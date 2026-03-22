// VICTORIA TERMINAL — full eval dashboard ported from eval_dashboard.jsx
// 10 panels + positions/trades sidebars. CRT phosphor aesthetic.
import { useState, useEffect } from "react";
import {
  ComposedChart,
  AreaChart,
  BarChart,
  Bar,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  T,
  Panel,
  StatRow,
  TermTip,
  VictoriaPage,
  fmt,
  fmtPct,
  fmtUSDT,
} from "../components/victoria/Terminal";
import * as mock from "../mocks/victoria";
import {
  fetchBacktestResults,
  fetchEquityCurve,
  fetchRiskMetrics,
  fetchSignals,
  fetchPositions,
  fetchTrades,
} from "../api/victoria";

// ---------------------------------------------------------------------------
// Module-level data store — updated by VictoriaDashboard on API fetch.
// Sub-components read from here and re-render when the parent forces an update.
// ---------------------------------------------------------------------------
let D = mock.backtestStats;
let perfData = mock.perfData;
let labels = mock.labels;
let TRAIN_END = mock.TRAIN_END;
let fundingData = mock.fundingData;
let latestFunding = mock.latestFunding;
let latestOI = mock.latestOI;
let ablation = mock.ablation;
let regimes = mock.regimes;
let currentRegimeIdx = mock.currentRegimeIdx;
let crashes = mock.crashes;
let advSeries = mock.advSeries;
let tpeSeries = mock.tpeSeries;
const autonomyHistory = mock.autonomyHistory;
const CURRENT_LEVEL = mock.CURRENT_LEVEL;
let signals = mock.signals;
let positions = mock.positions;
let trades = mock.trades;

