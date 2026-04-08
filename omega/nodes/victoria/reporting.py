"""
omega.nodes.victoria.reporting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ReportingNode — generates human-readable market analysis reports.

Improvement arc:
  v1.0 — Basic market summary: top signals, portfolio weights
  v1.1 — Risk section added: VaR, CVaR, position limit violations
  v1.2 — Performance attribution: backtest Sharpe, drawdown, hit rate
  v1.3 — Market regime commentary: vol regime, correlation warnings
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.reporting")


class ReportingNode(Node):
    """
    Generates human-readable market analysis reports from pipeline outputs.

    Capabilities : generate_report, summarize_market, format_signals
    Improves via : basic summary → risk section → performance attribution → regime commentary
    """

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._include_risk = False
        self._include_attribution = False
        self._include_regime = False
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_report_length = 0
        self._last_report_sections = 0
        self._reports_generated = 0

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        completeness = self._completeness_score()
        return NodeState(
            node_id=self._node_id,
            name="ReportingNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "completeness_score": completeness,
                "reports_generated": float(self._reports_generated),
                "last_report_sections": float(self._last_report_sections),
            },
            metadata={
                "include_risk": self._include_risk,
                "include_attribution": self._include_attribution,
                "include_regime": self._include_regime,
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["generate_report", "summarize_market", "format_signals"]

    def describe(self) -> str:
        return (
            "Generates human-readable market analysis reports combining market data, "
            "trading signals, portfolio construction, and risk metrics. "
            "Self-improves by adding risk sections, performance attribution, "
            "and market regime commentary."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action
        params = input.parameters

        try:
            if action == "generate_report":
                result = self._generate_full_report(params)
            elif action == "summarize_market":
                result = self._summarize_market(params.get("market_data", {}))
            elif action == "format_signals":
                result = self._format_signals(params.get("signals", {}))
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed
            self._reports_generated += 1

            report_text = result.get("report", "") if isinstance(result, dict) else str(result)
            self._last_report_length = len(report_text)
            self._last_report_sections = (
                result.get("sections", 0) if isinstance(result, dict) else 1
            )

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={
                    "latency_ms": elapsed,
                    "completeness_score": self._completeness_score(),
                    "report_length_chars": float(self._last_report_length),
                    "sections": float(self._last_report_sections),
                },
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("ReportingNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "completeness_score": self._completeness_score(),
            "reports_generated": float(self._reports_generated),
            "last_report_sections": float(self._last_report_sections),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False
        iteration = feedback.get("iteration", 0)

        # v1.1: Add risk section
        if not self._include_risk and iteration >= 1:
            self._include_risk = True
            self._version = "1.1"
            logger.info("ReportingNode → v1.1: risk section added")
            changed = True

        # v1.2: Add performance attribution
        if self._include_risk and not self._include_attribution and iteration >= 2:
            self._include_attribution = True
            self._version = "1.2"
            logger.info("ReportingNode → v1.2: performance attribution section added")
            changed = True

        # v1.3: Add regime commentary
        if self._include_attribution and not self._include_regime and iteration >= 3:
            self._include_regime = True
            self._version = "1.3"
            logger.info("ReportingNode → v1.3: market regime commentary added")
            changed = True

        return changed

    # ------------------------------------------------------------------ report generation

    def _generate_full_report(self, params: dict[str, Any]) -> dict[str, Any]:
        market_data = params.get("market_data", {})
        signals = params.get("signals", {})
        portfolio = params.get("portfolio", {})
        risk = params.get("risk", {})
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines: list[str] = []
        sections = 0

        # ── Header ─────────────────────────────────────────────────────────────
        lines += [
            "=" * 68,
            "  VICTORIA MARKET ANALYSIS REPORT",
            f"  Generated: {timestamp}",
            "=" * 68,
            "",
        ]

        # ── Section 1: Market Overview ─────────────────────────────────────────
        sections += 1
        market_summary = self._summarize_market(market_data)
        lines += [
            "MARKET OVERVIEW",
            "-" * 40,
        ]
        lines.append(market_summary.get("text", "No market data available."))
        lines.append("")

        # ── Section 2: Top Signals ─────────────────────────────────────────────
        sections += 1
        signal_text = self._format_signals(signals)
        lines += [
            "TRADING SIGNALS",
            "-" * 40,
        ]
        lines.append(signal_text.get("text", "No signals generated."))
        lines.append("")

        # ── Section 3: Portfolio Construction ─────────────────────────────────
        sections += 1
        lines += [
            "PORTFOLIO CONSTRUCTION",
            "-" * 40,
        ]
        weights = portfolio.get("weights", {})
        method = portfolio.get("method", "equal")
        if weights:
            lines.append(f"  Method       : {method}")
            lines.append(f"  Positions    : {len(weights)}")
            lines.append("")
            lines.append(f"  {'Ticker':<12} {'Weight':>8}  {'Signal':>8}")
            lines.append(f"  {'-' * 12} {'-' * 8}  {'-' * 8}")
            for ticker in sorted(weights, key=lambda t: -weights[t]):
                w = weights[ticker]
                sig = signals.get(ticker, {}).get("composite", 0.0)
                lines.append(f"  {ticker:<12} {w:>7.1%}   {sig:>+7.3f}")
        else:
            lines.append("  No portfolio constructed.")
        lines.append("")

        # ── Section 4 (v1.1+): Risk Metrics ───────────────────────────────────
        if self._include_risk and risk:
            sections += 1
            lines += [
                "RISK METRICS",
                "-" * 40,
            ]
            var = risk.get("portfolio_var_95", risk.get("var_95", 0.0))
            cvar = risk.get("portfolio_cvar_95", risk.get("cvar_95", 0.0))
            passed = risk.get("passed", True)
            violations = risk.get("violations", [])

            lines.append(f"  VaR (95%, 1-day)  : {var:.2%}")
            if cvar:
                lines.append(f"  CVaR (95%, 1-day) : {cvar:.2%}")
            lines.append(f"  Risk Limits       : {'✓ PASSED' if passed else '✗ VIOLATED'}")
            if violations:
                for v in violations:
                    lines.append(f"    ⚠  {v}")
            lines.append("")

        # ── Section 5 (v1.2+): Performance Attribution ────────────────────────
        if self._include_attribution:
            sections += 1
            backtest = portfolio.get("backtest", {})
            lines += [
                "BACKTEST PERFORMANCE",
                "-" * 40,
            ]
            if backtest:
                sharpe = backtest.get("sharpe", 0.0)
                max_dd = backtest.get("max_drawdown", 0.0)
                hit_rate = backtest.get("hit_rate", 0.0)
                trades = backtest.get("trades", 0)
                mean_ret = backtest.get("mean_daily_return", 0.0)

                lines.append(f"  Sharpe Ratio     : {sharpe:+.3f}")
                lines.append(f"  Max Drawdown     : {max_dd:.2%}")
                lines.append(f"  Hit Rate         : {hit_rate:.1%}")
                lines.append(f"  Trades Analysed  : {trades}")
                lines.append(f"  Mean Daily Return: {mean_ret:+.4%}")
                quality = (
                    "Excellent"
                    if sharpe > 1.5
                    else "Good"
                    if sharpe > 0.8
                    else "Fair"
                    if sharpe > 0.3
                    else "Poor"
                )
                lines.append(f"  Strategy Quality : {quality}")
            else:
                lines.append("  No backtest data available.")
            lines.append("")

        # ── Section 6 (v1.3+): Market Regime ──────────────────────────────────
        if self._include_regime:
            sections += 1
            high_vol = risk.get("high_vol_regime", False)
            max_corr = risk.get("max_pairwise_correlation", 0.0)
            recent_vol = risk.get("recent_vol_annualised", None)

            lines += [
                "MARKET REGIME",
                "-" * 40,
            ]
            regime = "HIGH VOLATILITY" if high_vol else "NORMAL"
            lines.append(f"  Regime           : {regime}")
            if recent_vol is not None:
                lines.append(f"  Realised Vol (ann): {recent_vol:.1%}")
            if max_corr > 0:
                lines.append(f"  Max Pair Correl  : {max_corr:.2f}")
                if max_corr > 0.85:
                    lines.append("  ⚠  High correlation — diversification benefit reduced")
            if high_vol:
                lines.append("  ⚠  High-vol regime: consider reducing position sizes")
            lines.append("")

        # ── Footer ─────────────────────────────────────────────────────────────
        lines.append("=" * 68)
        lines.append("  Nodes: DataIngestion | Signals | Strategy | Risk | Reporting")
        lines.append("=" * 68)

        report_text = "\n".join(lines)
        return {
            "report": report_text,
            "sections": sections,
            "timestamp": timestamp,
        }

    def _summarize_market(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """Generate a brief market overview from raw OHLCV data."""
        if not market_data:
            return {"text": "No market data available."}

        valid = {k: v for k, v in market_data.items() if v}
        lines = [f"  Tickers tracked : {len(market_data)} ({len(valid)} with data)"]

        gainers: list[tuple[str, float, float]] = []
        losers: list[tuple[str, float, float]] = []
        for ticker, data in valid.items():
            prices = [
                float(p) for p in (data.get("adjclose") or data.get("close", [])) if p is not None
            ]
            if len(prices) >= 2 and prices[-2] != 0:
                ret = (prices[-1] - prices[-2]) / prices[-2]
                (gainers if ret > 0 else losers).append((ticker, ret, prices[-1]))

        gainers.sort(key=lambda x: -x[1])
        losers.sort(key=lambda x: x[1])

        if gainers:
            top3 = gainers[:3]
            lines.append("  Top gainers     : " + ", ".join(f"{t} ({r:+.2%})" for t, r, _ in top3))
        if losers:
            bot3 = losers[:3]
            lines.append("  Top losers      : " + ", ".join(f"{t} ({r:+.2%})" for t, r, _ in bot3))

        if gainers or losers:
            all_rets = [r for _, r, _ in gainers + losers]
            mkt_ret = sum(all_rets) / len(all_rets)
            lines.append(f"  Market avg 1d   : {mkt_ret:+.3%}")

        return {"text": "\n".join(lines)}

    def _format_signals(self, signals: dict[str, Any]) -> dict[str, Any]:
        """Format signals into a readable table."""
        if not signals:
            return {"text": "  No signals generated."}

        buys = [(t, s) for t, s in signals.items() if s.get("composite", 0.0) > 0.1]
        sells = [(t, s) for t, s in signals.items() if s.get("composite", 0.0) < -0.1]
        neutrals = [(t, s) for t, s in signals.items() if -0.1 <= s.get("composite", 0.0) <= 0.1]

        buys.sort(key=lambda x: -x[1].get("composite", 0.0))
        sells.sort(key=lambda x: x[1].get("composite", 0.0))

        lines = [
            f"  {'Ticker':<12} {'Signal':>8}  {'Price':>10}  {'RSI':>6}  {'1d Ret':>8}",
            f"  {'-' * 12} {'-' * 8}  {'-' * 10}  {'-' * 6}  {'-' * 8}",
        ]

        def fmt_row(ticker: str, sig: dict[str, Any], label: str = "") -> str:
            composite = sig.get("composite", 0.0)
            price = sig.get("price")
            rsi = sig.get("rsi")
            ret_1d = sig.get("return_1d")
            p_str = f"${price:.2f}" if price else "N/A"
            r_str = f"{rsi:.1f}" if rsi is not None else "N/A"
            d_str = f"{ret_1d:+.2%}" if ret_1d is not None else "N/A"
            direction = (
                "▲ BUY " if composite > 0.1 else ("▼ SELL" if composite < -0.1 else "  ---  ")
            )
            return f"  {ticker:<12} {direction}  {p_str:>10}  {r_str:>6}  {d_str:>8}"

        if buys:
            lines.append(f"\n  BUY SIGNALS ({len(buys)}):")
            for ticker, sig in buys[:5]:
                lines.append(fmt_row(ticker, sig))
        if sells:
            lines.append(f"\n  SELL SIGNALS ({len(sells)}):")
            for ticker, sig in sells[:5]:
                lines.append(fmt_row(ticker, sig))
        if neutrals:
            lines.append(f"\n  NEUTRAL ({len(neutrals)} tickers)")

        return {"text": "\n".join(lines)}

    # ------------------------------------------------------------------ helpers

    def _completeness_score(self) -> float:
        """Score based on how many report sections are active."""
        active = 3  # always: market overview, signals, portfolio
        if self._include_risk:
            active += 1
        if self._include_attribution:
            active += 1
        if self._include_regime:
            active += 1
        return active / 6.0

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
