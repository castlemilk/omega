---
name: omega-research
description: Structured research pipeline for Omega — takes an idea or hypothesis, searches for evidence, compares to existing Omega capabilities, and delivers a verdict with implementation recommendations. Use when asked to /research a topic, evaluate a new signal source, assess an external tool/library, or investigate trading strategies.
tags:
  - research
  - omega
  - victoria
  - strategy
  - analysis
---

# Omega Research Skill

Run structured research on any idea, signal, tool, or strategy and produce an actionable verdict with Omega integration notes.

## Trigger phrases
- `/research <topic>`
- "research X"
- "look into X for Omega"
- "evaluate X for Victoria"
- "should we add X to the pipeline?"

---

## The Pipeline

```
IDEA → DECOMPOSE → SEARCH → COMPARE-TO-OMEGA → VERDICT → LOG
```

---

## Phase 1: Decompose

Break the research topic into 3–5 sub-questions:
1. What is it and how does it work?
2. What is the claimed edge / advantage?
3. What does the literature / community say about real-world performance?
4. Is there existing Omega/Victoria overlap or conflict?
5. What would implementation cost (time, API cost, infra)?

---

## Phase 2: Search

Use WebSearch on each sub-question. Prefer:
- arXiv, SSRN for academic signals
- GitHub for implementations
- Twitter/X via SN13 feed for practitioner alpha
- Polymarket blog / forecast community for prediction market angles

Collect 3–5 authoritative sources per sub-question.

---

## Phase 3: Compare to Omega

Check the following files for overlap:
- `omega-strategic-backlog.md` — is this already tracked?
- `omega/nodes/` — is there an existing node that covers this?
- `docs/DATA_SOURCES.md` — is the data source already integrated?
- `docs/specs/` — any relevant spec?

Explicitly state: **NEW**, **OVERLAP** (with item ID), or **SUPERSEDES** (item ID).

---

## Phase 4: Verdict

Produce a structured verdict block:

```
## Research Verdict: <topic>
Date: YYYY-MM-DD

### TL;DR
One sentence conclusion.

### Evidence Quality
[HIGH / MEDIUM / LOW] — explain why

### Omega Overlap
[NEW / OVERLAP: <ID> / SUPERSEDES: <ID>]

### Recommended Action
- [ ] Add to backlog as <ID>: <description>
- [ ] Implement immediately (reason)
- [ ] Discard (reason)
- [ ] Monitor (next review date)

### Implementation Notes
- Relevant node: <NodeName>
- Data source: <API/SDK>
- Estimated cost: <$/mo>
- Estimated effort: <S/M/L>

### Sources
1. <url> — <one-line summary>
2. ...
```

---

## Phase 5: Log

Append the verdict to `docs/ideas/feed.jsonl` in this format:

```json
{"timestamp": "ISO8601", "type": "research_verdict", "topic": "...", "action": "add_backlog|implement|discard|monitor", "backlog_id": "...", "summary": "...", "sources": [...]}
```

If high-priority (implement immediately), also print a `[PRIORITY]` banner.

---

## Rules

- Always complete all 5 phases before responding
- Never skip Phase 3 — Omega overlap check prevents duplicate work
- Cost estimates are required for any external API
- Log entry is mandatory — this feeds the scheduled research task
