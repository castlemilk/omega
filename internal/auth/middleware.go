package auth

import (
	"context"
	"errors"
	"os"
	"strings"

	"connectrpc.com/connect"
)

// Identity represents an authenticated principal — either a JWT subject or an API key holder.
type Identity struct {
	Subject string
	Roles   []string
	KeyID   string // non-empty only for API key auth
}

// contextKey is the unexported type used as the context key for Identity.
type contextKey struct{}

// Config controls authentication enforcement for the interceptor.
type Config struct {
	// Enabled — when false all requests pass without authentication.
	Enabled bool
	// Allowlist is a list of procedure prefixes that bypass authentication.
	Allowlist []string
}

// DefaultConfig reads OMEGA_AUTH_ENABLED and returns a Config with sensible defaults.
func DefaultConfig() Config {
	return Config{
		Enabled: os.Getenv("OMEGA_AUTH_ENABLED") == "true",
		Allowlist: []string{
			"/grpc.health.v1.Health/",
			"/omega.v1.OrchestratorService/GetSystemHealth",
		},
	}
}

// authInterceptor implements connect.Interceptor.
type authInterceptor struct {
	cfg      Config
	jwt      *Validator
	keyStore *KeyStore
}

// NewInterceptor returns a Connect-RPC interceptor that enforces JWT or API key auth.
// Procedures matching cfg.Allowlist prefixes are always allowed through.
// When cfg.Enabled is false, all requests pass without authentication.
func NewInterceptor(cfg Config, jwtValidator *Validator, keyStore *KeyStore) connect.Interceptor {
	return &authInterceptor{
		cfg:      cfg,
		jwt:      jwtValidator,
		keyStore: keyStore,
	}
}

// WrapUnary implements connect.Interceptor for unary RPCs.
func (a *authInterceptor) WrapUnary(next connect.UnaryFunc) connect.UnaryFunc {
	return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		newCtx, err := a.authenticate(ctx, req.Spec().Procedure, req.Header())
		if err != nil {
			return nil, err
		}
		return next(newCtx, req)
	}
}

// WrapStreamingClient implements connect.Interceptor for streaming client calls (pass-through).
func (a *authInterceptor) WrapStreamingClient(next connect.StreamingClientFunc) connect.StreamingClientFunc {
	return func(ctx context.Context, spec connect.Spec) connect.StreamingClientConn {
		return next(ctx, spec)
	}
}

// WrapStreamingHandler implements connect.Interceptor for streaming server-side RPCs.
func (a *authInterceptor) WrapStreamingHandler(next connect.StreamingHandlerFunc) connect.StreamingHandlerFunc {
	return func(ctx context.Context, conn connect.StreamingHandlerConn) error {
		newCtx, err := a.authenticate(ctx, conn.Spec().Procedure, conn.RequestHeader())
		if err != nil {
			return err
		}
		return next(newCtx, conn)
	}
}

// authenticate is the shared auth logic used by both unary and streaming wrappers.
func (a *authInterceptor) authenticate(ctx context.Context, procedure string, header interface {
	Get(string) string
}) (context.Context, error) {
	// Auth disabled — pass all.
	if !a.cfg.Enabled {
		return ctx, nil
	}

	// Check allowlist.
	for _, prefix := range a.cfg.Allowlist {
		if strings.HasPrefix(procedure, prefix) {
			return ctx, nil
		}
	}

	// Try Bearer JWT.
	if authHeader := header.Get("Authorization"); authHeader != "" {
		if len(authHeader) > 7 && strings.EqualFold(authHeader[:7], "Bearer ") && a.jwt != nil {
			tokenStr := authHeader[7:]
			claims, err := a.jwt.ValidateToken(tokenStr)
			if err == nil {
				id := &Identity{
					Subject: claims.Subject,
					Roles:   claims.Roles,
				}
				return context.WithValue(ctx, contextKey{}, id), nil
			}
		}
	}

	// Try API key.
	if apiKey := header.Get("X-Api-Key"); apiKey != "" {
		identity, err := a.keyStore.Validate(apiKey)
		if err == nil {
			if !a.keyStore.Allow(identity.KeyID) {
				return ctx, connect.NewError(connect.CodeResourceExhausted, errors.New("auth: rate limit exceeded"))
			}
			return context.WithValue(ctx, contextKey{}, identity), nil
		}
	}

	return ctx, connect.NewError(connect.CodeUnauthenticated, errors.New("auth: missing or invalid credentials"))
}

// IdentityFromContext retrieves the authenticated Identity from the context.
// Returns (nil, false) if no identity is present (e.g., auth disabled or allowlisted route).
func IdentityFromContext(ctx context.Context) (*Identity, bool) {
	id, ok := ctx.Value(contextKey{}).(*Identity)
	return id, ok && id != nil
}
