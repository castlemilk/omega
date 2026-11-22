package scope_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/benebsworth/omega/internal/auth"
	"github.com/benebsworth/omega/internal/venture/scope"
)

func authenticatedContext(t *testing.T, subject string, apiKey bool) context.Context {
	t.Helper()
	t.Setenv("OMEGA_JWT_SECRET", "local-scope-contract-fixture")
	t.Setenv("OMEGA_JWT_ISSUER", "test-omega")
	t.Setenv("OMEGA_API_KEYS", "")
	validator, err := auth.NewValidator()
	require.NoError(t, err)
	req := connect.NewRequest(&struct{}{})
	if apiKey {
		t.Setenv("OMEGA_API_KEYS", subject+":scope-fixture-key")
		req.Header().Set("X-Api-Key", "scope-fixture-key")
	} else {
		token, err := validator.IssueToken(subject, nil, time.Hour)
		require.NoError(t, err)
		req.Header().Set("Authorization", "Bearer "+token)
	}
	var authenticated context.Context
	handler := auth.NewInterceptor(auth.Config{Enabled: true}, validator, auth.NewKeyStore()).WrapUnary(
		func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
			authenticated = ctx
			return connect.NewResponse(&struct{}{}), nil
		},
	)
	_, err = handler(context.Background(), req)
	require.NoError(t, err)
	require.NotNil(t, authenticated)
	return authenticated
}

func reference(owner, business, product string) scope.Reference {
	return scope.Reference{OwnerID: owner, Target: scope.Target{BusinessID: business, ProductID: product}}
}

type directory map[scope.Reference]string

func (d directory) lookup(_ context.Context, ref scope.Reference) (scope.Reference, bool, error) {
	_, found := d[ref]
	return ref, found, nil
}

func TestResolveSeparatesOwnersWithIdenticalCatalogues(t *testing.T) {
	ownerA := authenticatedContext(t, "user:alpha", false)
	ownerB := authenticatedContext(t, "user:beta", false)
	businessA, productA := reference("user:alpha", "business-1", ""), reference("user:alpha", "business-1", "product-1")
	businessB, productB := reference("user:beta", "business-1", ""), reference("user:beta", "business-1", "product-1")
	d := directory{
		businessA: "Example Press", productA: "Field poster",
		businessB: "Example Press", productB: "Field poster",
	}

	var queries []scope.Reference
	lookup := func(ctx context.Context, key scope.Reference) (scope.Reference, bool, error) {
		queries = append(queries, key)
		return d.lookup(ctx, key)
	}
	a, err := scope.Resolve(ownerA, scope.Product, productA.Target, lookup)
	require.NoError(t, err)
	b, err := scope.Resolve(ownerB, scope.Product, productA.Target, lookup)
	require.NoError(t, err)
	assert.Equal(t, []scope.Reference{businessA, productA, businessB, productB}, queries)
	assert.Equal(t, productA, a.Reference())
	assert.Equal(t, productB, b.Reference())
	assert.True(t, a.Matches(productA))
	assert.False(t, a.Matches(productB))
	assert.False(t, b.Matches(productA))
}

func TestResolveRejectsMissingIdentityAndLegacyKeyBeforeLookup(t *testing.T) {
	keyCtx := authenticatedContext(t, "owner-a", true)
	for _, ctx := range []context.Context{context.Background(), keyCtx} {
		_, err := scope.Resolve(ctx, scope.Product, reference("owner-a", "press", "poster").Target,
			func(context.Context, scope.Reference) (scope.Reference, bool, error) {
				t.Fatal("unauthorised request reached lookup")
				return scope.Reference{}, false, nil
			})
		require.ErrorIs(t, err, scope.ErrUnavailable)
	}
}

func TestResolveRequiresAnExactOwnerBusinessProductTuple(t *testing.T) {
	ctx := authenticatedContext(t, "owner-a", false)
	product := reference("owner-a", "press", "poster")
	for _, tc := range []struct {
		name   string
		level  scope.Level
		target scope.Target
		stored scope.Reference
	}{
		{"product cannot fall back to business", scope.Product, scope.Target{BusinessID: "press"}, product},
		{"business operation expects no product", scope.Business, product.Target, product},
		{"unrecognised level", 0, product.Target, product},
		{"unknown product", scope.Product, product.Target, scope.Reference{}},
		{"row from another owner", scope.Product, product.Target, reference("owner-b", "press", "poster")},
		{"row from another business", scope.Product, product.Target, reference("owner-a", "other-press", "poster")},
		{"invalid product ID", scope.Product, scope.Target{BusinessID: "press", ProductID: "post\x00er"}, product},
	} {
		t.Run(tc.name, func(t *testing.T) {
			resolved, err := scope.Resolve(ctx, tc.level, tc.target, func(_ context.Context, key scope.Reference) (scope.Reference, bool, error) {
				if key.ProductID == "" {
					return key, true, nil
				}
				return tc.stored, tc.stored != (scope.Reference{}), nil
			})
			require.ErrorIs(t, err, scope.ErrUnavailable)
			assert.False(t, resolved.Matches(product))
		})
	}
}

