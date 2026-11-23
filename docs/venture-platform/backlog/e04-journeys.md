# E04 Navigation and journeys

Source: https://chatgpt.com/space/page_a87059d370b08191873d2ef2b5265190

All tickets are Proposed. Prototype acceptance and live-service acceptance are separate. Terraform, Scout, Frontiers, Deploy, Operate, Expand and Sustain may provide thematic navigation when paired with clear task language; they must not conceal lifecycle, permission or execution state.

## OME-025 Build the scoped application shell

**P0 · Frontend · M · Dependencies: OME-010, OME-014, OME-024**

Provide organisation, portfolio and venture navigation, breadcrumbs, contextual search and a persistent intervention entry point.

**Acceptance:** scope is visible on every screen; switching scope clears incompatible selections/caches; deep links restore context; unauthorised resources reveal no names/counts; mobile retains urgent work; unsaved changes use OME-022 recovery.

**Screens:** S01–S29.

**UI acceptance:** Back/Forward, deep links and resource switching restore the correct context; resolve dirty drafts before switching. Customer storefronts S30–S32 and S13/S21 do not inherit the operator sidebar.

**Evidence:** route matrix and cross-scope navigation tests. Hiding navigation does not establish backend access control.

## OME-026 Build the portfolio command view

**P0 · Frontend and product · M · Dependencies: OME-017, OME-020, OME-021, OME-025**

Prioritise decisions, blockers and venture health over background activity. Use a registry with compact economics and source freshness.

**Acceptance:** selected period applies consistently; attention items link to exact records; missing financial sources remain explicit; lifecycle, health and autonomy are independent; closed ventures remain discoverable without crowding active work; fixtures are labelled.

**Screens:** S03.

**UI acceptance:** decisions and exceptions precede the registry. Distinguish project, product, storefront and venture records. Show No live data imported where appropriate; attention items open exact resources.

**Evidence:** desktop/narrow prototypes followed by live aggregation tests.

## OME-027 Build the three onboarding entry paths

**P1 · Product design and frontend · M · Dependencies: OME-004, OME-024, OME-025**

Support Find an opportunity, Develop an idea and Bring an existing business. Collect objectives, exclusions, region, time commitment and proposed budget without requesting all integrations immediately.

**Acceptance:** save/resume progress; detect existing records before duplication; budget fields never charge; request credentials only when needed; each path ends in a useful draft and next action.

**Screens:** S01 → S04, S06 or S02.

**UI acceptance:** returning users can open an existing workspace. Field errors retain entered values; proposed budgets/import choices do not grant execution authority.

**Evidence:** complete journey prototypes and abandonment/recovery tests.

## OME-028 Build the venture creation and spawning journey

**P1 · Frontend and product · M · Dependencies: OME-027, OME-034, OME-035**

Create a venture from an opportunity, playbook or existing venture with explicit lineage and resource selection.

**Acceptance:** users select artifacts to copy/reference; customers, credentials and approval authority are excluded by default; budgets are separately authorised; naming conflicts are resolved; retries do not duplicate creation; drafts are distinct from agent activation.

**Screens:** S06, S02, S28.

**UI acceptance:** Terraform uses Thesis → Blueprint → Resources → Review and explains Prepare a venture. Explicit version inheritance; creation, activation and spending remain separate.

**Evidence:** new, forked and cancelled creation scenarios.

## OME-029 Build the venture room

**P0 · Frontend and product · L · Dependencies: OME-018, OME-019, OME-020, OME-022, OME-025**

Unify thesis, evidence, experiments, products, operating activity and decisions around a venture. Use persistent summary/contextual inspector rather than disconnected departmental dashboards.

**Acceptance:** recommendations link to evidence and thesis version; changes retain history; thesis edits flag affected experiments; activity does not obscure unresolved work; drafts survive reload/conflict; long research has a readable light treatment.

**Screens:** S03, S05, S07–S19, S25.

**UI acceptance:** preserve each object's scope and use real list/detail navigation and version-aware handoffs, not disconnected screen-selector demonstrations.

**Evidence:** an end-to-end pilot with partial data and recovery.

## OME-030 Build the approval inbox and mobile decision detail

**P0 before external actions · Frontend · M · Dependencies: OME-019, OME-025**

Provide a cross-venture queue ordered by urgency, expiry and impact, with full decision detail usable on a phone.

**Acceptance:** appropriate owned/delegated filters; no hover-only decisive facts; refreshed payloads require renewed review; incompatible/high-impact bulk approval disabled; race outcomes show actual approver and receipt.

**Screens:** S03 → S17 → S25.

**UI acceptance:** exact destination, changes, expiry and authority; approve/reject/request revision/changed payload/raced decision/unknown dispatch states. Mobile retains decisive facts above the action.

**Evidence:** keyboard/mobile and stale-request concurrency tests.

## OME-031 Add contextual search and command composition

**P1 · Frontend and search · M · Dependencies: OME-025, OME-039**

Search ventures, artifacts, evidence and runs; compose commands against visible resource scope.

**Acceptance:** server-side permissions; shortcuts do not capture typing fields; natural-language commands become inspectable proposals; ambiguous/destructive intent never executes silently; highlights cannot render unsafe markup; command history redacts secrets.

**Screens:** S03, S04, S08, S26, S28.

**UI acceptance:** expose resolved command proposal and distinguish empty/stale results. Chat is a command surface, not the source of truth.

**Evidence:** permission fixtures and ambiguous-command tests.

## OME-032 Validate complete journeys and responsive behaviour

**P0 for pilot release · Design research and quality · M · Dependencies: OME-026, OME-029, OME-030**

Test triage, evidence review, venture creation, interrupted save and approval with representative users/input methods.

**Acceptance:** define success before sessions; record completion/errors/interventions; test 390px, desktop, text zoom, reduced motion and keyboard; no blocker waived because a static concept looks correct; document limitations.

**Screens:** all atlas routes.

**UI acceptance:** include short-height and 200% zoom; capture complete paths, failure and recovery before acceptance.

**Evidence:** task scripts, observation notes and resolved-defect references. Proposed benchmarks are not measured results.

### Journey test packages

| Journey | Route and proof |
|---|---|
| J01 and existing-business import | S01 → S02 → S03 → S07: mapping review, duplicate prevention, correct scope after reload. |
| J02 and discovery | S01/S04 → S05 → S06: sources, inconclusive outcome, saved draft without activation. |
| J03/J04 content review | S08 → S09 → S12 → S11 → S15: exact artwork/Copy versions, changes requested, retained drafts. |
| J05/J08 release | S14 → S15 → S16 → S17 → S21: metadata, customer package, publication receipt and payment entitlement remain distinct. |
| J06 learning | S18 → S19 → S05 → S07: definitions, missing metrics, immutable outcome and next decision. |
| J07 intervention | Origin → S27 → origin: retained draft, reconciliation before retry, no duplicate external action. |
| Supervision/spawning | S03 → S17/S25/S19; S03 → S28 → S06 → S23: exact receipt and independent child scope. |
| Customer branches | S13 → S14 → S21; S30 → S21; S31 → S14 → S21; S32 → S21: distinct brands, personalisation, deliverable explanation and deferred gates. |

The local-session HTML prototype does not prove these packages have passed.
