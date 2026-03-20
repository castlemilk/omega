---
name: deep-research
description: IterDRAG iterative retrieval-augmented generation pattern — search, summarize, reflect loop for deep research tasks
tags:
  - research
  - search
  - rag
  - deep-research
  - analysis
---

# Deep Research — IterDRAG Pattern

When assigned a research task, follow this iterative loop until the answer is comprehensive and well-sourced.

## The Loop

```
QUERY → DECOMPOSE → SEARCH → SUMMARIZE → REFLECT → (gaps?) → SEARCH again → REPORT
```

Stop when: all sub-questions have authoritative answers, OR 3 iterations complete, OR new searches return no new information.

---

## Phase 1: Decompose the Query

Before searching, break the research question into 3–5 independently searchable sub-questions that together cover the full topic.

**Example** — "What are best practices for Connect-RPC in Go?":
1. What is Connect-RPC and how does it differ from standard gRPC?
2. What are the recommended project structure conventions?
3. How should error handling work in Connect-RPC handlers?
4. What are the performance best practices for streaming RPCs?
5. How does Connect-RPC handle backward compatibility?

---

## Phase 2: Search (per sub-question)

For each sub-question:
1. Formulate a precise search query (use technical terms, avoid ambiguity).
2. Execute search via available tool (web search, document retrieval, code search).
3. Collect 3–5 relevant sources. Prefer: official docs > source code > RFC/specs > engineering blogs > forum posts.
4. Note the URL/reference, title, and key claims from each source.

---

## Phase 3: Summarize

After searching all sub-questions:
1. Write a structured summary per sub-question.
2. Cite sources inline for every claim.
3. Flag contradictions between sources explicitly.
4. Mark what is authoritative (spec, official docs) vs. community opinion.

---

## Phase 4: Reflect on Gaps

Ask:
- What questions remain unanswered?
- What claims lack good sourcing?
- Are there edge cases or failure modes not covered?
- Is the information current? (check publication dates)

If gaps found → formulate new targeted queries and return to Phase 2.
If confident → proceed to Phase 5.

---

## Phase 5: Produce the Report

```markdown
# [Topic] — Research Report

## Summary
[2–3 sentences: key findings]

## Findings

### [Sub-question 1]
[Answer with inline citations]

### [Sub-question 2]
[Answer with inline citations]

## Key Recommendations
- [Actionable recommendation 1]
- [Actionable recommendation 2]

## Sources
- [URL or doc name] — [why relevant]

## Gaps and Caveats
- [What remains uncertain or needs verification]
```

---

## Configuration

| Mode | When to use |
|------|-------------|
| **Local (Ollama)** | Private data, offline, cost-sensitive. Models: llama3, mistral, deepseek-r1 |
| **Cloud** | High accuracy on complex topics. Models: claude-sonnet-4-6, gpt-4o |

Search providers (no key required): DuckDuckGo instant answers.
Search providers (API key): Brave Search API, Tavily API, SerpAPI.

---

## Quality Signals

**Good output:**
- Every claim has a source
- Contradictions are surfaced, not hidden
- Distinguishes spec/official vs. community practice
- Gaps section is honest

**Poor output:**
- Confident claims without sources
- No alternatives or tradeoffs discussed
- Single-source conclusions on contested topics
- Missing a gaps/caveats section
