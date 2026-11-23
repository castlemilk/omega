# E06 Discovery and validation

Source: https://chatgpt.com/space/page_d4d61a09862081919e986d86f9c01f84

All tickets are Proposed. Agent ideas are hypotheses, not validated demand. First experiments suit existing digital products; broader sourcing/paid tests are gated. Readable source ledgers and decision panels take precedence over decorative terrain.

## OME-041 Build opportunity and evidence intake

**P1 · Research systems · M · Dependencies: OME-034, OME-036, OME-038**

Capture opportunities from briefs, imported research and approved sources, retaining problem, audience, alternatives, proposed offer and next test.

**Acceptance:** retain URLs, dates and snapshots/permitted excerpts; distinguish fact/inference; show failed retrieval; reconcile duplicates; record access/retention rules; untrusted content cannot instruct execution.

**Screens:** S04 → S05.

**UI acceptance:** expose source/date/scope/claim type; retain candidate and notes during failed retrieval and duplicate reconciliation.

**Evidence:** complete, conflicting and missing-source fixtures.

## OME-042 Normalise market signals and competitor records

**P1 · Data engineering · M · Dependencies: OME-041, OME-005**

Model competitors, products, prices, reviews and demand signals with entity resolution, windows and provenance.

**Acceptance:** names alone do not establish identity; currencies/units explicit; changed prices append observations; duplicate reviews are not independent evidence; collection failures do not imply absence; respect configured limits.

**Screens:** S04 comparison.

**UI acceptance:** resolved identity, observation dates and duplicate-source relationships; competitors never appear as owned ventures.

**Evidence:** normalisation tests and dated source-quality register.

## OME-043 Implement transparent opportunity ranking

**P1 · Product analytics · M · Dependencies: OME-041, OME-042**

Rank explicit customer pain, evidence quality, cost, competition, operating burden and owner constraints.

**Acceptance:** inspect factors/weights; missing stays missing; show sensitivity; exclusions override attractive scores; rankings are not calibrated success probabilities; record override reasons.

**Screens:** S04 ranking inspector.

**UI acceptance:** expose missing factors, weights, exclusions and reasons; no invented revenue potential or uncalibrated percentages.

**Evidence:** scoring fixtures, sensitivity examples and retrospective protocol.

## OME-044 Create experiment protocols and stop rules

**P0 before running experiments · Product and backend · M · Dependencies: OME-036, OME-041**

Record hypothesis, primary metric, measurement window, audience, variant, budget, minimum evidence and decision rule before execution.

**Acceptance:** edits create versions; record post-results metric changes; time/cost/adverse stop conditions; incomplete samples are inconclusive; external actions require separate mandate/approval.

**Screens:** S05 → S18.

**UI acceptance:** version audience/method/metric/denominator/window/ceiling/rules; post-observation edits remain visible.

**Evidence:** experiment state machine and protocol tests.

## OME-045 Build low-cost validation templates

**P1 · Research and workflow design · M · Dependencies: OME-044**

Reusable protocols for competitor-review synthesis, interviews, concept preference, waitlists and small landing-page tests.

**Acceptance:** declare capabilities/side effects; synthetic respondents never count as customer evidence; retain recruitment/consent provenance; research-only path requires no ads; estimated launch costs differ from incurred costs.

**Screens:** S05 template selection.

**UI acceptance:** inspect capability/side-effect requirements before selection; retain research-only route and explicit synthetic labels.

**Evidence:** three executable pilot protocols with failure/cancellation paths.

## OME-046 Ingest observations and assess outcomes

**P1 · Analytics and backend · M · Dependencies: OME-044, OME-038**

Attach observations to exact experiment versions with denominator, period, attribution and data quality.

**Acceptance:** reject duplicates; rates show sample size/uncertainty; attribution gaps explicit; document early stopping/multiple comparisons; inconclusive is valid; permitted reviewers can inspect raw observations.

**Screens:** S18 → S05.

**UI acceptance:** unavailable, insufficient and inconclusive differ from zero/failed; source and attribution limits remain accessible on mobile.

**Evidence:** known outcomes plus missing/delayed/contradictory measurements.

## OME-047 Record continue pivot pause and stop decisions

**P1 · Product and decision systems · M · Dependencies: OME-043, OME-046**

Decision brief compares options, evidence, sunk costs, further commitments and cheapest useful next test.

**Acceptance:** recommendation differs from authorised decision; include counterevidence; permitted actors make transitions; stop preserves artifacts/obligations; agents cannot silently increase limits; later outcomes link to decision.

**Screens:** S05 → S07.

**UI acceptance:** supporting/contrary evidence and separate recommendation/decision actors and records.

**Evidence:** reviewed continue, inconclusive, pivot and stop cases.

## OME-048 Produce the validation-to-build handoff

**P1 · Product and workflow design · M · Dependencies: OME-047, OME-036**

Convert reviewed thesis into audience, offer, success criteria, brand brief, artifact requirements and launch constraints.

**Acceptance:** evidence or explicit assumption per requirement; archetype selects template; unresolved claims block readiness; immutable references; budget recommendation is not authority; tasks retain opportunity lineage.

**Screens:** S05 → S06 → S07.

**UI acceptance:** saving a version-bound handoff does not activate agents, publish or authorise spend.

**Evidence:** complete digital-product handoff without external publication.
