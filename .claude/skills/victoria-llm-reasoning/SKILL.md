---
name: victoria-llm-reasoning
description: Use when working with LLM reasoning inside Victoria — the reasoning layer, local/thinking models (Qwen3, Gemma via ollama), the hermetic LLM cache, cache-fill runs, or any new "let the model reason about the basket / regime / exits" idea. Covers the provider setup, the determinism contract that makes an LLM safe in a backtest, the cache-fill procedure, and the two reasoning hypotheses that are ALREADY REFUTED — read this before proposing a third.
---

# Victoria LLM reasoning

An LLM sits in a backtest only if the backtest stays a pure function of committed
bytes. Victoria solves this with a **hermetic cache**: prompts are hashed, responses are
committed, and a frozen replay that misses the cache **raises** rather than calling
anything. Everything below follows from that.

## Read this first: two hypotheses are already dead

Before proposing any reasoning work, know what has been measured:

| Version | Hypothesis | Outcome |
|---|---|---|
| **V240 Track D** | build the layer (per-cycle basket review) | shipped, flag-gated OFF |
| **V241** | whole-basket review improves the grid | **REFUTED** on all 32 windows — *"ACTIVE but adds variance, not expectancy."* recent mean-Δ **+$226.56** vs a >+$400 bar; recent p25-Δ **−$705.44** vs >+$500 |
| **V258** | specialist ensemble rehabilitates V241 | **REFUTED at Phase 0**, $0 grid spend |
| **V260** | LLM as news→regime classifier | **REFUTED** — degenerate classifier, 94% one class, MI 0.11 bits vs a 1.58-bit target |

`reasoning_layer_enabled` is `False` in `features.py` and should stay there absent a
**new** hypothesis with a **new** falsifier. "Same idea, better/cheaper model" is not a
new hypothesis — V258 already tried that shape and died at Phase 0.

Genuinely untried directions (as of V281): reasoning applied to **exits** rather than
entries; reasoning as a **veto-only** overlay on an existing gate; reasoning over
**regime labelling** with a causally-computable target (note V260 refuted the news
variant specifically, not the idea).

## The determinism contract — the part you must not break

`omega/nodes/victoria/reasoning_layer.py`:

- Cache path: `data/frozen_llm_cache/{model_id}/{prompt_hash}.json`,
  `prompt_hash = sha256(canonical_prompt_json)[:16]`.
- Under `OMEGA_FROZEN_CACHE=1`, a cache miss raises **`LLMCacheMiss`** — never a live
  call, never a neutral stub. A neutral-stub fallback would silently turn a cache gap
  into a "the model had no opinion" signal, which is why it is an exception.
- `OMEGA_LLM_CACHE_FILL=1` overrides frozen mode **for the LLM path only**, so a fill
  runs under the *identical* market/macro conditions the grid will replay. The prompt
  embeds in-run computed values, so **fill-time and replay-time prompts must hash-match**
  or every entry misses.
- Providers are **subprocess** calls (`agy`, or `curl` → ollama), because the V215 fence
  intercepts in-process HTTP. This is by design, not a bypass: a frozen replay never
  reaches a live call at all.

**The layer's authority is bounded and must stay bounded** (V241 contract): it may
`keep`, `drop`, or `size_scale` within **[0, 1]** — trim or scale down only. It can never
invent a position or up-size one. `tests/test_reasoning_provider.py` pins this
per-provider; if you add a provider, that test must still pass.

**Thinking traces are audit-only.** `BasketReview.thinking` is captured and cached, but
only `keep`/`drop`/`size_scale` can move a position. Never route a trace into a decision.

## Providers

Registry: `_PROVIDERS` in `reasoning_layer.py`, keyed by `model_id` (which is also the
cache directory, so providers never shadow each other).

| kind | transport | trace | notes |
|---|---|---|---|
| `agy` | `agy --model <string> -p <prompt>` | none | V240's original path; no temperature control |
| `ollama` | `curl` → `http://localhost:11434/api/generate` | **yes** — a `thinking` field separate from `response` | `temperature=0`, fixed seed |

Local models present on this machine: `qwen3.8:27b-mlx`, `qwen3:14b`, `gemma3:27b`,
`ornith-1.5:35b`. Check with `ollama list`; the server must be running.

Adding a model is one registry entry:

```python
"qwen3-14b": {"kind": "ollama", "model": "qwen3:14b"},
```

Local inference makes cache-fill effectively free, which is the point: V258's Phase 0
was explicitly scoped *"$0-grid, agy-wall-clock only"*. That constraint is gone.

## Procedure for a reasoning experiment

1. **Check the table above.** If your idea is V241's or V258's shape, stop.
2. **Pre-register** (`victoria-training-loop` skill): hypothesis, falsifier, gates,
   committed *before* any fill. The bar is the walk-forward **distribution**, never a
   single window (V235).
3. **Fill the cache** under the exact grid conditions:
   ```bash
   OMEGA_FROZEN_CACHE=1 OMEGA_LLM_CACHE_FILL=1 \
   OMEGA_AUDIT_OUTPUT_DIR=data/v###_fill \
     bash scripts/v274_smoke.sh
   ```
   Verify entries landed in `data/frozen_llm_cache/{model_id}/` and that `MANIFEST.json`
   records the provider and model.
4. **Replay frozen** (fill flag OFF). Any `LLMCacheMiss` means a prompt hash moved
   between fill and replay — the prompt embeds computed values, so a changed signal
   changes the key. Fix the mismatch; never "fix" it by relaxing the miss into a stub.
5. **Gate it** with N=2 determinism, and compare arms on *this host* — the standing
   baseline does not reproduce off-host (V276 §6 R5).
6. **Report the refutation if it refutes.** Three of the four rows above are
   refutations, and each was cheap because it was pre-registered.

## Traps

- **Prompt drift breaks the cache silently at fill time, loudly at replay.** Any change
  to the prompt builder invalidates every committed entry. Re-fill deliberately, and
  never mix entries from two prompt versions in one directory.
- **A model's world knowledge is lookahead.** A model trained past the replayed bar
  "knows" what happened. This is the V273 H1/H2 defect class in its purest form and it
  is *not* fixed by the hermetic cache — the cache makes the answer reproducible, not
  causal. Any prompt containing dates, or asset names a model has memorised outcomes
  for, needs this stated explicitly in the pre-registration.
- **Don't trust a fluent trace.** V260's LLM classifier produced confident, readable
  output and was a degenerate classifier — 94% one class. Score the output
  distributionally before believing it.
- **Latency is a design input.** `qwen3.8:27b-mlx` runs ~30 s per basket review. A
  32-window grid at 60 cycles is ~2k calls; fill in the background and never poll
  (see the training-loop skill).
