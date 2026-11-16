# E12 Integrations quality and rollout

Source: https://chatgpt.com/space/page_9972a8fb90208191bd756dd9032db9af

All tickets are Proposed. Source validation, CI, deployment, hosted acceptance and authority to activate external capabilities are separate gates. No paid provisioning, production migration or public rebrand is authorised by this backlog.

## OME-089 Define integration adapter and capability contracts

**P0 before integrations · Platform and integrations · M · Dependencies: OME-033, OME-036, OME-054, OME-059**

Standardise accounts, capabilities, schemas, provider versions, health, limits, test/live and read/draft/write modes across APIs/MCP.

**Acceptance:** unknown capability fails closed; broker credentials; installation is not all-action authority; actionable redacted provider errors; review capability changes; disclose idempotency/reconciliation; disconnected is not healthy.

**Screens:** S26.

**UI acceptance:** Not connected/Read only/Draft write/Live write with verified account/scope and capability inspector.

**Evidence:** contract harness and sandbox adapter. MCP is an interface, not security boundary.

## OME-090 Build the verified webhook inbox and reconciliation jobs

**P0 before provider events · Backend and reliability · L · Dependencies: OME-038, OME-054, OME-089**

Persist verified events before processing; deduplicate, order, bound retries, dead-letter and reconcile.

**Acceptance:** reject invalid signatures/expired replays; acknowledge after durable receipt; no duplicate domain events on retry; bounded parsing/payload; trusted-connection tenant resolution; recover missing events; inspectable dead-letter replay operation.

**Screens:** S26 event inbox, S25/S27.

**UI acceptance:** verified/duplicate/reordered/dead-letter/reconciled states; explicit replay identity; invalid signatures cannot create payment/publication success.

**Evidence:** forged, duplicate, reordered and interrupted-delivery tests.

## OME-091 Define privacy retention and deletion workflows

**P0 before customer data · Security and governance · M · Dependencies: OME-033, OME-036, OME-039, OME-054**

Classify personal/confidential/financial/public research data and define purpose, retention, export, deletion and audit minimisation.

**Acceptance:** avoid unnecessary personal data in prompts/traces; delete indexed/derived copies subject to documented obligations; minimal audit references not raw personal payloads; authenticated access requests; verify current official local rules; explicit unresolved retention requirements.

**Screens:** S29 Privacy, S20.

**UI acceptance:** purpose/retention/derived-copy inventory and authority/impact review; no invented periods or blanket removal claims before receipts.

**Evidence:** inventory and deletion/retrieval tests. No blanket compliance claim.

## OME-092 Provide portable exports and safe imports

**P1 · Platform and data · M · Dependencies: OME-034, OME-036, OME-039, OME-091**

Export definitions, artifacts, provenance, recipes, workflows and permitted records using versioned manifests.

**Acceptance:** exclude credentials; obey current scope; report digests/missing artifacts; validate schema/ownership before writing; deterministic duplicates; dry-run conflicts; export is not sharing; cross-organisation transfer requires separate authority/design.

**Screens:** S29 Exports, S15 packets, S02 import.

**UI acceptance:** explicit duplicate/conflict/schema/ownership errors; read-only packet review import remains distinct from mutation.

**Evidence:** round-trip fixtures and corrupt-package test.

## OME-093 Establish CI and regression release gates

**P0 for release · Quality and platform · L · Dependencies: OME-015, OME-033, OME-038, OME-052, OME-059**

Extend existing CI with domain/permission/approval/idempotency/persistence/visual/accessibility checks. Cuttlefish only through verified project and supported pipeline.

**Acceptance:** commit/environment provenance; no silent skip of required checks; investigate flakes; fixture visuals do not imply hosted acceptance; preserve editor/autosave regressions; runner success is not deployment.

**Screens:** all 32 families.

**UI acceptance:** exact revision, shared states, isolation, approval binding, uncertain-save recovery, visual and accessibility checks.

**Evidence:** reviewed CI and attested successful run on intended revision.

## OME-094 Define runtime observability and performance budgets

**P0 for operational release · SRE and frontend · M · Dependencies: OME-006, OME-064, OME-090**

Measure API latency, queue age, workflow completion, reconciliation lag, stream freshness, interface response and resource use; derive objectives from pilot/baseline.

**Acceptance:** targets labelled until measured; owner/runbook routing; budgeted telemetry without customer content; responsive long tables/workflows at agreed scale; reduced-motion avoids unnecessary render; observable event loss/staleness.

**Screens:** S03, S08, S24–S27.

**UI acceptance:** first-useful-content, long-list response, queue age, stale events and recovery latency distinguish targets, fixtures and measurements.

**Evidence:** load tests, browser traces, dated dashboards.

## OME-095 Verify deployment provenance and migration readiness

**P0 before deployment · Release engineering · M · Dependencies: OME-040, OME-093, OME-094**

Document actual hosted source, build, environment, schema, private boundary and rollback before release.

**Acceptance:** deployed artifact resolves to reviewed revision; rehearsed migration recovery; owner-private access preserved; environment-scoped credentials; hosted route/asset/persistence/service smoke tests; no old prototype presented as deployed source; unknown ownership blocks promotion.

**Screens:** S27 Release evidence.

**UI acceptance:** reviewed source/build/schema/environment/access/deployment receipt/hosted checks separate; prototype attachment cannot advance gate.

**Evidence:** deployment receipt and hosted acceptance. No public-access or paid-provisioning authority.

## OME-096 Run the staged pilot and capability rollout

**P0 for external-action pilot · Product, SRE and quality · L · Dependencies: OME-007, OME-032, OME-056, OME-069, OME-074, OME-088, OME-095**

Progress design agreement → read-only shell → supervised internal work → one approved external action → bounded operation using independent flags.

**Acceptance:** each stage enables only completed controls; future commerce does not block read-only design work; exact external test authority; retain feedback/failures; rollback stops dispatch without discarding receipts; expand from measured outcomes; public naming also requires OME-002.

**Screens:** complete pilot routes.

**UI acceptance:** stage-specific controls/evidence, preserved rollback and unresolved obligations.

**Evidence:** stage-by-stage acceptance and explicit continue/revise/stop decision.

### UI release checklist

- [ ] Recover exact implementation candidate and source ownership.
- [ ] Use a supported browser path; prior ERR_BLOCKED_BY_ADMINISTRATOR remains unresolved until new evidence. Do not change browser policy.
- [ ] S01–S32 identity, meaningful content, no framework overlay, console health and route transitions.
- [ ] Complete E04 desktop/390px/short-height/keyboard/200%-zoom/reduced-motion journeys.
- [ ] Loading, empty, no-results, partial, stale, denied, failed, conflict and unknown states.
- [ ] Compare actual renders with task-specific designs, not broad cinematic dashboards.
- [ ] Persisted save/readback, two-owner isolation, approval races and provider timeout reconciliation beyond session-only behaviour.
- [ ] Inspect actual bytes, manifests and entitlements before delivery.
- [ ] Record decision, defects and deployment receipts without marking disconnected capabilities Done.

Unchecked items are acceptance work, not failed tests or completed validation.
