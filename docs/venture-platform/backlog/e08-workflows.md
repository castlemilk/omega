# E08 Durable workflows

Source: https://chatgpt.com/space/page_56882e66e5448191bf8cbf2c8080df2c

All tickets are Proposed. A language-model loop is not the authoritative state machine. Runtime selection is measured; no paid service is provisioned by this backlog. Local prototype simulation does not establish durability.

## OME-057 Select the durable execution architecture

**P0 before durable runs · Architecture and reliability · M · Dependencies: OME-037, OME-038**

Compare current-Workers-compatible execution with a separate durable service; test long waits, resume, deployments, cost and operations.

**Acceptance:** survive interruption/approval wait; document failure semantics/limits; portable domain; versioned workflows/idempotent activities; no hidden rewrite or purchase.

**Screens:** S24, S25, S27.

**UI acceptance:** prove restart and human wait before presenting resumable execution.

**Evidence:** architecture decision and fault injection.

## OME-058 Implement workflow definitions and run state

**P0 · Workflow backend · L · Dependencies: OME-036, OME-050, OME-057**

Separate editable definitions, immutable versions, runs, node attempts and artifacts; bounded loops, typed inputs and terminal states.

**Acceptance:** pin active work; reject invalid graphs/unbounded recursion; restart checkpoints; transition preconditions; distinguish success/failure/cancel/unknown; agents return structured outputs rather than mutate state directly.

**Screens:** S24 → S25.

**UI acceptance:** canvas/list share exact definition; schema mismatch errors; edits create successors rather than change running work.

**Evidence:** state-machine/restart tests.

## OME-059 Make external effects idempotent and reconcilable

**P0 before external writes · Backend and integrations · L · Dependencies: OME-038, OME-052, OME-054, OME-058**

Stable operation identities and provider keys where supported; otherwise read-after-write reconciliation or manual resolution.

**Acceptance:** no blind retry on timeout; correlate persisted intent/receipt; retain payload identity; reject conflicting key reuse; expose unknown outcomes; concurrent workers cannot double-dispatch; no unsupported exactly-once claims.

**Screens:** S25 → S27.

**UI acceptance:** show intent, payload, receipt and reconciliation; unknown offers Check status/Reconcile rather than blind Retry.

**Evidence:** timeout-after-commit and duplicate-delivery tests.

## OME-060 Resume human approval workflows

**P0 · Workflow backend · M · Dependencies: OME-052, OME-058**

Support wait, approval, rejection, revision, expiry and delegation without holding a live process.

**Acceptance:** resume same run after revalidation; revision creates new digest; expired grants cannot execute; duplicate signals harmless; explicit rejection branch/stop; configurable reminders do not reveal private payloads.

**Screens:** S25 → S17 → S25.

**UI acceptance:** current-state revalidation, explicit revision/rejection branches and no silent expired/duplicate dispatch.

**Evidence:** simulated multi-day waits, redeploy recovery and reviewer races.

## OME-061 Implement cancellation and compensating actions

**P0 before external workflows · Workflow backend · M · Dependencies: OME-055, OME-059, OME-060**

Define stoppable/retryable/compensatable/manual steps; distinguish completed external effects from unfinished work.

**Acceptance:** cancel prevents new dispatch; races retain receipts; compensation needs authority/idempotency; identify irreversible effects; resume skips completed steps; incomplete compensation remains incident.

**Screens:** S25, S27.

**UI acceptance:** distinct stop-dispatch/cancel/compensate/manual follow-up; no fictional Undo.

**Evidence:** cancellation at every boundary and recovery procedures.

## OME-062 Add scheduling quotas and concurrency leases

**P1 · Reliability · M · Dependencies: OME-053, OME-058, OME-059**

Bounded recurring operating loops with tenant limits, fairness, backoff and concurrency policy.

**Acceptance:** skip/queue/replace overlap rules; stale fencing tokens cannot commit; pause checked; timezone/DST tests; retry preserves budget; rate limits queue instead of request storms.

**Screens:** S24 schedule settings, S25 queue.

**UI acceptance:** timezone/recurrence/overlap/quota/concurrency visible; queued/rate-limited differs from running.

**Evidence:** load, lease expiry and clock-transition tests.

## OME-063 Validate outputs independently of generation

**P0 for accepted automated outputs · Agent evaluation · M · Dependencies: OME-049, OME-058**

Validate schemas, citations, asset properties and task quality with deterministic checks and independent review as needed.

**Acceptance:** self-approval insufficient; quarantine malformed/unsupported output; attach evaluator version/result; science and print checks separate; repairs bounded and budgeted; failed evaluator cannot mark ready.

**Screens:** S11, S14, S25.

**UI acceptance:** link exact artifact to evaluator/version/result; separate editorial, factual, rights and output checks.

**Evidence:** deliberately broken outputs and known-good baselines.

## OME-064 Instrument runs and explain recovery

**P0 for pilot execution · Observability and frontend · M · Dependencies: OME-020, OME-038, OME-058, OME-059**

Correlate steps, model calls, policy decisions, receipts, cost and artifacts in an operator timeline.

**Acceptance:** derive state from persisted events; distinguish event/ingestion time; redact secrets; reconnect via cursor without duplicates; expose stale telemetry; identify exact failed boundary/safe next action.

**Screens:** S25, S27.

**UI acceptance:** actual timing, artifacts, costs and blockers; stable selection/reconnection and labelled historical replays.

**Evidence:** end-to-end trace and restart/reconnection tests.

### Reference workflow

Research brief → Prepare recipe → Review artwork → Package files → Human approval → Publish. Changes requested returns to preparation. Publication is gated external action, not a simulation effect. Validate authoring, approval wait, interrupted dispatch and recovery separately.
