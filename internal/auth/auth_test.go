package auth

import (
	"context"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// ---- JWT tests ----

func TestJWT_ValidHS256Token(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "supersecret")
	t.Setenv("OMEGA_JWT_ISSUER", "")
	v, err := NewValidator()
	require.NoError(t, err)

	tokenStr, err := v.IssueToken("user-1", []string{"admin"}, time.Hour)
	require.NoError(t, err)
	require.NotEmpty(t, tokenStr)

	claims, err := v.ValidateToken(tokenStr)
	require.NoError(t, err)
	assert.Equal(t, "user-1", claims.Subject)
	assert.Equal(t, []string{"admin"}, claims.Roles)
	assert.True(t, claims.ExpiresAt.After(time.Now()))
}

func TestJWT_ExpiredToken(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "supersecret")
	v, err := NewValidator()
	require.NoError(t, err)

	// Issue a token that expires immediately (negative TTL = already expired)
	tokenStr, err := v.IssueToken("user-2", nil, -time.Second)
	require.NoError(t, err)

	_, err = v.ValidateToken(tokenStr)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "token validation failed")
}

func TestJWT_TamperedSignature(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "supersecret")
	v, err := NewValidator()
	require.NoError(t, err)

	tokenStr, err := v.IssueToken("user-3", nil, time.Hour)
	require.NoError(t, err)

	// Tamper by appending a character.
	tampered := tokenStr + "X"
	_, err = v.ValidateToken(tampered)
	assert.Error(t, err)
}

func TestJWT_WrongIssuer(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "supersecret")
	t.Setenv("OMEGA_JWT_ISSUER", "expected-issuer")
	v, err := NewValidator()
	require.NoError(t, err)

	// Issue with the correct issuer.
	tokenStr, err := v.IssueToken("user-4", nil, time.Hour)
	require.NoError(t, err)

	// Now create a validator that expects a different issuer.
	t.Setenv("OMEGA_JWT_ISSUER", "wrong-issuer")
	vWrong, err := NewValidator()
	require.NoError(t, err)

	_, err = vWrong.ValidateToken(tokenStr)
	assert.Error(t, err)
}

func TestJWT_IssueTokenRequiresHS256(t *testing.T) {
	// A validator with no secret configured (algorithm = "none") cannot issue tokens.
	v := &Validator{algorithm: "none"}
	_, err := v.IssueToken("user", nil, time.Hour)
	assert.Error(t, err)
}

func TestJWT_AuthEnabledNoKey(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "")
	t.Setenv("OMEGA_JWT_PUBLIC_KEY", "")
	t.Setenv("OMEGA_AUTH_ENABLED", "true")
	_, err := NewValidator()
	assert.Error(t, err)
}

// ---- API key tests ----

func TestAPIKey_KnownKeyPasses(t *testing.T) {
	t.Setenv("OMEGA_API_KEYS", "mykey123")
	ks := NewKeyStore()

	id, err := ks.Validate("mykey123")
	require.NoError(t, err)
	assert.Equal(t, "mykey123", id.Subject)
	assert.Equal(t, "mykey123", id.KeyID)
}

func TestAPIKey_NamedKeyPasses(t *testing.T) {
	t.Setenv("OMEGA_API_KEYS", "svc-a:secretA,svc-b:secretB")
	ks := NewKeyStore()

	id, err := ks.Validate("secretA")
	require.NoError(t, err)
	assert.Equal(t, "svc-a", id.Subject)
	assert.Equal(t, "svc-a", id.KeyID)
}

func TestAPIKey_UnknownKeyFails(t *testing.T) {
	t.Setenv("OMEGA_API_KEYS", "goodkey")
	ks := NewKeyStore()

	_, err := ks.Validate("badkey")
	assert.Error(t, err)
}

func TestAPIKey_EmptyKeyFails(t *testing.T) {
	ks := NewKeyStore()
	_, err := ks.Validate("")
	assert.Error(t, err)
}

// ---- Rate limiting tests ----

func TestAPIKey_RateLimit(t *testing.T) {
	t.Setenv("OMEGA_API_RATE_LIMIT", "5")
	ks := NewKeyStore()

	// Allow burst (5 * 2 = 10) then expect false.
	allowed := 0
	denied := 0
	for i := 0; i < 20; i++ {
		if ks.Allow("test-key") {
			allowed++
		} else {
			denied++
		}
	}
	assert.Greater(t, allowed, 0, "some requests should be allowed")
	assert.Greater(t, denied, 0, "some requests should be denied after burst exhausted")
}