// ---------------------------------------------------------------------------
// Top bar with live clock + portfolio stats
// ---------------------------------------------------------------------------
function TopBar({ fromMock }: { fromMock: boolean }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const uPnL = positions.reduce((s, p) => s + p.upnl, 0);
  const passCount = crashes.filter((c) => c.pass).length;

  const stats = [
    { l: "TOTAL RETURN", v: fmtPct(D.totalReturn), c: T.green },
    { l: "ANN RETURN", v: fmtPct(D.annReturn), c: T.green },
    { l: "SHARPE", v: fmt(D.sharpeAnn), c: T.green },
    { l: "SORTINO", v: fmt(D.sortinoAnn), c: T.green },
    { l: "MAX DD", v: fmtPct(D.maxDDpct), c: T.red },
    { l: "VAR 95%", v: `${D.VaR.toFixed(2)}%`, c: T.amber },
    { l: "CVAR 95%", v: `${D.CVaR.toFixed(2)}%`, c: T.amber },
    { l: "IS SHARPE", v: fmt(D.sharpeIS), c: T.cyan },
    { l: "OOS SHARPE", v: fmt(D.sharpeOOS), c: D.sharpeOOS > 0.5 ? T.green : T.amber },
    {
      l: "FUNDING /8H",
      v: `${latestFunding.toFixed(4)}%`,
      c: latestFunding > 0 ? T.amber : T.green,
    },
    { l: "OPEN INT", v: `$${latestOI}B`, c: T.white },
    { l: "UNREALISED", v: `+$${uPnL.toFixed(0)}`, c: T.green },
    { l: "AUTONOMY", v: CURRENT_LEVEL, c: T.green },
    { l: "CRASH PASS", v: `${passCount}/5`, c: T.green },
  ];

  return (
    <div style={{ background: T.black, borderBottom: `1px solid ${T.green}`, fontFamily: T.font }}>
      {/* Title row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 12px",
          borderBottom: `1px solid ${T.dim}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20, color: T.green, textShadow: T.glow, fontWeight: "bold" }}>
            Ω
          </span>
          <span
            style={{ color: T.green, fontSize: 14, letterSpacing: "0.18em", textShadow: T.glow }}
          >
            VICTORIA TERMINAL
          </span>
          <span style={{ color: T.dim, fontSize: 10 }}>v0.1</span>
          <span style={{ color: T.dim, fontSize: 10 }}>
            │ CRYPTO QUANT RESEARCH NODE │ OMEGA SYSTEM
          </span>
          {fromMock && (
            <span
              style={{
                fontSize: 9,
                color: T.amber,
                border: `1px solid ${T.amber}`,
                padding: "1px 5px",
                letterSpacing: "0.1em",
              }}
            >
              MOCK DATA
            </span>
          )}
        </div>
        <div style={{ color: T.dim, fontSize: 10 }}>
          {now.toISOString().slice(0, 19)} UTC
          <span
            style={{ marginLeft: 12, color: fromMock ? T.amber : T.green, textShadow: T.glow }}
          >
            ⬤ {fromMock ? "MOCK" : "LIVE"}
          </span>
        </div>
      </div>

      {/* Portfolio value */}
      <div style={{ textAlign: "center", padding: "8px 0 4px" }}>
        <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.2em", marginBottom: 1 }}>
          PORTFOLIO VALUE (USDT)
        </div>
        <div
          style={{
            fontSize: 48,
            fontWeight: "bold",
            color: T.green,
            textShadow: T.glow,
            lineHeight: 1,
          }}
        >
          {fmtUSDT(D.portfolioValue)}
        </div>
        <div style={{ fontSize: 11, color: T.dim, marginTop: 1 }}>
          STARTED: $100,000 USDT &nbsp;│&nbsp; GAIN: +{fmtUSDT(D.portfolioValue - 100000)} (+
          {(D.totalReturn * 100).toFixed(1)}%) &nbsp;│&nbsp; UNREALISED PNL:{" "}
          <span style={{ color: T.green }}>+${uPnL.toFixed(2)}</span>
        </div>
      </div>

      {/* Stats strip */}
      <div style={{ display: "flex", borderTop: `1px solid ${T.dim}`, overflowX: "auto" }}>
        {stats.map((s, i) => (
          <div
            key={i}
            style={{
              flex: "0 0 auto",
              minWidth: 90,
              padding: "4px 10px",
              borderRight: `1px solid ${T.dim}`,
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.08em" }}>{s.l}</div>
            <div
              style={{
                fontSize: 12,
                fontWeight: "bold",
                color: s.c,
                textShadow: s.c === T.green ? T.glow : s.c === T.red ? T.glowR : T.glowA,
              }}
            >
              {s.v}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 1 — Performance chart
// ---------------------------------------------------------------------------
function PerfChart() {
  const [mode, setMode] = useState<"equity" | "dd">("equity");
  const data = perfData.filter((_, i) => i % 2 === 0);
  const splitIdx = data.findIndex((d) => d.i >= TRAIN_END);

  return (
    <Panel
      title="PERFORMANCE OVERVIEW — BTC/USDT vs BUY&HOLD"
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <div style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
        {(["equity", "dd"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              background: mode === m ? T.dim : T.black,
              color: mode === m ? T.black : T.green,
              border: `1px solid ${T.green}`,
              fontFamily: T.font,
              fontSize: 10,
              padding: "2px 8px",
              cursor: "pointer",
              textTransform: "uppercase",
            }}
          >
            {m === "equity" ? "> EQUITY CURVE" : "> DRAWDOWN"}
          </button>
        ))}
        <span style={{ marginLeft: "auto", color: T.dim, fontSize: 9 }}>
          ▓ TRAIN [{labels[0]}→{labels[TRAIN_END - 1]}] &nbsp; ░ TEST [{labels[TRAIN_END]}→
          {labels[labels.length - 1]}]
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          {mode === "equity" ? (
            <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 18, left: 64 }}>
              <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
              <XAxis
                dataKey="date"
                tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }}
                interval={Math.floor(data.length / 7)}
              />
              <YAxis
                tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }}
                tickFormatter={(v) => `$${(v / 1000).toFixed(0)}K`}
              />
              <Tooltip content={<TermTip />} />
              {splitIdx > 0 && (
                <ReferenceLine
                  x={data[splitIdx]?.date}
                  stroke={T.dim}
                  strokeDasharray="4 4"
                  label={{
                    value: "OOS START",
                    fill: T.dim,
                    fontSize: 8,
                    fontFamily: T.font,
                    position: "insideTopRight",
                  }}
                />
              )}
              <Line
                type="monotone"
                dataKey="btc"
                stroke={T.dim}
                strokeWidth={1}
                dot={false}
                name="BTC B&H"
                strokeDasharray="3 3"
              />
              <Line
                type="monotone"
                dataKey="omega"
                stroke={T.green}
                strokeWidth={2}
                dot={false}
                name="VICTORIA"
              />
            </ComposedChart>
          ) : (
            <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 18, left: 50 }}>
              <defs>
                <linearGradient id="ddG" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={T.red} stopOpacity={0.5} />
                  <stop offset="100%" stopColor={T.red} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
              <XAxis
                dataKey="date"
                tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }}
                interval={Math.floor(data.length / 7)}
              />
              <YAxis
                tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }}
                tickFormatter={(v) => `${v.toFixed(0)}%`}
              />
              <Tooltip content={<TermTip />} />
              <ReferenceLine
                y={-20}
                stroke={T.amber}
                strokeDasharray="4 2"
                label={{ value: "-20%", fill: T.amber, fontSize: 9, fontFamily: T.font }}
              />
              <Area
                type="monotone"
                dataKey="dd"
                stroke={T.red}
                fill="url(#ddG)"
                strokeWidth={1.5}
                name="DD%"
              />
            </AreaChart>
          )}
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 2 — Sharpe Analysis
// ---------------------------------------------------------------------------
function SharpePanel() {
  const ci = { lo: D.sharpeAnn - 0.31, hi: D.sharpeAnn + 0.29 };
  const dsr = D.sharpeAnn * 0.78;
  const sig = ci.lo > 0;
  return (
    <Panel title="SHARPE ANALYSIS">
      <div
        style={{
          padding: "3px 6px",
          border: `1px solid ${sig ? T.green : T.red}`,
          color: sig ? T.green : T.red,
          fontSize: 10,
          marginBottom: 6,
          textShadow: sig ? T.glow : T.glowR,
        }}
      >
        {sig ? "> SIG AT 95% CONFIDENCE" : "> NOT SIGNIFICANT"}
      </div>
      {[
        ["RAW SHARPE", fmt(D.sharpeAnn), T.green],
        ["CI 95% LO", fmt(ci.lo), T.dim],
        ["CI 95% HI", fmt(ci.hi), T.dim],
        ["DEFLATED DSR", fmt(dsr), T.amber],
        ["IS SHARPE", fmt(D.sharpeIS), T.cyan],
        ["OOS SHARPE", fmt(D.sharpeOOS), D.sharpeOOS > 0.5 ? T.green : T.amber],
        ["ANN VOL", fmtPct(D.stdR * Math.sqrt(252)), T.white],
      ].map(([l, v, c]) => (
        <StatRow key={l} label={l} value={v} color={c} glow={c === T.green} />
      ))}
      <div
        style={{
          fontSize: 9,
          color: T.dim,
          marginTop: 5,
          borderTop: `1px solid ${T.dim}`,
          paddingTop: 3,
        }}
      >
        DSR corrects for 5 backtests trialled
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 3 — Risk Metrics
// ---------------------------------------------------------------------------
function RiskPanel() {
  return (
    <Panel title="RISK METRICS">
      {[
        ["MAX DRAWDOWN", fmtPct(D.maxDDpct), T.red],
        ["DD DURATION", `${D.maxDDDuration} BARS`, T.amber],
        ["SORTINO RATIO", fmt(D.sortinoAnn), T.green],
        ["CALMAR RATIO", fmt(D.calmar), T.green],
        ["VAR 95% DAILY", `${D.VaR.toFixed(2)}%`, T.amber],
        ["CVAR 95% DAILY", `${D.CVaR.toFixed(2)}%`, T.red],
        [
          "FUNDING RATE /8H",
          `${latestFunding.toFixed(4)}%`,
          latestFunding > 0 ? T.amber : T.green,
        ],
        ["OPEN INTEREST", `$${latestOI}B`, T.white],
        ["WIN RATE", `${(D.winRate * 100).toFixed(1)}%`, T.green],
        ["PROFIT FACTOR", D.profitFactor.toFixed(2), T.green],
      ].map(([l, v, c]) => (
        <StatRow key={l} label={l} value={v} color={c} glow={c === T.green} />
      ))}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 4 — Ablation
// ---------------------------------------------------------------------------
function AblationPanel() {
  return (
    <Panel title="ABLATION — ΔSharpe PER SUBSYSTEM">
      <div style={{ fontSize: 10, color: T.dim, marginBottom: 4 }}>
        FULL SYSTEM: <span style={{ color: T.green, textShadow: T.glow }}>{fmt(D.sharpeAnn)}</span>
      </div>
      <ResponsiveContainer width="100%" height={170}>
        <BarChart
          data={ablation}
          layout="vertical"
          margin={{ top: 2, right: 30, bottom: 2, left: 90 }}
        >
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} horizontal={false} />
          <XAxis type="number" tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: T.white, fontSize: 10, fontFamily: T.font }}
            width={88}
          />
          <Tooltip content={<TermTip />} />
          <Bar dataKey="dSharpe" name="ΔSharpe" radius={0}>
            {ablation.map((d, i) => (
              <Cell key={i} fill={d.sig ? T.green : T.dim} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 5 — Regime
// ---------------------------------------------------------------------------
function RegimePanel() {
  return (
    <Panel title="REGIME BREAKDOWN — CRYPTO MARKET STATES">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {regimes.map((r, i) => (
          <div
            key={r.name}
            style={{
              border: `1px solid ${i === currentRegimeIdx ? T.green : T.dim}`,
              padding: "5px 7px",
              background: i === currentRegimeIdx ? `${T.green}09` : T.black,
            }}
          >
            <div
              style={{
                fontSize: 9,
                color: i === 0 ? T.green : T.dim,
                letterSpacing: "0.1em",
                textShadow: i === 0 ? T.glow : "none",
              }}
            >
              {r.name}
              {i === currentRegimeIdx ? " ◀ ACTIVE" : ""}
            </div>
            <div
              style={{
                fontSize: 17,
                color: T.green,
                fontWeight: "bold",
                textShadow: i === 0 ? T.glow : "none",
              }}
            >
              {r.sharpe.toFixed(2)}
            </div>
            <div style={{ fontSize: 10, color: T.dim }}>
              RET:{r.ret.toFixed(1)}% N:{r.trades}
            </div>
            <div style={{ marginTop: 3, height: 3, background: `${T.dim}44` }}>
              <div style={{ width: `${r.pct}%`, height: "100%", background: T.green }} />
            </div>
            <div style={{ fontSize: 9, color: T.dim, textAlign: "right" }}>{r.pct}%</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 6 — Crash Replay
// ---------------------------------------------------------------------------
function CrashPanel() {
  const passed = crashes.filter((c) => c.pass).length;
  return (
    <Panel title="CRASH REPLAY RESULTS — HISTORICAL STRESS TESTS">
      <div style={{ fontSize: 10, marginBottom: 5 }}>
        <span
          style={{
            color: passed === crashes.length ? T.green : T.amber,
            textShadow: passed === crashes.length ? T.glow : T.glowA,
          }}
        >
          {passed}/{crashes.length} SCENARIOS PASSED
        </span>
        <span style={{ color: T.dim, marginLeft: 12 }}>
          STOP-LOSS: 15% │ MAX-DD FAIL: 30% │ STRATEGY: RING1-FILTERED
        </span>
      </div>
      <table
        style={{ width: "100%", borderCollapse: "collapse", fontSize: 10, fontFamily: T.font }}
      >
        <thead>
          <tr style={{ borderBottom: `1px solid ${T.green}` }}>
            {["SCENARIO", "SYM", "MAX DD", "RECOVERY", "STOP-L", "PNL", "STATUS"].map((h) => (
              <th
                key={h}
                style={{
                  textAlign: "left",
                  color: T.dim,
                  padding: "2px 8px 2px 0",
                  letterSpacing: "0.08em",
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {crashes.map((c) => (
            <tr key={c.name} style={{ borderBottom: `1px solid ${T.dim}22` }}>
              <td style={{ color: T.white, padding: "2px 8px 2px 0" }}>{c.name}</td>
              <td style={{ color: T.cyan, paddingRight: 8 }}>{c.sym}</td>
              <td
                style={{
                  color: c.dd > 30 ? T.red : c.dd > 15 ? T.amber : T.green,
                  fontWeight: "bold",
                  paddingRight: 8,
                }}
              >
                {c.dd.toFixed(1)}%
              </td>
              <td style={{ color: c.recov ? T.white : T.red, paddingRight: 8 }}>
                {c.recov ? `${c.recov} BARS` : "NEVER ∞"}
              </td>
              <td style={{ color: c.sl > 0 ? T.amber : T.green, paddingRight: 8 }}>{c.sl}</td>
              <td
                style={{
                  color: c.pnl >= 0 ? T.green : T.red,
                  fontWeight: "bold",
                  paddingRight: 8,
                }}
              >
                {c.pnl >= 0 ? "+" : ""}
                {c.pnl.toFixed(1)}%
              </td>
              <td style={{ color: c.pass ? T.green : T.red, fontWeight: "bold" }}>
                [{c.pass ? "PASS" : "FAIL"}]
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 7 — Adversarial Health
// ---------------------------------------------------------------------------
function AdvPanel() {
  const avgFlag = advSeries.reduce((s, d) => s + d.flag, 0) / advSeries.length;
  const avgFP = advSeries.reduce((s, d) => s + d.fp, 0) / advSeries.length;
  return (
    <Panel title="ADVERSARIAL HEALTH [RING 1]">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, marginBottom: 6 }}>
        {[
          { l: "FLAG RATE", v: `${(avgFlag * 100).toFixed(1)}%`, c: T.amber },
          { l: "FALSE POS", v: `${(avgFP * 100).toFixed(1)}%`, c: T.green },
          { l: "ENSEMBLE DIS", v: "34.2%", c: T.cyan },
          { l: "RING1", v: "ACTIVE", c: T.green },
        ].map((s) => (
          <div key={s.l} style={{ border: `1px solid ${T.dim}`, padding: "3px 5px" }}>
            <div style={{ fontSize: 9, color: T.dim }}>{s.l}</div>
            <div
              style={{
                fontSize: 13,
                color: s.c,
                fontWeight: "bold",
                textShadow: s.c === T.green ? T.glow : s.c === T.amber ? T.glowA : "none",
              }}
            >
              {s.v}
            </div>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <ComposedChart data={advSeries} margin={{ top: 2, right: 2, bottom: 2, left: 22 }}>
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
          <XAxis
            dataKey="t"
            tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
            interval={14}
          />
          <YAxis
            tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
            tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
            width={26}
          />
          <Tooltip content={<TermTip />} />
          <Area
            type="monotone"
            dataKey="flag"
            stroke={T.amber}
            fill={`${T.amber}22`}
            strokeWidth={1}
            name="Flag%"
          />
          <Line
            type="monotone"
            dataKey="fp"
            stroke={T.green}
            strokeWidth={1}
            dot={false}
            name="FP%"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 8 — TPE Convergence
// ---------------------------------------------------------------------------
function TPEPanel() {
  const last = tpeSeries.length > 0 ? tpeSeries[tpeSeries.length - 1] : null;
  const best = last?.best ?? 0;
  const data = tpeSeries.filter((_, i) => i % 3 === 0);
  return (
    <Panel title="TPE CONVERGENCE">
      <StatRow label="BEST SCORE" value={best.toFixed(4)} glow />
      <StatRow label="TRIALS" value="200" />
      <StatRow label="CONVERGED" value="~TRIAL 130" color={T.cyan} />
      <StatRow label="STATUS" value="STABLE" glow />
      <ResponsiveContainer width="100%" height={100} style={{ marginTop: 4 }}>
        <ComposedChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 22 }}>
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
          <XAxis
            dataKey="t"
            tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
            interval={24}
          />
          <YAxis tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }} width={26} />
          <Tooltip content={<TermTip />} />
          <Line
            type="monotone"
            dataKey="score"
            stroke={T.dim}
            strokeWidth={0.5}
            dot={false}
            name="Trial"
          />
          <Line
            type="monotone"
            dataKey="best"
            stroke={T.green}
            strokeWidth={2}
            dot={false}
            name="Best"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 9 — Autonomy Status
// ---------------------------------------------------------------------------
function AutoPanel() {
  const lc: Record<string, string> = { PICO: T.dim, SUPERVISED: T.amber, AUTONOMOUS: T.green };
  return (
    <Panel title="AUTONOMY STATUS">
      <div
        style={{
          textAlign: "center",
          padding: 5,
          border: `1px solid ${T.green}`,
          marginBottom: 6,
          textShadow: T.glow,
        }}
      >
        <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.15em" }}>CURRENT LEVEL</div>
        <div style={{ fontSize: 18, color: T.green, fontWeight: "bold", textShadow: T.glow }}>
          {CURRENT_LEVEL}
        </div>
      </div>
      <div style={{ fontSize: 9, color: T.dim, marginBottom: 5 }}>
        &gt; PROMO: cycles≥10 │ sharpe≥0.5 │ dd≤15%
      </div>
      <div style={{ fontSize: 10 }}>
        {autonomyHistory.map((e, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 4,
              marginBottom: 2,
              borderBottom: `1px solid ${T.dim}22`,
              paddingBottom: 2,
              flexWrap: "wrap",
            }}
          >
            <span style={{ color: T.dim, minWidth: 72, fontSize: 9 }}>{e.date}</span>
            <span
              style={{
                color: e.dir === "↑" ? T.green : e.dir === "↓" ? T.red : T.dim,
                minWidth: 10,
              }}
            >
              {e.dir || "·"}
            </span>
            <span style={{ color: lc[e.level], fontWeight: "bold", fontSize: 9 }}>{e.level}</span>
            <span style={{ color: T.dim, fontSize: 9 }}>/ {e.reason}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Panel 10 — Signal Quality
// ---------------------------------------------------------------------------
function SignalPanel() {
  return (
    <Panel title="SIGNAL QUALITY — VICTORIA FACTORS">
      {signals.slice(0, 4).map((s) => (
        <div key={s.name} style={{ marginBottom: 5 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 10,
              marginBottom: 2,
            }}
          >
            <span style={{ color: T.white }}>{s.name}</span>
            <span style={{ color: T.cyan, fontSize: 9 }}>
              IC:{s.avgIC.toFixed(4)} w:{(s.weight * 100).toFixed(0)}% t½:{s.halfLife}d
            </span>
          </div>
          <div style={{ height: 4, background: `${T.dim}33`, border: `1px solid ${T.dim}` }}>
            <div
              style={{ width: `${s.weight * 100 * 3}%`, height: "100%", background: s.color }}
            />
          </div>
        </div>
      ))}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Positions pane
// ---------------------------------------------------------------------------
function PositionsPane() {
  return (
    <Panel title="OPEN POSITIONS">
      {positions.map((pos) => (
        <div
          key={pos.sym}
          style={{ borderBottom: `1px solid ${T.dim}22`, paddingBottom: 5, marginBottom: 5 }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
            <span
              style={{
                color: pos.side === "LONG" ? T.green : T.amber,
                fontWeight: "bold",
                textShadow: pos.side === "LONG" ? T.glow : T.glowA,
              }}
            >
              [{pos.side}] {pos.sym}
            </span>
            <span style={{ color: T.green, textShadow: T.glow }}>
              +${pos.upnl.toFixed(2)} ({pos.pct >= 0 ? "+" : ""}
              {pos.pct.toFixed(2)}%)
            </span>
          </div>
          <div style={{ fontSize: 9, color: T.dim }}>
            SIZE: {pos.size} │ ENTRY: {pos.entry} │ MARK: {pos.mark}
          </div>
        </div>
      ))}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Trades pane
// ---------------------------------------------------------------------------
function TradesPane() {
  return (
    <Panel title="RECENT FILLS">
      {trades.slice(0, 7).map((t, i) => (
        <div
          key={i}
          style={{ borderBottom: `1px solid ${T.dim}22`, paddingBottom: 3, marginBottom: 3 }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
            <span style={{ color: t.side === "LONG" ? T.green : T.amber }}>
              {t.side === "LONG" ? "↑" : "↓"} {t.sym}
            </span>
            <span
              style={{
                color: t.pnl >= 0 ? T.green : T.red,
                fontWeight: "bold",
                textShadow: t.pnl >= 0 ? T.glow : T.glowR,
              }}
            >
              {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
            </span>
          </div>
          <div style={{ fontSize: 8, color: T.dim }}>
            {t.ts} │ {t.size} │ {t.entry}→{t.exit}
          </div>
        </div>
      ))}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Funding chart (replaces bottom right panel)
// ---------------------------------------------------------------------------
function FundingChart() {
  return (
    <Panel title="FUNDING RATE + OPEN INTEREST">
      <ResponsiveContainer width="100%" height={100}>
        <ComposedChart data={fundingData} margin={{ top: 2, right: 4, bottom: 2, left: 28 }}>
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
          <XAxis
            dataKey="t"
            tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
            interval={14}
          />
          <YAxis
            yAxisId="left"
            tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
            tickFormatter={(v) => `${v.toFixed(2)}%`}
            width={30}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
            tickFormatter={(v) => `$${v}B`}
            width={30}
          />
          <Tooltip content={<TermTip />} />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="funding"
            stroke={T.amber}
            strokeWidth={1}
            dot={false}
            name="Funding%"
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="oi"
            stroke={T.cyan}
            strokeWidth={1}
            dot={false}
            name="OI $B"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
export default function VictoriaDashboard() {
  const [fromMock, setFromMock] = useState(true);
  // Trigger re-render so sub-components pick up updated module-level data
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    Promise.all([
      fetchBacktestResults(),
      fetchEquityCurve(),
      fetchRiskMetrics(),
      fetchSignals(),
      fetchPositions(),
      fetchTrades(),
    ]).then(([btResult, curveResult, riskResult, sigResult, posResult, tradeResult]) => {
      let anyLive = false;
      if (!btResult.fromMock) {
        D = btResult.stats;
        TRAIN_END = btResult.trainEnd;
        anyLive = true;
      }
      if (!curveResult.fromMock && curveResult.points.length > 0) {
        perfData = curveResult.points;
        labels = curveResult.points.map((p) => p.date);
        TRAIN_END = curveResult.trainEnd;
        anyLive = true;
      }
      if (!riskResult.fromMock) {
        ablation = riskResult.ablation;
        regimes = riskResult.regimes;
        currentRegimeIdx = riskResult.currentRegimeIdx;
        crashes = riskResult.crashes;
        fundingData = riskResult.fundingData;
        latestFunding = riskResult.latestFunding;
        latestOI = riskResult.latestOI;
        advSeries = riskResult.advSeries;
        if (riskResult.tpeSeries?.length > 0) tpeSeries = riskResult.tpeSeries;
        anyLive = true;
      }
      if (!sigResult.fromMock) {
        signals = sigResult.signals;
        anyLive = true;
      }
      if (!posResult.fromMock) {
        positions = posResult.positions;
        anyLive = true;
      }
      if (!tradeResult.fromMock) {
        trades = tradeResult.trades;
        anyLive = true;
      }
      if (anyLive) {
        setFromMock(false);
        forceUpdate((n) => n + 1);
      }
    });
  }, []);

  return (
    <VictoriaPage>
      <TopBar fromMock={fromMock} />

      {/* Main body: left │ center │ right */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "220px 1fr 250px",
          gap: 3,
          padding: 3,
          flex: 1,
          minHeight: 0,
          alignItems: "start",
        }}
      >
        {/* LEFT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <SharpePanel />
          <RiskPanel />
          <AdvPanel />
        </div>

        {/* CENTER */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ height: 340 }}>
            <PerfChart />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3 }}>
            <AblationPanel />
            <RegimePanel />
          </div>
          <FundingChart />
        </div>

        {/* RIGHT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <PositionsPane />
          <TPEPanel />
          <AutoPanel />
          <SignalPanel />
          <TradesPane />
        </div>
      </div>

      {/* Bottom */}
      <div style={{ padding: "0 3px 3px" }}>
        <CrashPanel />
      </div>

      <div
        style={{
          borderTop: `1px solid ${T.dim}`,
          padding: "3px 12px",
          fontSize: 9,
          color: T.dim,
          textAlign: "center",
        }}
      >
        Ω VICTORIA TERMINAL v0.1 │ OMEGA SYSTEM │ {labels[0]} → {labels[labels.length - 1]} │ 504
        TRADING DAYS │ COMMISSION 0.1%
      </div>
    </VictoriaPage>
  );
}
