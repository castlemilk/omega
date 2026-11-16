# E07 Agent authority and control

Source: https://chatgpt.com/space/page_4ca7d77e167081919b88ef37e34819fa

All tickets are Proposed. Separate recommendation, permission and execution. These controls gate the corresponding capability; the backlog does not imply unattended execution is available. Source reference: https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

## OME-049 Create the versioned agent and capability registry

**P0 before agent execution · Agent platform · M · Dependencies: OME-036, OME-039**

Define task-oriented agents, model routing, structured inputs/outputs, tools and evaluation profiles.

**Acceptance:** immutable once used; explicit allowed tools; model changes require regression evaluation; descriptions do not grant authority; check capabilities before start; provider failures return bounded errors rather than escalating silently.

**Screens:** S23.

**UI acceptance:** Definition/Mandate/Tools/Evaluations tabs expose exact versions and availability. Role labels and sigils do not imply permission.

**Evidence:** registry contracts and versioned fixtures.

## OME-050 Implement bounded execution mandates

**P0 · Agent platform and security · M · Dependencies: OME-049, OME-039**

Bind each run to principal, tenant, venture, objective, resources, tools, time limit, model/tool cost envelope, external-action policy and authorising actor.

**Acceptance:** expired/revoked mandates fail closed; equal/narrower child scope; bounded delegation depth/task count; one reservation tree; recheck authority on resume; display effective scope.

**Screens:** S23 → S25.

**UI acceptance:** persistent mandate strip exposes principal, objective, scope, deadline, cost/delegation limits; resume checks current authority.

**Evidence:** delegation, expiry, revocation and escalation tests.

## OME-051 Implement deterministic policy evaluation

**P0 · Security and backend · L · Dependencies: OME-050**

Evaluate side effects outside the language model using permissions, resource state, risk, budget and policy version.

**Acceptance:** allow/deny/require approval with reasons; deny unknown actions; tool/model text cannot override rules; retain/version decisions; dry runs have no effects; direct adapters cannot bypass enforcement.

**Screens:** S17, S23, S26.

**UI acceptance:** reason codes/policy version accompany decisions; dry-run controls remain side-effect-free.

**Evidence:** policy matrix and service-boundary bypass tests.

## OME-052 Bind approvals to exact actions

**P0 · Security and backend · L · Dependencies: OME-051, OME-036**

Persist payload digest, resource revision, destination, cost limit, approver, expiry and single-use execution identity.

**Acceptance:** changed content/recipient/amount/target invalidates approval; recheck authority/revision at execution; resolve races once; replay cannot duplicate effects; expired requests cannot resume silently; failure/unknown preserves receipt and reconciliation.

**Screens:** S17 → S25.

**UI acceptance:** exact payload, recipient/destination, amount, digest and expiry precede approval; changed/expired/raced/uncertain states cannot show false success.

**Evidence:** stale-approval, changed-payload, double-click and replay tests. UI uses OME-019.

## OME-053 Enforce atomic hierarchical budget reservations

**P0 before billable execution · Backend and finance · L · Dependencies: OME-037, OME-050, OME-051**

Reserve estimated maximum before dispatch, settle actual cost and release unused funds, checking organisation/venture caps together.

**Acceptance:** concurrent runs cannot oversubscribe; subagents do not duplicate allowances; retries reuse reservation; unknown charges retain exposure; stale prices block or use approved conservative bounds; provider overruns create incidents, not rewritten history.

**Screens:** S19, S23, S25.

**UI acceptance:** authorised/reserved/settled/available funds and lineage; unknown charges stay exposed.

**Evidence:** concurrent-spend/crash-recovery tests; provider-side caps where hard local ceilings cannot be guaranteed.

## OME-054 Broker scoped tools and credentials

**P0 before external integration · Security and integrations · L · Dependencies: OME-039, OME-051**

Keep secrets outside prompts/artifacts; expose typed capabilities through brokered resource grants and restricted networking.

**Acceptance:** no secrets in traces; minimal OAuth; server validates tenant/destination; rotate/revoke without recreating ventures; block untrusted internal URLs; isolate generated code; treat tool output as data.

**Screens:** S26.

**UI acceptance:** inspect account, mode and effective grants without credentials; saving ventures/installing connectors does not grant scope.

**Evidence:** secret-canary, cross-tenant, SSRF and sandbox-boundary tests.

## OME-055 Implement pause quarantine and intervention

**P0 before unattended runs · Reliability and security · M · Dependencies: OME-050, OME-051, OME-053**

Organisation, venture and run pause, plus quarantine for suspicious actions.

**Acceptance:** future dispatch checks pause; pending approvals cannot bypass; list in-flight operations and best-known status; cancellation differs from reversal; permitted revalidated resume; preserve redacted incident evidence.

**Screens:** S03, S23, S25, S27.

**UI acceptance:** pause remains reachable at all scopes; expose last-confirmed in-flight states and distinguish stop-dispatch/cancel/compensate.

**Evidence:** pause-during-dispatch/recovery tests. Already accepted external actions are not always reversible.

## OME-056 Establish adversarial and autonomy promotion evaluations

**P0 before autonomy promotion · Security and quality · L · Dependencies: OME-052, OME-053, OME-054, OME-055**

Test injection, malicious documents, forged receipts, poisoned memory, stale approvals, budget exhaustion and cross-venture leakage.

**Acceptance:** predefined criteria/severity; regressions block promotion; explicit observe/draft/bounded eligibility; agents cannot alter their evaluations; reproducible redacted failures; revocable promotion.

**Screens:** S23 Evaluations.

**UI acceptance:** version-bound test results, failed criteria, eligibility and explicit promotion/revocation. Activity charts cannot establish eligibility.

**Evidence:** evaluation suite and reviewed promotion report, not agent self-assessment.