func TestScopeKeysSeparateResourceKindsAndBoundaries(t *testing.T) {
	ownerA := authenticatedContext(t, "owner-a", false)
	ownerB := authenticatedContext(t, "owner-b", false)
	business := scope.Target{BusinessID: "field/press"}
	project := scope.Target{BusinessID: business.BusinessID, ProductID: "poster"}
	d := directory{
		{OwnerID: "owner-a", Target: business}: "Field Press",
		{OwnerID: "owner-a", Target: project}:  "Poster",
		{OwnerID: "owner-b", Target: business}: "Field Press",
		{OwnerID: "owner-b", Target: project}:  "Poster",
	}
	a, err := scope.Resolve(ownerA, scope.Product, project, d.lookup)
	require.NoError(t, err)
	b, err := scope.Resolve(ownerB, scope.Product, project, d.lookup)
	require.NoError(t, err)
	businessA, err := scope.Resolve(ownerA, scope.Business, business, d.lookup)
	require.NoError(t, err)
	assert.False(t, businessA.Matches(a.Reference()))

	original, err := a.Key(scope.Artifact, "proof")
	require.NoError(t, err)
	assert.Regexp(t, "^omega-venture/v1/artifact/[a-f0-9]{64}$", original)
	again, err := a.Key(scope.Artifact, "proof")
	require.NoError(t, err)
	assert.Equal(t, original, again)
	seen := map[string]bool{original: true}
	for _, candidate := range []struct {
		resolved scope.Scope
		use      scope.KeyUse
		id       string
	}{
		{b, scope.Artifact, "proof"},
		{businessA, scope.Artifact, "proof"},
		{a, scope.Artifact, "proof-2"},
		{a, scope.Cache, "proof"},
		{a, scope.Job, "proof"},
		{a, scope.Search, "proof"},
	} {
		key, err := candidate.resolved.Key(candidate.use, candidate.id)
		require.NoError(t, err)
		assert.False(t, seen[key], "composite keys must stay separate")
		seen[key] = true
	}
	_, err = (scope.Scope{}).Key(scope.Artifact, "proof")
	require.ErrorIs(t, err, scope.ErrUnavailable)
	_, err = a.Key(scope.Artifact, "proof\x00raw")
	require.ErrorIs(t, err, scope.ErrUnavailable)
	_, err = a.Key(scope.KeyUse("other"), "proof")
	require.ErrorIs(t, err, scope.ErrUnavailable)
}

func TestWorkerRevalidatesCurrentOwnerAndParent(t *testing.T) {
	ctx := authenticatedContext(t, "owner-a", false)
	product := reference("owner-a", "press", "poster")
	business := reference("owner-a", "press", "")
	d := directory{business: "Press", product: "Poster"}
	saved, err := scope.Resolve(ctx, scope.Product, product.Target, d.lookup)
	require.NoError(t, err)
	queued := saved.Reference()

	reopened, err := scope.RevalidateJob(ctx, scope.Product, queued, d.lookup)
	require.NoError(t, err)
	assert.Equal(t, saved, reopened)
	unrelated := authenticatedContext(t, "owner-b", false)
	_, err = scope.RevalidateJob(unrelated, scope.Product, queued, d.lookup)
	require.ErrorIs(t, err, scope.ErrUnavailable)
	_, err = scope.RevalidateJob(ctx, scope.Product, business, d.lookup)
	require.ErrorIs(t, err, scope.ErrUnavailable)

	delete(d, business)
	_, err = scope.RevalidateJob(ctx, scope.Product, queued, d.lookup)
	require.ErrorIs(t, err, scope.ErrUnavailable)
	d[business] = "Press"

	delete(d, product)
	d[reference("owner-a", "new-press", "")] = "New Press"
	d[reference("owner-a", "new-press", "poster")] = "Poster"
	_, err = scope.RevalidateJob(ctx, scope.Product, queued, d.lookup)
	require.ErrorIs(t, err, scope.ErrUnavailable)
}

func TestFailuresUseAStableErrorWithoutBackendDetails(t *testing.T) {
	ctx := authenticatedContext(t, "owner-a", false)
	target := scope.Target{BusinessID: "press"}
	cause := errors.New("test database error containing a private row")
	_, err := scope.Resolve(ctx, scope.Business, target, func(context.Context, scope.Reference) (scope.Reference, bool, error) {
		return scope.Reference{}, false, cause
	})
	require.Equal(t, scope.ErrLookup, err)
	_, err = scope.Resolve(ctx, scope.Business, target, nil)
	require.ErrorIs(t, err, scope.ErrLookup)
}