// ---- Middleware tests ----

// fakeHeader is a minimal map-backed header for testing authenticate().
type fakeHeader map[string]string

func (h fakeHeader) Get(key string) string { return h[key] }


func TestMiddleware_AllowlistedProcedureBypassesAuth(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "test-secret")
	v, _ := NewValidator()
	ks := NewKeyStore()
	cfg := DefaultConfig()
	cfg.Enabled = true

	interceptor := NewInterceptor(cfg, v, ks)
	ai := interceptor.(*authInterceptor)

	ctx := context.Background()
	// No auth header — but procedure is in allowlist.
	newCtx, err := ai.authenticate(ctx, "/grpc.health.v1.Health/Check", fakeHeader{})
	assert.NoError(t, err)
	assert.Equal(t, ctx, newCtx) // context unchanged (no identity added)
}

func TestMiddleware_NoTokenReturnsUnauthenticated(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "test-secret")
	v, _ := NewValidator()
	ks := NewKeyStore()
	cfg := Config{Enabled: true, Allowlist: []string{"/grpc.health.v1.Health/"}}

	interceptor := NewInterceptor(cfg, v, ks)
	ai := interceptor.(*authInterceptor)

	ctx := context.Background()
	_, err := ai.authenticate(ctx, "/omega.v1.SomeService/DoSomething", fakeHeader{})
	require.Error(t, err)

	var connectErr *connect.Error
	require.ErrorAs(t, err, &connectErr)
	assert.Equal(t, connect.CodeUnauthenticated, connectErr.Code())
}

func TestMiddleware_AuthDisabledPassesAll(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "test-secret")
	v, _ := NewValidator()
	ks := NewKeyStore()
	cfg := Config{Enabled: false, Allowlist: nil}

	interceptor := NewInterceptor(cfg, v, ks)
	ai := interceptor.(*authInterceptor)

	ctx := context.Background()
	newCtx, err := ai.authenticate(ctx, "/omega.v1.SomeService/DoSomething", fakeHeader{})
	assert.NoError(t, err)
	assert.Equal(t, ctx, newCtx)
}

func TestMiddleware_ValidJWTPassesAndSetsIdentity(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "test-secret")
	v, err := NewValidator()
	require.NoError(t, err)

	token, err := v.IssueToken("alice", []string{"reader"}, time.Hour)
	require.NoError(t, err)

	ks := NewKeyStore()
	cfg := Config{Enabled: true, Allowlist: nil}

	interceptor := NewInterceptor(cfg, v, ks)
	ai := interceptor.(*authInterceptor)

	ctx := context.Background()
	newCtx, authErr := ai.authenticate(ctx, "/omega.v1.SomeService/DoSomething", fakeHeader{
		"Authorization": "Bearer " + token,
	})
	require.NoError(t, authErr)

	id, ok := IdentityFromContext(newCtx)
	require.True(t, ok)
	assert.Equal(t, "alice", id.Subject)
}

func TestMiddleware_ValidAPIKeyPassesAndSetsIdentity(t *testing.T) {
	t.Setenv("OMEGA_JWT_SECRET", "test-secret")
	v, _ := NewValidator()
	t.Setenv("OMEGA_API_KEYS", "svc-x:mykeyvalue")
	ks := NewKeyStore()
	cfg := Config{Enabled: true, Allowlist: nil}

	interceptor := NewInterceptor(cfg, v, ks)
	ai := interceptor.(*authInterceptor)

	ctx := context.Background()
	newCtx, err := ai.authenticate(ctx, "/omega.v1.SomeService/DoSomething", fakeHeader{
		"X-Api-Key": "mykeyvalue",
	})
	require.NoError(t, err)

	id, ok := IdentityFromContext(newCtx)
	require.True(t, ok)
	assert.Equal(t, "svc-x", id.Subject)
}

// ---- IdentityFromContext ----

func TestIdentityFromContext_Empty(t *testing.T) {
	ctx := context.Background()
	id, ok := IdentityFromContext(ctx)
	assert.False(t, ok)
	assert.Nil(t, id)
}

