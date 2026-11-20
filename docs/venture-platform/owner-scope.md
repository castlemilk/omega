# Owner-private resource ownership

[OME-033](https://github.com/castlemilk/omega/issues/32) defines the
ownership contract for the venture pilot. The authenticated subject
supplies the owner ID. Business and Product retain their source IDs.
The organisation and venture mapping and delegated roles have separate
programme decisions. [OME-001](https://github.com/castlemilk/omega/issues/10)
· [OME-034](https://github.com/castlemilk/omega/issues/37)
· [OME-039](https://github.com/castlemilk/omega/issues/49)

## Ownership matrix

| Surface | Scope | Enforcement |
| --- | --- | --- |
| API and business CRM | Signed-in owner and business ID | The server selects `Business` and resolves the composite before reading or writing. |
| Product records and content | Signed-in owner, business ID and product ID | The server selects `Product` and checks both the parent and the exact product. |
| Artwork and object-storage addressing | The owning business or product tuple plus the record ID | Resolve ownership before deriving the artifact key or issuing an authorised URL. |
| Jobs | The exact persisted tuple under the worker's current authorised owner context | Revalidate at execution. A moved or missing product makes the prior tuple unavailable. |
| Caches | The full resolved tuple, purpose and record ID | Derive a cache key after each request's scope lookup. Authorise cache hits as well as misses. |
| Search | The resolved tuple for each searched branch | Filter by owner and resource scope, then use exact matching to verify each returned row. |

`internal/venture/scope` reads the authenticated identity from the
existing Connect middleware. The endpoint or job definition fixes the
required scope level. API inputs select the resource IDs. A scoped
directory lookup checks what is currently stored. The reader receives
the full expected tuple and returns the actual ownership of the record.
Business scope is exact. Portfolio search must enumerate authorised
branches before reading their product results.

Run lookups and mutations in the same transaction or recheck ownership
at the write boundary. A worker obtains current authority from its
adapter before resuming a queued job. The queue payload carries IDs for
addressing. Owner membership and execution authority are evaluated by
the caller's policy.

## Threat model

| Risk | Contract response |
| --- | --- |
| Two owners use identical names and resource IDs | Owner identity comes from authentication and participates in every lookup, result match and derived key. Display names have no authority. |
| A request combines an owned business with a product from another business or owner | The parent and product records must match their expected tuples exactly. A missing product fails a product-level request. |
| A legacy API key uses the same name as a user | The owner-private resolver requires a verified user identity. Service grants will have their own authority contract. |
| A job is resumed after its referenced product has moved | The original tuple is checked again against current storage. The prior result is scoped to its original resolution. |
| A cached result, search document or artifact key is reused across tenants | Scope includes owner, business and product as applicable. The key includes a version, purpose and record ID. A key is an opaque address. |
| A query probes for another owner's resources or returns a database error | Missing, malformed and inaccessible resources use the same unavailable error. Backend errors get a generic lookup failure. |

## Verification and integration status

```sh
go test ./internal/auth ./internal/venture/scope
go test -race ./internal/venture/scope
```

The tests use the existing auth interceptor, signed test identities and
a synthetic directory. They exercise overlapping names and IDs,
composite ownership, resumed jobs, key separation and redacted errors.
Wiring this contract into a hosted directory, application routes and
workers is a subsequent integration step.
