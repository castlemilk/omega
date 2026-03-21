// VECTORA PORTFOLIO — live positions, P&L, allocation, risk exposure
import { useEffect, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import {
  T,
  Panel,
  StatRow,
  TermTip,
  VectoraPage,
  fmt,
  fmtUSDT,
} from "../components/vectora/Terminal";
import * as mock from "../mocks/vectora";
import { fetchPortfolio, fetchPositions } from "../api/vectora";
import type { BacktestStats } from "../mocks/vectora";

function buildDefaults() {
  const positions = mock.positions;
  const trades = mock.trades;
  const totalNotional = positions.reduce((s, p) => s + p.notional, 0);
  const totalUnrealised = positions.reduce((s, p) => s + p.upnl, 0);
  const totalRealised = trades.reduce((s, t) => s + t.pnl, 0);
  return {
    positions,
    allocation: mock.allocation,
    D: mock.backtestStats,
    totalNotional,
    totalUnrealised,
    totalRealised,
    totalPnl: totalUnrealised + totalRealised,
    fromMock: true,
  };
}

type PageState = ReturnType<typeof buildDefaults>;

export default function VectoraPortfolio() {
  const [state, setState] = useState<PageState>(buildDefaults);

  useEffect(() => {
    Promise.all([fetchPortfolio(), fetchPositions()]).then(([portfolio, posResult]) => {
      if (!portfolio.fromMock || !posResult.fromMock) {
        const positions = posResult.positions;
        const totalNotional = positions.reduce((s, p) => s + p.notional, 0);
        const totalUnrealised = positions.reduce((s, p) => s + p.upnl, 0);
        const totalRealised = portfolio.realisedPnl;
        setState({
          positions,
          allocation: portfolio.allocation,
          D: {
            sharpeAnn: portfolio.sharpe,
            sortinoAnn: mock.backtestStats.sortinoAnn,
            maxDDpct: mock.backtestStats.maxDDpct,
            calmar: mock.backtestStats.calmar,
            sharpeIS: mock.backtestStats.sharpeIS,
            sharpeOOS: mock.backtestStats.sharpeOOS,
            VaR: mock.backtestStats.VaR,
            CVaR: mock.backtestStats.CVaR,
            meanR: mock.backtestStats.meanR,
            stdR: mock.backtestStats.stdR,
            annReturn: portfolio.annReturn,
            totalReturn: portfolio.totalReturn,
            portfolioValue: portfolio.portfolioValue,
            maxDDDuration: mock.backtestStats.maxDDDuration,
            winRate: portfolio.winRate,
            profitFactor: portfolio.profitFactor,
          } as BacktestStats,
          totalNotional,
          totalUnrealised,
          totalRealised,
          totalPnl: totalUnrealised + totalRealised,
          fromMock: portfolio.fromMock && posResult.fromMock,
        });
      }
    });
  }, []);

  const {
    positions,
    allocation,
    D,
    totalNotional,
    totalUnrealised,
    totalRealised,
    totalPnl,
    fromMock,
  } = state;

  return (
    <VectoraPage>
      {/* Page header */}
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
            VECTORA PORTFOLIO
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
            { l: "PORTFOLIO VALUE", v: fmtUSDT(D.portfolioValue), c: T.green },
            { l: "UNREALISED PNL", v: `+${fmtUSDT(totalUnrealised)}`, c: T.green },
            { l: "REALISED PNL", v: `+${fmtUSDT(totalRealised)}`, c: T.green },
            { l: "TOTAL PNL", v: `+${fmtUSDT(totalPnl)}`, c: T.green },
          ].map((s) => (
            <div key={s.l} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.08em" }}>{s.l}</div>
              <div style={{ fontSize: 14, color: s.c, fontWeight: "bold", textShadow: T.glow }}>
                {s.v}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 3, padding: 3 }}>
        {/* LEFT: positions table + allocation */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {/* Live positions */}
          <Panel title="LIVE POSITIONS">
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 11,
                fontFamily: T.font,
              }}
            >
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.green}` }}>
                  {[
                    "SYMBOL",
                    "SIDE",
                    "SIZE",
                    "ENTRY",
                    "MARK",
                    "NOTIONAL",
                    "UNREAL PNL",
                    "PCT",
                    "LEVERAGE",
                    "VAR 95%",
                  ].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        color: T.dim,
                        padding: "2px 10px 2px 0",
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
                {positions.map((pos) => (
                  <tr key={pos.sym} style={{ borderBottom: `1px solid ${T.dim}22` }}>
                    <td style={{ color: T.white, padding: "5px 10px 5px 0", fontWeight: "bold" }}>
                      {pos.sym}
                    </td>
                    <td
                      style={{
                        color: pos.side === "LONG" ? T.green : T.amber,
                        fontWeight: "bold",
                        paddingRight: 10,
                        textShadow: pos.side === "LONG" ? T.glow : T.glowA,
                      }}
                    >
                      {pos.side}
                    </td>
                    <td style={{ color: T.white, paddingRight: 10 }}>{pos.size}</td>
                    <td style={{ color: T.dim, paddingRight: 10 }}>
                      {pos.entry.toLocaleString()}
                    </td>
                    <td style={{ color: T.white, paddingRight: 10 }}>
                      {pos.mark.toLocaleString()}
                    </td>
                    <td style={{ color: T.cyan, paddingRight: 10 }}>
                      ${pos.notional.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                    </td>
                    <td
                      style={{
                        color: T.green,
                        fontWeight: "bold",
                        textShadow: T.glow,
                        paddingRight: 10,
                      }}
                    >
                      +${pos.upnl.toFixed(2)}
                    </td>
                    <td style={{ color: T.green, paddingRight: 10 }}>+{pos.pct.toFixed(2)}%</td>
                    <td style={{ color: pos.leverage > 1.5 ? T.amber : T.dim, paddingRight: 10 }}>
                      {pos.leverage.toFixed(1)}x
                    </td>
                    <td style={{ color: T.amber }}>{pos.var95.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Summary row */}
            <div
              style={{
                marginTop: 8,
                paddingTop: 6,
                borderTop: `1px solid ${T.dim}`,
                display: "flex",
                gap: 20,
                fontSize: 11,
              }}
            >
              <div>
                <span style={{ color: T.dim }}>TOTAL NOTIONAL: </span>
                <span style={{ color: T.cyan, fontWeight: "bold" }}>
                  ${totalNotional.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </span>
              </div>
              <div>
                <span style={{ color: T.dim }}>TOTAL UNREALISED: </span>
                <span style={{ color: T.green, fontWeight: "bold", textShadow: T.glow }}>
                  +${totalUnrealised.toFixed(2)}
                </span>
              </div>
              <div>
                <span style={{ color: T.dim }}>POSITIONS: </span>
                <span style={{ color: T.white }}>{positions.length}</span>
              </div>
            </div>
          </Panel>

          {/* Allocation pie */}
          <Panel title="PORTFOLIO ALLOCATION">
            <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
              <div style={{ width: 200, height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={allocation}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      strokeWidth={0}
                    >
                      {allocation.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip content={<TermTip />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div style={{ flex: 1 }}>
                {allocation.map((a) => {
                  const total = allocation.reduce((s, x) => s + x.value, 0);
                  const pct = ((a.value / total) * 100).toFixed(1);
                  return (
                    <div
                      key={a.name}
                      style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}
                    >
                      <div style={{ width: 10, height: 10, background: a.color, flexShrink: 0 }} />
                      <span style={{ color: T.white, fontSize: 11, flex: 1 }}>{a.name}</span>
                      <span style={{ color: T.cyan, fontSize: 11 }}>
                        ${a.value.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                      </span>
                      <span
                        style={{ color: T.dim, fontSize: 11, minWidth: 40, textAlign: "right" }}
                      >
                        {pct}%
                      </span>
                    </div>
                  );
                })}
                <div style={{ marginTop: 8, paddingTop: 6, borderTop: `1px solid ${T.dim}` }}>
                  <StatRow
                    label="TOTAL AUM"
                    value={fmtUSDT(allocation.reduce((s, a) => s + a.value, 0))}
                    glow
                  />
                  <StatRow
                    label="DEPLOYED"
                    value={`${((totalNotional / D.portfolioValue) * 100).toFixed(1)}%`}
                    color={T.amber}
                  />
                  <StatRow
                    label="CASH"
                    value={fmtUSDT(allocation.find((a) => a.name === "USDT Cash")?.value ?? 0)}
                    color={T.dim}
                  />
                </div>
              </div>
            </div>
          </Panel>
        </div>

        {/* RIGHT: risk metrics */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <Panel title="P&L SUMMARY">
            {[
              ["UNREALISED PNL", `+${fmtUSDT(totalUnrealised)}`, T.green, true],
              ["REALISED PNL", `+${fmtUSDT(totalRealised)}`, T.green, true],
              ["TOTAL PNL", `+${fmtUSDT(totalPnl)}`, T.green, true],
              ["TOTAL RETURN", `+${(D.totalReturn * 100).toFixed(1)}%`, T.green, true],
              ["ANN RETURN", `+${(D.annReturn * 100).toFixed(1)}%`, T.green, false],
              ["WIN RATE", `${(D.winRate * 100).toFixed(1)}%`, T.green, false],
              ["PROFIT FACTOR", fmt(D.profitFactor), T.green, false],
            ].map(([l, v, c, g]) => (
              <StatRow
                key={l as string}
                label={l as string}
                value={v as string}
                color={c as string}
                glow={g as boolean}
              />
            ))}
          </Panel>

          <Panel title="RISK EXPOSURE">
            {[
              ["MAX DRAWDOWN", `${(D.maxDDpct * 100).toFixed(1)}%`, T.red],
              ["VAR 95% DAILY", `${D.VaR.toFixed(2)}%`, T.amber],
              ["CVAR 95% DAILY", `${D.CVaR.toFixed(2)}%`, T.red],
              ["SORTINO RATIO", fmt(D.sortinoAnn), T.green],
              ["CALMAR RATIO", fmt(D.calmar), T.green],
              ["SHARPE RATIO", fmt(D.sharpeAnn), T.green],
              ["ANN VOLATILITY", `${(D.stdR * Math.sqrt(252) * 100).toFixed(1)}%`, T.white],
            ].map(([l, v, c]) => (
              <StatRow key={l} label={l} value={v} color={c} glow={c === T.green} />
            ))}
          </Panel>

          <Panel title="ASSET RISK">
            {positions.map((pos) => (
              <div
                key={pos.sym}
                style={{ marginBottom: 8, paddingBottom: 6, borderBottom: `1px solid ${T.dim}22` }}
              >
                <div style={{ fontSize: 10, color: T.white, marginBottom: 4, fontWeight: "bold" }}>
                  {pos.sym}
                </div>
                <StatRow label="VAR 95%" value={`${pos.var95.toFixed(2)}%`} color={T.amber} />
                <StatRow
                  label="NOTIONAL"
                  value={`$${pos.notional.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
                  color={T.cyan}
                />
                <StatRow
                  label="LEVERAGE"
                  value={`${pos.leverage.toFixed(1)}x`}
                  color={pos.leverage > 1.5 ? T.amber : T.dim}
                />
              </div>
            ))}
          </Panel>

          <Panel title="POSITION SIZING">
            {positions.map((pos) => {
              const alloc = (pos.notional / D.portfolioValue) * 100;
              return (
                <div key={pos.sym} style={{ marginBottom: 6 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 10,
                      marginBottom: 2,
                    }}
                  >
                    <span style={{ color: T.white }}>{pos.sym}</span>
                    <span style={{ color: T.cyan }}>{alloc.toFixed(1)}%</span>
                  </div>
                  <div
                    style={{ height: 4, background: `${T.dim}33`, border: `1px solid ${T.dim}` }}
                  >
                    <div
                      style={{
                        width: `${Math.min(alloc * 4, 100)}%`,
                        height: "100%",
                        background: pos.side === "LONG" ? T.green : T.amber,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </Panel>
        </div>
      </div>
    </VectoraPage>
  );
}
