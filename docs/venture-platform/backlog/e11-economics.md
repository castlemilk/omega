# E11 Economics and portfolio learning

Source: https://chatgpt.com/space/page_1e7fb1c82a848191937ec372abaed190

All tickets are Proposed. Financial reporting, execution limits and platform billing are separate. Proposed prices, forecasts and concept-dashboard values are not observed business results.

## OME-081 Establish metric definitions and data-quality contracts

**P0 before economic reporting · Analytics and product · M · Dependencies: OME-034, OME-038**

Define revenue, refunds, direct costs, contribution margin, effort, experiment outcomes and execution costs with units, periods, source precedence and calculation versions.

**Acceptance:** missing is not zero; cash differs from earned revenue; gross differs from contribution margin; explicit inclusions/exclusions; definition changes version comparisons; freshness/reconciliation queryable.

**Screens:** S03, S18, S19.

**UI acceptance:** definition/period/currency/freshness/source/coverage per value; No live data imported and Partial report differ from zero; retain rate numerator/denominator.

**Evidence:** semantic catalogue and independent calculations.

## OME-082 Implement the venture financial ledger

**P0 before financial balances · Finance engineering · L · Dependencies: OME-037, OME-038, OME-081**

Explicit currencies, integer minor units/exact decimals, balanced journals, dated FX and linked receipts; synthetic fixtures before provider ingestion.

**Acceptance:** reversals not destructive corrections; no duplicate posting; reconcile by currency; liabilities versus cash; refund lineage; independent balance checks; provider mapping additionally requires OME-075.

**Screens:** S19.

**UI acceptance:** exact source/reversal links; separate cash/liability/settlement/refund/dispute and reconcile totals.

**Evidence:** property tests/reconciliation fixtures. Not tax filing or complete statutory accounting.

## OME-083 Attribute execution and production costs

**P0 before profitability claims · Analytics and agent platform · M · Dependencies: OME-053, OME-064, OME-081, OME-082**

Attribute model/media/browser/compute/channel/production costs to run, experiment, product and venture using explicit allocation rules.

**Acceptance:** separate estimates/reservations/incurred/settled; retries retain attribution; shared expenses allocate once; unknown charges provisional; dated rate changes; corrections preserve receipts.

**Screens:** S19, S25.

**UI acceptance:** each cost links to run/artifact and status; provisional/shared costs remain inspectable.

**Evidence:** reconciled waterfall and concurrent-run fixtures.

## OME-084 Build portfolio economics and scenario views

**P1 · Analytics and frontend · M · Dependencies: OME-021, OME-081, OME-082, OME-083**

Comparable venture economics, contribution, capital commitments and scenario assumptions with defined periods/freshness.

**Acceptance:** no membership/transfer double-counting; explicit FX basis; actuals and forecasts semantically/visually separate; partial connector labels; inspect shared allocations; include paused/closed ventures where relevant.

**Screens:** S03, S19.

**UI acceptance:** separate labels/source sets for actuals/scenarios; preserve period filters; explain conversion/unallocated costs.

**Evidence:** aggregation fixtures and metric-to-source drill-through.

## OME-085 Produce capital allocation recommendations

**P2 · Portfolio intelligence · M · Dependencies: OME-046, OME-047, OME-084**

Compare validation, product investment, distribution, holding funds and stopping against evidence/uncertainty/obligations.

**Acceptance:** assumptions/sensitivity exposed; sunk costs alone cannot justify more spend; incomplete outcomes labelled; budget changes require separate authority; no recommendation-triggered bank transfer/limit increase; later outcomes compare with original decision.

**Screens:** S19 → S17.

**UI acceptance:** evidence/counterevidence, assumptions/sensitivity and versioned proposal; recommendation never itself transfers money or increases ceiling.

**Evidence:** reviewed alternatives and counterevidence briefs.

## OME-086 Build permissioned playbooks and venture memory

**P2 · Knowledge systems and security · L · Dependencies: OME-036, OME-039, OME-047, OME-063**

Lessons/playbooks with origin, evidence, applicability, expiry and versions; venture-private versus explicitly shared organisation knowledge.

**Acceptance:** current permission checks; copied provenance; flag stale/contradictory lessons; retain failures; cross-organisation learning off by default pending separately reviewed consent/aggregation; no raw customers/credentials in shared memory.

**Screens:** S28 → S06/S24.

**UI acceptance:** objective/inputs/origin/applicability/evidence/sharing scope; copy/reference preview excludes credentials/customer data.

**Evidence:** isolation/revocation/poisoning/contradiction tests.

## OME-087 Define transparent platform billing and entitlements

**P2 · Product and billing engineering · L · Dependencies: OME-039, OME-081, OME-083**

Prototype tiers, active-venture limits, metered usage and cost explanations. Research pricing remains a hypothesis, not approved tariff.

**Acceptance:** quotas do not replace execution budgets; deduplicate usage; periods/adjustments explicit; cancel/downgrade retain access rules; venture sales differ from Omega subscription revenue; reconcile test invoices to usage.

**Screens:** S29 Usage.

**UI acceptance:** period, quota, usage, adjustments and proposed plan changes without fictional selected pricing.

**Evidence:** pricing experiment and test-mode billing lifecycle.

## OME-088 Measure outcomes trust and operator leverage

**P1 · Product analytics and research · M · Dependencies: OME-007, OME-032, OME-046, OME-064, OME-081**

Evaluate validated outcomes per operator hour plus intervention, approval, rollback, failure, cost and unauthorised-action rates.

**Acceptance:** defined denominators/windows; simulations excluded from live claims; measured effort; failed/stopped ventures retained in cohorts; incidents not diluted by low-risk volume; compare with OME-006 baseline.

**Screens:** S03, S18, S19.

**UI acceptance:** named cohort/denominator/window and baseline comparison; no concept-image numbers or affiliations as business performance.

**Evidence:** pilot report with limitations and next-autonomy recommendation.
