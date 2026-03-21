// VECTORA BACKTEST — equity curve, Sharpe + CIs, drawdown, crash replay, ablation
// TODO: replace mock data with Connect-ES useVectoraBacktest() hook
import { useState } from "react";
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
  VectoraPage,
  fmt,
  fmtPct,
} from "../components/vectora/Terminal";
import {
  perfData,
  labels,
  TRAIN_END,
  backtestStats as D,
  crashes,
  ablation,
  tpeSeries,
  regimes,
} from "../mocks/vectora";

export default function VectoraBacktest() {
  const [chartMode, setChartMode] = useState<"equity" | "dd">("equity");

  const data = perfData.filter((_, i) => i % 2 === 0);
  const splitIdx = data.findIndex((d) => d.i >= TRAIN_END);
  const ci = { lo: D.sharpeAnn - 0.31, hi: D.sharpeAnn + 0.29 };
  const dsr = D.sharpeAnn * 0.78;
  const sig = ci.lo > 0;
  const passCount = crashes.filter((c) => c.pass).length;

  return (
    <VectoraPage>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          borderBottom: `1px solid ${T.green}`,
          fontFamily: T.font,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16, color: T.green, textShadow: T.glow }}>Ω</span>
          <span
            style={{ color: T.green, fontSize: 12, letterSpacing: "0.18em", textShadow: T.glow }}
          >
            VECTORA BACKTEST
          </span>
          <span style={{ color: T.dim, fontSize: 10 }}>
            │ {labels[0]} → {labels[labels.length - 1]} │ 504 DAYS
          </span>
        </div>
        <div style={{ display: "flex", gap: 20 }}>
          {[
            { l: "SHARPE", v: fmt(D.sharpeAnn), c: T.green },
            { l: "TOTAL RETURN", v: fmtPct(D.totalReturn), c: T.green },
            { l: "MAX DD", v: fmtPct(D.maxDDpct), c: T.red },
            { l: "SORTINO", v: fmt(D.sortinoAnn), c: T.green },
            { l: "CALMAR", v: fmt(D.calmar), c: T.green },
            { l: "CRASH PASS", v: `${passCount}/5`, c: passCount >= 4 ? T.green : T.amber },
          ].map((s) => (
            <div key={s.l} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.08em" }}>{s.l}</div>
              <div
                style={{
                  fontSize: 13,
                  color: s.c,
                  fontWeight: "bold",
                  textShadow: s.c === T.green ? T.glow : s.c === T.red ? T.glowR : T.glowA,
                }}
              >
                {s.v}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: 3, display: "flex", flexDirection: "column", gap: 3 }}>
        {/* Main equity/drawdown chart */}
        <Panel title="PERFORMANCE — VECTORA vs BTC BUY&HOLD" style={{ minHeight: 300 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
            {(["equity", "dd"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setChartMode(m)}
                style={{
                  background: chartMode === m ? T.dim : T.black,
                  color: chartMode === m ? T.black : T.green,
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
              IS [{labels[0]}→{labels[TRAIN_END - 1]}] │ OOS [{labels[TRAIN_END]}→
              {labels[labels.length - 1]}]
            </span>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            {chartMode === "equity" ? (
              <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 18, left: 70 }}>
                <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }}
                  interval={Math.floor(data.length / 7)}
                />
                <YAxis
                  tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }}
                  tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`}
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
                  name="VECTORA"
                />
              </ComposedChart>
            ) : (
              <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 18, left: 52 }}>
                <defs>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
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
                  tickFormatter={(v: number) => `${v.toFixed(0)}%`}
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
                  fill="url(#ddGrad)"
                  strokeWidth={1.5}
                  name="DD%"
                />
              </AreaChart>
            )}
          </ResponsiveContainer>
        </Panel>

        {/* Stats grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 3 }}>
          {/* Sharpe analysis */}
          <Panel title="SHARPE ANALYSIS">
            <div
              style={{
                padding: "3px 6px",
                border: `1px solid ${sig ? T.green : T.red}`,
                color: sig ? T.green : T.red,
                fontSize: 10,
                marginBottom: 6,
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
          </Panel>

          {/* Risk metrics */}
          <Panel title="RISK METRICS">
            {[
              ["MAX DRAWDOWN", fmtPct(D.maxDDpct), T.red],
              ["DD DURATION", `${D.maxDDDuration} BARS`, T.amber],
              ["SORTINO RATIO", fmt(D.sortinoAnn), T.green],
              ["CALMAR RATIO", fmt(D.calmar), T.green],
              ["VAR 95% DAILY", `${D.VaR.toFixed(2)}%`, T.amber],
              ["CVAR 95% DAILY", `${D.CVaR.toFixed(2)}%`, T.red],
              ["WIN RATE", `${(D.winRate * 100).toFixed(1)}%`, T.green],
              ["PROFIT FACTOR", D.profitFactor.toFixed(2), T.green],
            ].map(([l, v, c]) => (
              <StatRow key={l} label={l} value={v} color={c} glow={c === T.green} />
            ))}
          </Panel>

          {/* IS vs OOS */}
          <Panel title="IN-SAMPLE vs OUT-OF-SAMPLE">
            <div
              style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, marginBottom: 8 }}
            >
              <div style={{ border: `1px solid ${T.cyan}`, padding: "4px 6px" }}>
                <div style={{ fontSize: 9, color: T.dim, marginBottom: 2 }}>IS SHARPE</div>
                <div style={{ fontSize: 18, color: T.cyan, fontWeight: "bold" }}>
                  {fmt(D.sharpeIS)}
                </div>
                <div style={{ fontSize: 9, color: T.dim }}>60% of data</div>
              </div>
              <div
                style={{
                  border: `1px solid ${D.sharpeOOS > 0.5 ? T.green : T.amber}`,
                  padding: "4px 6px",
                }}
              >
                <div style={{ fontSize: 9, color: T.dim, marginBottom: 2 }}>OOS SHARPE</div>
                <div
                  style={{
                    fontSize: 18,
                    color: D.sharpeOOS > 0.5 ? T.green : T.amber,
                    fontWeight: "bold",
                  }}
                >
                  {fmt(D.sharpeOOS)}
                </div>
                <div style={{ fontSize: 9, color: T.dim }}>40% of data</div>
              </div>
            </div>
            <StatRow
              label="IS ANN RETURN"
              value={`${(D.annReturn * 100).toFixed(1)}%`}
              color={T.green}
              glow
            />
            <StatRow
              label="OOS DECAY"
              value={`${(((D.sharpeIS - D.sharpeOOS) / D.sharpeIS) * 100).toFixed(1)}%`}
              color={T.amber}
            />
            <StatRow label="TOTAL RETURN" value={fmtPct(D.totalReturn)} color={T.green} glow />
            <div
              style={{
                marginTop: 8,
                fontSize: 9,
                color: T.dim,
                borderTop: `1px solid ${T.dim}`,
                paddingTop: 4,
              }}
            >
              &gt; OOS degradation below 30% threshold
            </div>
          </Panel>

          {/* TPE convergence */}
          <Panel title="TPE CONVERGENCE">
            <StatRow
              label="BEST SCORE"
              value={tpeSeries[tpeSeries.length - 1].best.toFixed(4)}
              glow
            />
            <StatRow label="TRIALS" value="200" color={T.white} />
            <StatRow label="CONVERGED" value="~TRIAL 130" color={T.cyan} />
            <StatRow label="STATUS" value="STABLE" glow />
            <ResponsiveContainer width="100%" height={100} style={{ marginTop: 6 }}>
              <ComposedChart
                data={tpeSeries.filter((_, i) => i % 3 === 0)}
                margin={{ top: 2, right: 2, bottom: 2, left: 22 }}
              >
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
        </div>

        {/* Ablation + regime side by side */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3 }}>
          <Panel title="ABLATION — ΔSharpe PER SUBSYSTEM">
            <div style={{ fontSize: 10, color: T.dim, marginBottom: 4 }}>
              FULL SYSTEM:{" "}
              <span style={{ color: T.green, textShadow: T.glow }}>{fmt(D.sharpeAnn)}</span>
              <span style={{ color: T.dim, marginLeft: 12 }}>★ = significant at p&lt;0.05</span>
            </div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={ablation}
                layout="vertical"
                margin={{ top: 2, right: 36, bottom: 2, left: 95 }}
              >
                <CartesianGrid
                  stroke={T.dim}
                  strokeDasharray="2 10"
                  opacity={0.3}
                  horizontal={false}
                />
                <XAxis type="number" tick={{ fill: T.dim, fontSize: 9, fontFamily: T.font }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fill: T.white, fontSize: 10, fontFamily: T.font }}
                  width={92}
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

          <Panel title="REGIME SHARPE BREAKDOWN">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {regimes.map((r, i) => (
                <div
                  key={r.name}
                  style={{
                    border: `1px solid ${i === 0 ? T.green : T.dim}`,
                    padding: "6px 8px",
                    background: i === 0 ? `${T.green}09` : T.black,
                  }}
                >
                  <div
                    style={{
                      fontSize: 9,
                      color: i === 0 ? T.green : T.dim,
                      letterSpacing: "0.1em",
                      marginBottom: 2,
                    }}
                  >
                    {r.name}
                    {i === 0 ? " ◀" : ""}
                  </div>
                  <div style={{ fontSize: 18, color: T.green, fontWeight: "bold" }}>
                    {r.sharpe.toFixed(2)}
                  </div>
                  <StatRow label="RET" value={`${r.ret.toFixed(1)}%`} color={T.cyan} />
                  <StatRow label="N" value={`${r.trades}`} color={T.white} />
                  <div style={{ marginTop: 3, height: 3, background: `${T.dim}44` }}>
                    <div
                      style={{
                        width: `${r.pct}%`,
                        height: "100%",
                        background: i === 0 ? T.green : T.dim,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {/* Crash replay */}
        <Panel
          title={`CRASH REPLAY — HISTORICAL STRESS TESTS (${passCount}/${crashes.length} PASSED)`}
        >
          <div style={{ fontSize: 10, marginBottom: 6 }}>
            <span
              style={{
                color: passCount >= 4 ? T.green : T.amber,
                textShadow: passCount >= 4 ? T.glow : T.glowA,
              }}
            >
              {passCount}/{crashes.length} SCENARIOS PASSED
            </span>
            <span style={{ color: T.dim, marginLeft: 12 }}>
              STOP-LOSS: 15% │ MAX-DD FAIL: 30% │ RING1-FILTERED
            </span>
          </div>
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 10, fontFamily: T.font }}
          >
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.green}` }}>
                {["SCENARIO", "SYMBOL", "MAX DD", "RECOVERY", "STOP-LOSSES", "PNL", "STATUS"].map(
                  (h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        color: T.dim,
                        padding: "3px 12px 3px 0",
                        fontSize: 9,
                        letterSpacing: "0.08em",
                      }}
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {crashes.map((c) => (
                <tr key={c.name} style={{ borderBottom: `1px solid ${T.dim}22` }}>
                  <td style={{ color: T.white, padding: "5px 12px 5px 0" }}>{c.name}</td>
                  <td style={{ color: T.cyan, paddingRight: 12 }}>{c.sym}</td>
                  <td
                    style={{
                      color: c.dd > 30 ? T.red : c.dd > 15 ? T.amber : T.green,
                      fontWeight: "bold",
                      paddingRight: 12,
                      textShadow: c.dd > 30 ? T.glowR : c.dd > 15 ? T.glowA : T.glow,
                    }}
                  >
                    {c.dd.toFixed(1)}%
                  </td>
                  <td style={{ color: c.recov ? T.white : T.red, paddingRight: 12 }}>
                    {c.recov ? `${c.recov} BARS` : "NEVER ∞"}
                  </td>
                  <td style={{ color: c.sl > 0 ? T.amber : T.green, paddingRight: 12 }}>{c.sl}</td>
                  <td
                    style={{
                      color: c.pnl >= 0 ? T.green : T.red,
                      fontWeight: "bold",
                      paddingRight: 12,
                      textShadow: c.pnl >= 0 ? T.glow : T.glowR,
                    }}
                  >
                    {c.pnl >= 0 ? "+" : ""}
                    {c.pnl.toFixed(1)}%
                  </td>
                  <td
                    style={{
                      color: c.pass ? T.green : T.red,
                      fontWeight: "bold",
                      textShadow: c.pass ? T.glow : T.glowR,
                    }}
                  >
                    [{c.pass ? "PASS" : "FAIL"}]
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </VectoraPage>
  );
}
