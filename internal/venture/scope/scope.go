// Package scope defines owner-private business and product ownership for the
// venture pilot. Transport handlers and workers resolve scope before accessing
// resources. The organisation and delegation models are separate contracts.
package scope

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/benebsworth/omega/internal/auth"
)

var (
	// ErrUnavailable is the same for missing, malformed, and inaccessible resources.
	ErrUnavailable = errors.New("venture resource unavailable")
	// ErrLookup is safe to return when the scoped lookup fails.
	ErrLookup = errors.New("venture ownership lookup failed")
)

// Level is set by the endpoint or job definition. A missing product must never
// turn a product operation into a business operation.
type Level uint8

const (
	Business Level = iota + 1
	Product
)

// Target contains only resource IDs. The request does not select an owner.
type Target struct {
	BusinessID string
	ProductID  string
}

// Reference is the ownership recorded on a resource or a queued job.
type Reference struct {
	OwnerID string
	Target
}

// Lookup reads an ownership reference by its full composite key. It returns
// found=false for missing records. Writes must run lookup and mutation against
// the same transaction or check current ownership at the mutation boundary.
type Lookup func(ctx context.Context, key Reference) (record Reference, found bool, err error)

// Scope records a successful lookup. Resolve it again in each request or job.
type Scope struct {
	ref Reference
}

func (s Scope) Reference() Reference { return s.ref }

// Matches checks exact scope. A business scope does not act as a wildcard over
// project rows, cache entries, or search results.
func (s Scope) Matches(ref Reference) bool {
	return s.ref.OwnerID != "" && s.ref == ref
}

// Resolve takes tenancy from the authenticated owner in context. An API key
// has no owner grant in this pilot, even when its key ID equals an owner ID.
func Resolve(ctx context.Context, level Level, target Target, lookup Lookup) (Scope, error) {
	owner, err := ownerFromContext(ctx)
	if err != nil {
		return Scope{}, err
	}
	return resolve(ctx, level, Reference{OwnerID: owner, Target: target}, lookup)
}

// RevalidateJob uses fresh authenticated context and current ownership. The
// stored reference only identifies the target and cannot supply authority.
func RevalidateJob(ctx context.Context, level Level, queued Reference, lookup Lookup) (Scope, error) {
	owner, err := ownerFromContext(ctx)
	if err != nil || owner != queued.OwnerID {
		return Scope{}, ErrUnavailable
	}
	return resolve(ctx, level, queued, lookup)
}

func ownerFromContext(ctx context.Context) (string, error) {
	identity, ok := auth.IdentityFromContext(ctx)
	if !ok || identity.KeyID != "" || !validID(identity.Subject) {
		return "", ErrUnavailable
	}
	return identity.Subject, nil
}

func resolve(ctx context.Context, level Level, ref Reference, lookup Lookup) (Scope, error) {
	if !validID(ref.BusinessID) ||
		(level == Business && ref.ProductID != "") ||
		(level == Product && !validID(ref.ProductID)) ||
		(level != Business && level != Product) {
		return Scope{}, ErrUnavailable
	}
	if lookup == nil {
		return Scope{}, ErrLookup
	}
	business := Reference{OwnerID: ref.OwnerID, Target: Target{BusinessID: ref.BusinessID}}
	if err := lookupExact(ctx, lookup, business); err != nil {
		return Scope{}, err
	}
	if level == Product {
		if err := lookupExact(ctx, lookup, ref); err != nil {
			return Scope{}, err
		}
	}
	return Scope{ref: ref}, nil
}

func lookupExact(ctx context.Context, lookup Lookup, expected Reference) error {
	ref, found, err := lookup(ctx, expected)
	if err != nil {
		return ErrLookup
	}
	if !found || ref != expected {
		return ErrUnavailable
	}
	return nil
}

// KeyUse separates independently addressed records that share a resource ID.
type KeyUse string

const (
	Artifact KeyUse = "artifact"
	Cache    KeyUse = "cache"
	Job      KeyUse = "job"
	Search   KeyUse = "search"
)

// Key derives an opaque, versioned key from the full resolved scope and record
// ID. Resolve scope before addressing a key. Possession of a key grants no access.
func (s Scope) Key(use KeyUse, id string) (string, error) {
	switch use {
	case Artifact, Cache, Job, Search:
	default:
		return "", ErrUnavailable
	}
	if s.ref.OwnerID == "" || !validID(id) {
		return "", ErrUnavailable
	}
	digest := sha256.Sum256([]byte(strings.Join([]string{
		string(use), s.ref.OwnerID, s.ref.BusinessID, s.ref.ProductID, id,
	}, "\x00")))
	return "omega-venture/v1/" + string(use) + "/" + hex.EncodeToString(digest[:]), nil
}

// IDs remain opaque and case-sensitive. Controls include the key separator.
func validID(value string) bool {
	return len(value) > 0 && len(value) <= 256 && utf8.ValidString(value) &&
		value == strings.TrimSpace(value) && !strings.ContainsFunc(value, unicode.IsControl)
}
