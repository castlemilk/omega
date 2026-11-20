# E05 Domain tenancy and migration

Source: https://chatgpt.com/space/page_b6ac4d6d71688191a18e8433691b19f5

All tickets are Proposed. The organisation is the proposed hard tenant boundary; ventures are economic/operational units, not automatically incorporated companies. The UI atlas consumes these contracts and does not authorise migration. Storage/runtime selection requires explicit architecture decisions.

## OME-033 Define tenant and resource ownership contracts

**P0 · Backend and security · M · Dependencies: OME-001, OME-003**

Specify ownership for APIs, records, object-store keys, jobs, cache entries and search results.

**Acceptance:** derive tenancy from authenticated context; reject cross-tenant composite references; test two owners with overlapping names; workers revalidate scope; errors do not disclose other tenants; preserve owner-private behaviour until collaboration is deliberately enabled.

**Screens:** S02, S03, S08, S20, S26, S29.

**UI acceptance:** scope reads, writes and caches. Business CRM remains business-scoped and content project-scoped until an approved mapping changes that.

**Evidence:** contract tests, ownership matrix and threat model.

## OME-034 Model ventures brands products and channels

**P0 · Domain engineering · M · Dependencies: OME-033**

Define organisation, portfolio, venture, legal-entity reference, brand, product, offer and channel-listing records with stable IDs and explicit cardinalities.

**Acceptance:** separate economics from brand presentation; multiple listings do not duplicate product ownership; legal entities relate to multiple ventures through dated associations; archive differs from deletion; review existing project mappings before backfill.

**Screens:** S02, S03, S06, S07, S16.

**UI acceptance:** explicit Product/Project/Venture mapping and independent brand/channel identity; import preview exposes unresolved associations and duplicates instead of selecting silently.

**Evidence:** entity diagram, validation rules and representative fixtures.

## OME-035 Model spawning lineage and portfolio membership

**P1 · Domain engineering · M · Dependencies: OME-034**

Record origin opportunity, parent venture and copied playbook version separately from current portfolio membership and legal relationships.

**Acceptance:** reject lineage cycles; independent grants/budget for new ventures; moves preserve audit; initially one primary portfolio per venture; consolidate each economic record once; no cross-organisation transfer without separate migration design.

**Screens:** S06, S19, S28.

**UI acceptance:** preserve copy/reference semantics and origin; child budgets, grants and customers do not automatically inherit; totals count once.

**Evidence:** fork/move/archive tests and aggregation fixtures.

## OME-036 Version strategic and executable objects

**P0 · Backend · M · Dependencies: OME-034**

Immutable versions for theses, hypotheses, brand kits, agent definitions, mandates, policies, workflows and product manifests.

**Acceptance:** runs reference exact versions; optimistic concurrency protects drafts; approvals bind digests; retired versions remain readable for authorised audit; draft deletion cannot erase executed versions; current-version pointers cannot bypass validation.

**Screens:** S05, S09–S17, S23–S25.

**UI acceptance:** version-bound review/run/handoff; changed-source impact preview; invalidate affected approvals and preserve historical receipts.

**Evidence:** concurrent-edit, version-resolution and historical replay tests.

## OME-037 Decide persistence and service evolution

**P0 before storage migration · Architecture · M · Dependencies: OME-003, OME-033, OME-034**

Compare extending current D1/Connect-ES repositories with PostgreSQL/separate Go services through a small prototype evaluating transactions, isolation, operations, cost, backups and migration complexity.

**Acceptance:** measured constraints and rejected alternatives; explicit WorkspaceRepository/PipelineRepository contracts; no production rewrite hidden in spike; demonstrate transaction/reservation requirements on chosen backend.

**Screens:** S12, S19, S25, S27.

**UI acceptance:** storage/provider selection stays outside visual redesign. Demonstrate persistence, reservations and reconciliation without changing boundaries for UI convenience.

**Evidence:** architecture decision and repeatable benchmark, not framework preference.

## OME-038 Define business events and provenance envelopes

**P0 · Backend and data · M · Dependencies: OME-033, OME-036**

Specify event ID, tenant, venture, actor, resource version, causation, correlation, policy decision, timestamp, schema version and minimal receipt references.

**Acceptance:** atomic outbox or documented equivalent; deduplicating consumers; event/ingestion times for late events; minimise sensitive payloads; compatible schema evolution; separately queryable fact/inference/forecast provenance.

**Screens:** S05, S17, S19, S25–S27.

**UI acceptance:** actor/scope/version/correlation and separate timestamps; duplicate/late events must not duplicate actions or totals.

**Evidence:** duplicate, reordered and partial-failure event tests.

## OME-039 Implement scoped roles and service principals

**P0 before delegated access · Security and backend · L · Dependencies: OME-033, OME-034**

Define owner, operator, reviewer, finance and read-only capabilities, plus non-human principals scoped to ventures/tools.

**Acceptance:** deny by default; delegated reviewers stay within authority; revocation affects new reads/writes; caches/exports obey scope; agents cannot self-grant; auditable policy decisions; service principals are not shared human sessions.

**Screens:** S17, S23, S26, S29.

**UI acceptance:** effective role/capability preview comes from authoritative evaluation. Revalidate pending actions after revocation; hidden buttons are not enforcement.

**Evidence:** positive/negative permission matrix across UI, APIs and workers.

## OME-040 Rehearse backward-compatible migration and recovery

**P0 before writable venture rollout · Backend and reliability · L · Dependencies: OME-003, OME-034, OME-036, OME-037, OME-038**

Plan expand/backfill/verify/cutover preserving IDs, revision checks, business boundaries and protobuf compatibility.

**Acceptance:** demonstrate restoration; reconcile counts/digests; resumable idempotent backfill; stale clients cannot erase updates; separate schema/data migrations; document rollback limits; no reset or owner-scope widening.

**Screens:** S02, S27, S29.

**UI acceptance:** migration dry-run comparison, count/hash reconciliation, resumable progress and recovery evidence. Retain old-client/save compatibility.

**Evidence:** rehearsal report and approved cutover checklist. This ticket does not authorise running migration.
