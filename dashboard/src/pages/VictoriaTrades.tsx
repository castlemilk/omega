// VICTORIA TRADES — full trade history, entry/exit, slippage, P&L
import { useEffect, useState } from "react";
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Line,
} from "recharts";
import { T, Panel, StatRow, TermTip, VictoriaPage } from "../components/victoria/Terminal";
import * as mock from "../mocks/victoria";
import type { Trade } from "../mocks/victoria";
import { fetchTrades } from "../api/victoria";

type FilterSym = "ALL" | "BTC/USDT" | "ETH/USDT" | "SOL/USDT";
type FilterSide = "ALL" | "LONG" | "SHORT";

function buildCumPnl(trades: Trade[]) {
  return trades
    .slice()
    .reverse()
    .reduce<{ i: number; pnl: number; cum: number }[]>((acc, t, i) => {
      const prev = acc[acc.length - 1]?.cum ?? 0;
      acc.push({ i: i + 1, pnl: t.pnl, cum: +(prev + t.pnl).toFixed(2) });
      return acc;
    }, []);
}

export default function VictoriaTrades() {
  const [trades, setTrades] = useState<Trade[]>(mock.trades);
  const [fromMock, setFromMock] = useState(true);
  const [symFilter, setSymFilter] = useState<FilterSym>("ALL");
  const [sideFilter, setSideFilter] = useState<FilterSide>("ALL");

  useEffect(() => {
    fetchTrades().then((result) => {
      if (!result.fromMock) setTrades(result.trades);
      setFromMock(result.fromMock);
    });
  }, []);

  const cumPnl = buildCumPnl(trades);

  const filtered = trades.filter((t) => {
    if (symFilter !== "ALL" && t.sym !== symFilter) return false;
    if (sideFilter !== "ALL" && t.side !== sideFilter) return false;
    return true;
  });

  const wins = filtered.filter((t) => t.pnl > 0).length;
  const totalPnl = filtered.reduce((s, t) => s + t.pnl, 0);
  const avgWin =
    wins > 0 ? filtered.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0) / wins : 0;
  const losses = filtered.filter((t) => t.pnl < 0).length;
  const avgLoss =
    losses > 0
      ? Math.abs(filtered.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0) / losses)
      : 0;
  const profitFactor = avgLoss > 0 ? avgWin / avgLoss : Infinity;
  const avgSlippage =
    filtered.length > 0 ? filtered.reduce((s, t) => s + t.slippage, 0) / filtered.length : 0;

  return (
    <VictoriaPage>
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
            VICTORIA TRADE LOG
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
        <div style={{ display: "flex", gap: 24 }}>
          {[
            { l: "TOTAL TRADES", v: `${trades.length}`, c: T.white },
            { l: "WIN RATE", v: `${((wins / filtered.length) * 100).toFixed(1)}%`, c: T.green },
            {
              l: "TOTAL PNL",
              v: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(0)}`,
              c: totalPnl >= 0 ? T.green : T.red,
            },
            {
              l: "PROFIT FACTOR",
              v: isFinite(profitFactor) ? profitFactor.toFixed(2) : "∞",
              c: T.green,
            },
          ].map((s) => (
            <div key={s.l} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.08em" }}>{s.l}</div>
              <div
                style={{
                  fontSize: 14,
                  color: s.c,
                  fontWeight: "bold",
                  textShadow: s.c === T.green ? T.glow : s.c === T.red ? T.glowR : "none",
                }}
              >
                {s.v}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 260px", gap: 3, padding: 3 }}>
        {/* Main trade table */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {/* Cumulative P&L chart */}
          <Panel title="CUMULATIVE P&L">
            <ResponsiveContainer width="100%" height={100}>
              <ComposedChart data={cumPnl} margin={{ top: 4, right: 4, bottom: 4, left: 50 }}>
                <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
                <XAxis dataKey="i" tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }} />
                <YAxis
                  tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                  width={48}
                />
                <Tooltip content={<TermTip />} />
                <ReferenceLine y={0} stroke={T.dim} strokeDasharray="4 2" />
                <Bar dataKey="pnl" name="Trade PnL" radius={0}>
                  {cumPnl.map((d, i) => (
                    <Bar key={i} dataKey="pnl" fill={d.pnl >= 0 ? T.green : T.red} />
                  ))}
                </Bar>
                <Line
                  type="monotone"
                  dataKey="cum"
                  stroke={T.cyan}
                  strokeWidth={2}
                  dot={false}
                  name="Cumulative"
                />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>

          {/* P&L bar chart */}
          <Panel title="PER-TRADE P&L">
            <ResponsiveContainer width="100%" height={80}>
              <ComposedChart
                data={[...cumPnl].reverse()}
                margin={{ top: 2, right: 4, bottom: 2, left: 50 }}
              >
                <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
                <XAxis dataKey="i" tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }} />
                <YAxis
                  tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                  width={48}
                />
                <Tooltip content={<TermTip />} />
                <ReferenceLine y={0} stroke={T.dim} />
                <Bar dataKey="pnl" name="PnL" radius={0}>
                  {[...cumPnl].reverse().map((d, i) => (
                    <Bar key={i} dataKey="pnl" fill={d.pnl >= 0 ? T.green : T.red} />
                  ))}
                </Bar>
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>

          {/* Filters */}
          <div style={{ display: "flex", gap: 6, fontFamily: T.font, fontSize: 10 }}>
            <span style={{ color: T.dim }}>FILTER:</span>
            {(["ALL", "BTC/USDT", "ETH/USDT", "SOL/USDT"] as FilterSym[]).map((f) => (
              <button
                key={f}
                onClick={() => setSymFilter(f)}
                style={{
                  background: symFilter === f ? T.dim : T.black,
                  color: symFilter === f ? T.black : T.green,
                  border: `1px solid ${T.green}`,
                  fontFamily: T.font,
                  fontSize: 9,
                  padding: "2px 6px",
                  cursor: "pointer",
                }}
              >
                {f}
              </button>
            ))}
            <span style={{ color: T.dim, marginLeft: 8 }}>SIDE:</span>
            {(["ALL", "LONG", "SHORT"] as FilterSide[]).map((f) => (
              <button
                key={f}
                onClick={() => setSideFilter(f)}
                style={{
                  background: sideFilter === f ? T.dim : T.black,
                  color: sideFilter === f ? T.black : T.green,
                  border: `1px solid ${T.green}`,
                  fontFamily: T.font,
                  fontSize: 9,
                  padding: "2px 6px",
                  cursor: "pointer",
                }}
              >
                {f}
              </button>
            ))}
          </div>

          {/* Trade table */}
          <Panel title={`TRADE HISTORY — ${filtered.length} TRADES`}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 10,
                fontFamily: T.font,
              }}
            >
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.green}` }}>
                  {[
                    "TIMESTAMP",
                    "SYMBOL",
                    "SIDE",
                    "SIZE",
                    "ENTRY",
                    "EXIT",
                    "PNL",
                    "SLIPPAGE",
                    "DURATION",
                  ].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        color: T.dim,
                        padding: "3px 10px 3px 0",
                        fontSize: 9,
                        letterSpacing: "0.08em",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((t, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${T.dim}22` }}>
                    <td style={{ color: T.dim, padding: "4px 10px 4px 0", fontSize: 9 }}>
                      {t.ts}
                    </td>
                    <td style={{ color: T.white, paddingRight: 10, fontWeight: "bold" }}>
                      {t.sym}
                    </td>
                    <td
                      style={{
                        color: t.side === "LONG" ? T.green : T.amber,
                        paddingRight: 10,
                        fontWeight: "bold",
                        textShadow: t.side === "LONG" ? T.glow : T.glowA,
                      }}
                    >
                      {t.side === "LONG" ? "↑ " : "↓ "}
                      {t.side}
                    </td>
                    <td style={{ color: T.white, paddingRight: 10 }}>{t.size}</td>
                    <td style={{ color: T.dim, paddingRight: 10 }}>{t.entry.toLocaleString()}</td>
                    <td style={{ color: T.dim, paddingRight: 10 }}>{t.exit.toLocaleString()}</td>
                    <td
                      style={{
                        color: t.pnl >= 0 ? T.green : T.red,
                        fontWeight: "bold",
                        paddingRight: 10,
                        textShadow: t.pnl >= 0 ? T.glow : T.glowR,
                      }}
                    >
                      {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                    </td>
                    <td style={{ color: t.slippage > 0.018 ? T.amber : T.dim, paddingRight: 10 }}>
                      {(t.slippage * 100).toFixed(3)}%
                    </td>
                    <td style={{ color: T.dim }}>{t.duration}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        {/* Right: stats */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <Panel title="TRADE STATISTICS">
            {[
              ["TOTAL TRADES", `${trades.length}`, T.white],
              ["FILTERED", `${filtered.length}`, T.dim],
              ["WINS", `${wins}`, T.green],
              ["LOSSES", `${losses}`, T.red],
              [
                "WIN RATE",
                `${filtered.length > 0 ? ((wins / filtered.length) * 100).toFixed(1) : "0.0"}%`,
                T.green,
              ],
              ["AVG WIN", `+$${avgWin.toFixed(2)}`, T.green],
              ["AVG LOSS", `-$${avgLoss.toFixed(2)}`, T.red],
              ["PROFIT FACTOR", isFinite(profitFactor) ? profitFactor.toFixed(2) : "∞", T.green],
              [
                "TOTAL PNL",
                `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`,
                totalPnl >= 0 ? T.green : T.red,
              ],
              ["AVG SLIPPAGE", `${(avgSlippage * 100).toFixed(3)}%`, T.amber],
            ].map(([l, v, c]) => (
              <StatRow key={l} label={l} value={v} color={c} glow={c === T.green} />
            ))}
          </Panel>

          <Panel title="BY SYMBOL">
            {(["BTC/USDT", "ETH/USDT", "SOL/USDT"] as const).map((sym) => {
              const symTrades = trades.filter((t) => t.sym === sym);
              const symPnl = symTrades.reduce((s, t) => s + t.pnl, 0);
              const symWins = symTrades.filter((t) => t.pnl > 0).length;
              return (
                <div
                  key={sym}
                  style={{
                    marginBottom: 8,
                    paddingBottom: 6,
                    borderBottom: `1px solid ${T.dim}22`,
                  }}
                >
                  <div
                    style={{ fontSize: 11, color: T.white, fontWeight: "bold", marginBottom: 4 }}
                  >
                    {sym}
                  </div>
                  <StatRow label="TRADES" value={`${symTrades.length}`} color={T.white} />
                  <StatRow
                    label="WIN RATE"
                    value={`${symTrades.length > 0 ? ((symWins / symTrades.length) * 100).toFixed(0) : 0}%`}
                    color={T.green}
                  />
                  <StatRow
                    label="TOTAL PNL"
                    value={`${symPnl >= 0 ? "+" : ""}$${symPnl.toFixed(2)}`}
                    color={symPnl >= 0 ? T.green : T.red}
                    glow={symPnl >= 0}
                  />
                </div>
              );
            })}
          </Panel>

          <Panel title="SLIPPAGE ANALYSIS">
            <StatRow
              label="AVG SLIPPAGE"
              value={`${(avgSlippage * 100).toFixed(3)}%`}
              color={T.amber}
            />
            <StatRow
              label="MAX SLIPPAGE"
              value={`${(Math.max(...trades.map((t) => t.slippage)) * 100).toFixed(3)}%`}
              color={T.red}
            />
            <StatRow
              label="MIN SLIPPAGE"
              value={`${(Math.min(...trades.map((t) => t.slippage)) * 100).toFixed(3)}%`}
              color={T.green}
            />
            <div
              style={{
                fontSize: 9,
                color: T.dim,
                marginTop: 6,
                borderTop: `1px solid ${T.dim}`,
                paddingTop: 4,
              }}
            >
              &gt; COMM: 0.10% taker │ TARGET: &lt;0.015%
            </div>
          </Panel>

          <Panel title="RECENT PERFORMANCE">
            <div style={{ fontSize: 9, color: T.dim, marginBottom: 4 }}>LAST 5 TRADES</div>
            {trades.slice(0, 5).map((t, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 10,
                  marginBottom: 3,
                  paddingBottom: 3,
                  borderBottom: `1px solid ${T.dim}22`,
                }}
              >
                <span style={{ color: t.side === "LONG" ? T.green : T.amber }}>
                  {t.side === "LONG" ? "↑" : "↓"} {t.sym.split("/")[0]}
                </span>
                <span
                  style={{
                    color: t.pnl >= 0 ? T.green : T.red,
                    fontWeight: "bold",
                    textShadow: t.pnl >= 0 ? T.glow : T.glowR,
                  }}
                >
                  {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(0)}
                </span>
              </div>
            ))}
          </Panel>
        </div>
      </div>
    </VictoriaPage>
  );
}
