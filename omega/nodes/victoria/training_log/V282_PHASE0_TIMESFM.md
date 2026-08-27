# V282 Phase 0 — TimesFM: capability, lookahead, and feasibility audit

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 / FINDINGS — no version pre-registered, no code changed, nothing installed
**Prompted by:** operator request to hook in `google-research/timesfm`
**Standing baseline:** crisis +$599 / trend +$2,997 / recent +$30 — untouched

---

## §0 — Why this is an audit and not an integration

TimesFM is a **time-series foundation model**. Victoria has already onboarded one of
those, across three versions:

| Version | Role | Verdict |
|---|---|---|
| **V263** | Kronos zero-shot, direction/entry | **STOP** — refutation pattern **R1 (no effect)**, ρ = **−0.027** |
| **V264** | Kronos fine-tuned on the V262 1h corpus | **STOP** — **R2 (below resolution)**; leakage assertions PASS |
| **V265** | Kronos **distributional** (realized-volatility forecast) | **CAVEATED — 2 of 3 gates.** V265-2 not queued |

The entry-signal role is refuted twice over, and **V280 independently showed that adding
signals to this composite costs $1k–$3.2k per window**. The only lane with a
non-refuted precedent is the *distributional* one — and that is precisely where
TimesFM's differentiator sits (§1). So the question is not "how do we hook it in" but
"is the one surviving lane viable, and can it be made causal."

## §1 — Capability (from the upstream project)

| | |
|---|---|
| Current version | **TimesFM 2.5**, **200M** params (down from 500M in 2.0) |
| Context | up to **16k** points |
| Frequency indicator | **no longer required** |
| Distributional output | **yes** — "continuous quantile forecast up to 1k horizon via an optional 30M quantile head"; output is mean plus the 10th–90th quantiles |
| Backends | PyTorch **or** Flax/JAX (optional deps) |

**The quantile head is the relevant capability.** A 10th–90th quantile band is a
forecast *distribution*, which maps directly onto V265's volatility lane (sizing /
risk), not onto the entry composite V263 refuted and V280 showed to be dilution-prone.

## §2 — The lookahead question, and why it is *narrower* than for an LLM

The V273 H1/H2 defect class is "a full-span or future statistic reaching an entry-time
decision." For foundation models there are two distinct channels, and they are not
equally dangerous:

| Channel | Applies to | Status for TimesFM |
|---|---|---|
| **Date-conditioning** — the model is told *when* it is and recalls what happened | LLMs (severe: an LLM knows how 2022 ended) | **Does not apply.** TimesFM consumes a context window of values, with no timestamp input and (in 2.5) not even a frequency tag. It cannot know which year it is looking at. |
| **Corpus memorisation** — the pretraining set contained *this series over this period* | any pretrained model | **Unresolved — see below.** |

This is a materially better position than the LLM path (V281 §7 item 2), where the model
demonstrably knows the outcome. For TimesFM the only live channel is memorisation.

**And that channel cannot currently be closed by inspection.** The upstream repository
**documents neither the pretraining corpus nor a data cutoff.** The v1 ICML paper
describes a largely non-financial mix (Google Trends, Wikipedia pageviews, synthetic
series, M4/electricity/traffic/weather), which would make crypto OHLCV memorisation
unlikely — but 2.5 is a different model with an undocumented corpus, and "unlikely on the
basis of a previous version's paper" is not a leakage assertion.

> **The honest statement: TimesFM's causal cleanliness on 2020–2026 crypto windows is
> not verifiable from published sources.** That is a finding about auditability, not a
> proof of contamination.

V264 shows the campaign can assert leakage-freedom for *fine-tuning* (temporal split,
assertions PASS). It has no method for asserting it about a **pretraining** corpus it
cannot see — and that gap is the real blocker on this lane.

## §3 — Practical feasibility on this host (measured)

| Requirement | Status here |
|---|---|
| `torch` | **ABSENT** |
| `jax` | **ABSENT** |
| `numpy` | present, 2.5.2 |
| Python | 3.14.7 (Homebrew, PEP-668 externally-managed — V276 §… `--user` and plain installs both refused) |
| Model weights | ~200M params, not present |

**Network on this host has failed every large install attempted today:** `pip install`
of five optional deps timed out at 10 minutes; the `postgres:16-alpine` pull stalled at
8 minutes and needed a kill-and-retry; `git push` timed out at 5 minutes and had to be
backgrounded. A `torch` install plus weights is substantially larger than any of those.

**TimesFM cannot be installed on this machine right now**, independently of whether it
is a good idea.

## §4 — The cheap test that should come first, and needs no model at all

Before spending anything on TimesFM, answer the question that governs the whole lane:

> **Does a better volatility forecast change Victoria's PnL at all?**

Run an **oracle-bound probe**: replace the volatility input with the *realised* forward
volatility — a perfect forecast, unattainable by any model — and measure the walk-forward
Δ. This is the V234-standing-rule shape (*"no grid until an env-gated probe shows the
gate variable actually discriminates"*), and it is decisive in one direction:

- **If the oracle moves PnL by less than the MDE**, then *no* volatility forecaster can
  help — TimesFM, Kronos, or anything else — and the lane closes for **$0**, permanently,
  with a stronger result than V265's caveated 2/3.
- **If the oracle moves PnL materially**, the lane is real, and the remaining question is
  how much of that headroom a forecaster can capture. Only then is installing TimesFM
  worth the cost.

It requires no new dependency, no download, no network, and it is not gated on the
unresolved §2 auditability question — an oracle is deliberately non-causal, and its
purpose is to bound the achievable, not to trade.

## §5 — Recommendation

**Do not integrate TimesFM yet.** Three things stand in front of it, in this order:

1. **Run the §4 oracle probe.** Cheap, local, decisive, and it may close the lane
   outright — which would make every downstream question moot.
2. **Resolve §2's auditability.** If the oracle probe says the lane is real, TimesFM's
   corpus/cutoff must be established (paper, model card, or an empirical memorisation
   probe on held-out crypto series) *before* any number it produces is trusted. A model
   whose training window cannot be bounded cannot produce a causal backtest number, and
   the campaign's entire measurement discipline rests on that.
3. **Fix the host.** `torch` + weights are not installable here today.

**Do NOT put TimesFM into the entry composite.** That is V263's refuted role (ρ = −0.027)
and V280's measured dilution, together.

**Note the asymmetry with the LLM lane.** TimesFM is *structurally* better placed than an
LLM for causal use — no date-conditioning channel — but *worse* documented, so the leak
it might have cannot currently be ruled out. The LLM has a known, severe channel; TimesFM
has an unknown, probably-small one.
