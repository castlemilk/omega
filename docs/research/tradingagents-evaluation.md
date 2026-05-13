# TradingAgents — architecture evaluation

Source: https://github.com/TauricResearch/TradingAgents (cloned 2026-05-13).

## Architecture (4-stage LangGraph DAG)

1. **Analyst layer** (parallel): four LLM-driven nodes — `market_analyst`,
   `sentiment_analyst`, `news_analyst`, `fundamentals_analyst`. Each pulls
   external data via tool calls and produces a written report.
2. **Researcher layer** (debate loop): `bull_researcher` and
   `bear_researcher` alternate. Each reads all four analyst reports plus
   the opponent's last turn, writes a rebuttal. A `research_manager`
   (deeper LLM) decides when to terminate the loop.
3. **Trader**: reads the debate transcript and the research manager's
   verdict; emits a structured `investment_plan`.
4. **Risk layer** (debate loop): three more LLM nodes — `aggressive`,
   `neutral`, `conservative` — debate the trader's plan. Loops until a
   `portfolio_manager` (deeper LLM) issues the final decision.

LangGraph stitches the whole thing with `add_conditional_edges` controlling
the debate-loop transitions.

## Comparison vs Victoria ensemble

| Aspect | TradingAgents | Victoria |
|---|---|---|
| Decision domain | Single ticker (stocks) | Multi-asset crypto basket |
| Signal type | LLM qualitative arguments | Quantitative numerical scores |
| Aggregation | Multi-round debates (LLM) | Single-pass vote + size_mult |
| Cost per decision | $0.10-1.00 LLM tokens | Free |
| Latency per decision | Seconds to minutes | Sub-second |
| Risk handling | LLM debate (qualitative) | Exit controller + ATR stop + regime gates |
| Memory use | Reflection module re-uses past trade outcomes in prompts | `semantic_memory` exists but does not feed entry decisions |
| Cadence fit | Daily/weekly | 15-min |

## Ideas worth porting

### Idea 1 — LLM tie-breaker for split ensemble decisions

When the three Victoria sub-strategies are split (1 long, 1 short, 1
abstain → `aggregate` returns "abstain"), we currently sit out. A short
LLM call (the existing `llm_analyst` wired to DeepSeek-Chat) could
arbitrate using the same numerical signal_dict + recent semantic_memory
hits, with a tightly scoped prompt asking "given these splits, is there
a tradable thesis on either side?" Cost-bounded by gating on
`size_mult == 0.0` only.

Wire point: `ensemble_strategy.py:aggregate` returns `EnsembleDecision`;
add an override path when `direction == "abstain"` AND a feature flag
`llm_tiebreaker` is on.

### Idea 2 — Post-decision risk debate (size scaling, not direction)

After the ensemble emits `(direction, size_mult)`, only on high-conviction
trades (`size_mult >= 0.5`), run a single LLM call asking: "given the
trade plan and recent loser MAE/MFE patterns, should size scale 0.5x,
1.0x, or 1.5x?" This is the TradingAgents risk-layer compressed from 3
agents and a debate loop into one call. Cost = 1 LLM call per high-conv
trade only, so ~$0.50/day at current trade rates.

Wire point: `paper_trading.py` proposal construction, after V184 lock50
trail logic.

### Idea 3 — Reflection / postmortem feedback into entry decisions

TradingAgents' `reflection.py` re-injects past trade outcomes into the
next-cycle prompt. Victoria has `semantic_memory` storing trade patterns
but only uses it for postmortem signal filtering (`postmortem_signal_filter`)
on individual signals, not for aggregate decisions. The pattern worth
porting: when the ensemble considers a new trade, look up the K most
similar past trades by signal vector + regime; if their realized PnL was
negative, apply a size penalty. This is closer to TradingAgents' "learn
from past mistakes" use of memory than the existing single-signal
filtering.

Wire point: `strategy.py` after `aggregate()`, before returning
`size_mult`.

## Ideas not worth porting

* **Multi-analyst-LLM pipeline.** TradingAgents calls 4 analyst LLMs in
  parallel, each with multi-turn tool use, before the debate even
  starts. At Victoria's 15-min cadence with five symbols, this would be
  20+ LLM calls per cycle. Our quantitative signals already cover the
  market/news/fundamentals/sentiment surface.
* **LangGraph framework adoption.** Victoria's orchestrator already wires
  a node graph. Adding LangGraph would re-implement what we have without
  semantic benefit.
* **Full bull/bear debate loop.** Multi-round LLM rebuttals are the
  costliest pattern. The tie-breaker (idea 1) captures most of the value
  with one call.

## Next steps if we want to test Idea 1

1. Add feature flag `llm_tiebreaker` + `llm_tiebreaker_provider`.
2. Pre-bake a tight prompt that takes: `signal_dict`, `sub_votes` (the
   three SubVote objects from `ensemble_strategy.decide`), recent regime,
   last 3 closed-trade outcomes. Asks for `{direction: long|short|abstain,
   conviction: 0.0..1.0, reason: <60 chars>}`.
3. Cost-cap: skip when `signals_dict` has fewer than N non-zero entries
   (poor data → abstain anyway).
4. A/B vs vanilla ensemble on snapshot first, then a parallel live run.
