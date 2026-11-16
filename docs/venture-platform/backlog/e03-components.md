# E03 Operational components

Source: https://chatgpt.com/space/page_295096878d8481919e208c154750e59a

All tickets are Proposed. Each component needs loading, empty, partial, stale, error, permission-denied and narrow-layout states. Label fixtures. A rendered component does not establish that its backing operation exists. Reuse shared primitives instead of equivalent screen-local implementations.

## OME-017 Build the venture registry component

**P0 · Frontend and design · M · Dependencies: OME-010, OME-011, OME-014**

**Outcome and scope:** scannable table and compact summary of venture identity, lifecycle, operating health, attention needed and economic period.

**Acceptance:** separate lifecycle from execution state; missing revenue is not zero; show currency/time window; sort typed values; selection preserves the list; support long names, no ventures and unavailable connectors.

**Screens:** S03, S04, S07.

**UI acceptance:** visible scope and record type, stable selection, restorable filters, separate lifecycle/health/autonomy and explicit empty, partial, disconnected and unauthorised states.

**Evidence:** component stories, keyboard tests and narrow-screen review. No invented financial performance or card-only portfolio layout.

## OME-018 Build evidence inspection and provenance components

**P0 · Frontend and research UX · M · Dependencies: OME-010, OME-014**

**Outcome and scope:** inspect a claim, source snapshot, retrieval date, author, contradictions and its use in decisions.

**Acceptance:** explicitly label fact/inference/forecast; show freshness/missing evidence; citations open the supporting passage; do not hide contradictions behind a score; percentages require a defined calibrated method; untrusted source text cannot inject controls.

**Screens:** S04, S05, S09, S11, S14, S28.

**UI acceptance:** evidence inspector, provenance label and immutable version strip show supporting passages, times, limitations and contradictions. Missing files retain their identity; never substitute another asset.

**Evidence:** fixtures for expired/conflicting/unavailable evidence.

## OME-019 Build the decision gate and exact change review

**P0 · Frontend and governance · M · Dependencies: OME-010, OME-014**

**Outcome and scope:** proposed action with before/after values, destination, affected venture, cost ceiling, consequences and authority.

**Acceptance:** approve/reject/request revision are distinct; material changes invalidate approval; expired/superseded requests cannot be approved; focus enters/returns correctly; show durable receipt rather than optimistic success.

**Screens:** S11, S17, S19, S29.

**UI acceptance:** shared editorial/publication/allocation/access-change variants expose exact revisions and consequences. Approval, execution and confirmed receipt remain separate.

**Evidence:** publication, budget-adjustment and refund scenarios. Live backend authority is a separate dependency.

## OME-020 Build the observable agent run timeline

**P0 · Frontend and runtime UX · M · Dependencies: OME-010, OME-014**

**Outcome and scope:** objective, declared plan, observable steps, tool receipts, concise decision explanations, artifacts, cost and blocker.

**Acceptance:** distinguish queued/running/waiting/failed/cancelled/uncertain; label partial output; redact secrets/personal data; elapsed time derives from events; explanations summarise evidence and decisions, not hidden model reasoning.

**Screens:** S03, S23, S25.

**UI acceptance:** timeline and selected-step inspector derive from actual events and retain access to mandate/artifacts.

**Evidence:** deterministic event fixtures and interrupted-run replay. Animation is not execution evidence.

## OME-021 Build budget and cost components

**P0 before spending · Frontend and finance · M · Dependencies: OME-010, OME-011, OME-014**

**Outcome and scope:** show authorised, reserved, settled and remaining amounts without double counting.

**Acceptance:** commitments differ from cash paid; currency and conversion times are explicit; parent/child limits are not independent funds; label stale provider costs; support zero, negative adjustments and exhausted limits; provide textual equivalents.

**Screens:** S06, S19, S23, S25.

**UI acceptance:** cost/reservation strip and ledger rows show currency/period and unknown charge exposure; delegated limits are counted once.

**Evidence:** numerical fixtures reconciled to independently calculated balances. A decorative gauge is not a financial source of truth.

## OME-022 Build save receipts and recovery states

**P0 · Frontend and reliability · M · Dependencies: OME-010, OME-014, OME-006**

**Outcome and scope:** preserve autosave guarantees under the new visual system.

**Acceptance:** dirty/saving/saved/offline/conflict/outcome-unknown are distinct; never blindly retry uncertain writes; local edits remain exportable; reconcile revisions and changed fields; warn before losing unsaved work; retain IME and queued-edit semantics.

**Screens:** S02, S06, S09, S12, S15, S27.

**UI acceptance:** shared draft guard, exact receipt and reconciliation panel retain edits through IME, navigation, malformed acknowledgements and cross-tab conflicts. Reconcile before repeated mutation.

**Evidence:** failure injection and create/edit/reload recordings against local and hosted persistence separately.

## OME-023 Build workflow canvas and accessible step list

**P1 · Frontend and workflow design · L · Dependencies: OME-010, OME-014**

**Outcome and scope:** inspect branching work, approvals, artifacts and dependencies without requiring a canvas.

**Acceptance:** graph/list represent the same definition and run; keyboard can select/connect/reorder without dragging; run progress cannot overwrite draft definitions; invalid connections explain schema mismatches; narrow layouts default to list; zoom/selection remain stable.

**Screens:** S24, S25.

**UI acceptance:** one representation powers typed ports, human gates and safe retry boundaries. Zoom and selection do not mutate workflow definitions.

**Evidence:** shared fixtures, screen-reader walkthrough and canvas/list parity checks.

## OME-024 Standardise forms tables alerts and empty states

**P0 · Design systems and frontend · M · Dependencies: OME-015**

**Outcome and scope:** common fields, filters, pagination, bulk selection, notifications and recovery messages.

**Acceptance:** validation identifies field/remedy; filtered versus all-matching selection is explicit; bulk actions show scope; transient notifications are not the only error record; empty states distinguish no data/no results/no permission/not connected; destructive controls use explicit verbs.

**Screens:** all forms, inventories and settings.

**UI acceptance:** share table, field, select, dialog, notification and empty-state primitives; assign scroll ownership; maintain loading dimensions; provide inline errors and focus return. Distinguish original, derivative, preview, mockup, metadata packet and customer file rather than an ambiguous Download label.

**Evidence:** component state matrix and interaction tests; prefer existing compatible primitives.
