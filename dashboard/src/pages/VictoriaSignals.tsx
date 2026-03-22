// VICTORIA SIGNALS — signal generators, conviction, Brier scores, regime view
import { useEffect, useState } from "react";
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from "recharts";
import { T, Panel, StatRow, TermTip, VictoriaPage, fmt } from "../components/victoria/Terminal";
import * as mock from "../mocks/victoria";
import { fetchSignals, fetchRiskMetrics } from "../api/victoria";

// Synthetic IC timeseries per signal (seeded, deterministic-ish via index)
function buildICHistory(baseIC: number, halfLife: number, n = 60) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const noise = 0.02 * Math.sin(i / halfLife + baseIC * 50) + 0.01 * Math.cos(i * 0.7);
    out.push({ t: i + 1, ic: +(baseIC + noise).toFixed(4) });
  }
  return out;
}

function calcComposite(sigs: typeof mock.signals) {
  const score = sigs.reduce((s, sig) => s + sig.conviction * sig.weight, 0);
  const direction = score > 0.5 ? "LONG" : score < 0.35 ? "SHORT" : "FLAT";
  const color = direction === "LONG" ? T.green : direction === "SHORT" ? T.red : T.amber;
  return { score, direction, color };
}

export default function VictoriaSignals() {
  const [signals, setSignals] = useState(mock.signals);
  const [regimes, setRegimes] = useState(mock.regimes);
  const [currentRegimeIdx, setCurrentRegimeIdx] = useState(mock.currentRegimeIdx);
  const [ablation, setAblation] = useState(mock.ablation);
  const [fundingData, setFundingData] = useState(mock.fundingData);
  const [D, setD] = useState(mock.backtestStats);
  const [fromMock, setFromMock] = useState(true);

  useEffect(() => {
    Promise.all([fetchSignals(), fetchRiskMetrics()]).then(([sigResult, riskResult]) => {
      if (!sigResult.fromMock) {
        setSignals(sigResult.signals);
        setD((prev) => ({ ...prev, sharpeOOS: sigResult.oosSharpe }));
      }
      if (!riskResult.fromMock) {
        setRegimes(riskResult.regimes);
        setCurrentRegimeIdx(riskResult.currentRegimeIdx);
        setAblation(riskResult.ablation);
        setFundingData(riskResult.fundingData);
      }
      setFromMock(sigResult.fromMock && riskResult.fromMock);
    });
  }, []);

  const {
    score: compositeScore,
    direction: compositeDirection,
    color: compositeColor,
  } = calcComposite(signals);

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
            VICTORIA SIGNALS
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
            { l: "COMPOSITE SIGNAL", v: compositeDirection, c: compositeColor },
            { l: "COMPOSITE SCORE", v: compositeScore.toFixed(3), c: T.green },
            { l: "ACTIVE SIGNALS", v: `${signals.length}`, c: T.white },
            { l: "OOS SHARPE", v: fmt(D.sharpeOOS), c: D.sharpeOOS > 0.5 ? T.green : T.amber },
          ].map((s) => (
            <div key={s.l} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.08em" }}>{s.l}</div>
              <div
                style={{
                  fontSize: 14,
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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 280px", gap: 3, padding: 3 }}>
        {/* Signal cards column 1 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {signals.slice(0, 3).map((sig) => {
            const icHistory = buildICHistory(sig.avgIC, sig.halfLife);
            const trendIcon = sig.trend === "up" ? "↑" : sig.trend === "down" ? "↓" : "→";
            const trendColor =
              sig.trend === "up" ? T.green : sig.trend === "down" ? T.red : T.amber;
            return (
              <Panel key={sig.name} title={sig.name}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 4,
                    marginBottom: 8,
                  }}
                >
                  <div style={{ border: `1px solid ${T.dim}`, padding: "4px 6px" }}>
                    <div style={{ fontSize: 9, color: T.dim }}>CURRENT VALUE</div>
                    <div style={{ fontSize: 20, color: sig.color, fontWeight: "bold" }}>
                      {sig.currentValue.toFixed(3)}{" "}
                      <span style={{ fontSize: 14, color: trendColor }}>{trendIcon}</span>
                    </div>
                  </div>
                  <div style={{ border: `1px solid ${T.dim}`, padding: "4px 6px" }}>
                    <div style={{ fontSize: 9, color: T.dim }}>CONVICTION</div>
                    <div
                      style={{
                        fontSize: 20,
                        color:
                          sig.conviction > 0.6 ? T.green : sig.conviction > 0.4 ? T.amber : T.red,
                        fontWeight: "bold",
                      }}
                    >
                      {(sig.conviction * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>

                <StatRow label="AVG IC" value={sig.avgIC.toFixed(4)} color={T.cyan} />
                <StatRow label="WEIGHT" value={`${(sig.weight * 100).toFixed(0)}%`} />
                <StatRow label="HALF-LIFE" value={`${sig.halfLife}d`} color={T.white} />
                <StatRow
                  label="BRIER SCORE"
                  value={sig.brierScore.toFixed(3)}
                  color={sig.brierScore < 0.25 ? T.green : sig.brierScore < 0.3 ? T.amber : T.red}
                />

                {/* Conviction bar */}
                <div style={{ marginTop: 6, marginBottom: 4 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 9,
                      color: T.dim,
                      marginBottom: 2,
                    }}
                  >
                    <span>CONVICTION</span>
                    <span style={{ color: sig.color }}>{(sig.conviction * 100).toFixed(0)}%</span>
                  </div>
                  <div
                    style={{ height: 5, background: `${T.dim}33`, border: `1px solid ${T.dim}` }}
                  >
                    <div
                      style={{
                        width: `${sig.conviction * 100}%`,
                        height: "100%",
                        background: sig.color,
                      }}
                    />
                  </div>
                </div>

                {/* IC history sparkline */}
                <div style={{ fontSize: 9, color: T.dim, marginBottom: 2 }}>IC HISTORY (60d)</div>
                <ResponsiveContainer width="100%" height={50}>
                  <ComposedChart
                    data={icHistory}
                    margin={{ top: 0, right: 0, bottom: 0, left: 20 }}
                  >
                    <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.2} />
                    <XAxis dataKey="t" tick={false} />
                    <YAxis tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }} width={22} />
                    <Tooltip content={<TermTip />} />
                    <Line
                      type="monotone"
                      dataKey="ic"
                      stroke={sig.color}
                      strokeWidth={1}
                      dot={false}
                      name="IC"
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </Panel>
            );
          })}
        </div>

        {/* Signal cards column 2 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {signals.slice(3).map((sig) => {
            const icHistory = buildICHistory(sig.avgIC, sig.halfLife);
            const trendIcon = sig.trend === "up" ? "↑" : sig.trend === "down" ? "↓" : "→";
            const trendColor =
              sig.trend === "up" ? T.green : sig.trend === "down" ? T.red : T.amber;
            return (
              <Panel key={sig.name} title={sig.name}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 4,
                    marginBottom: 8,
                  }}
                >
                  <div style={{ border: `1px solid ${T.dim}`, padding: "4px 6px" }}>
                    <div style={{ fontSize: 9, color: T.dim }}>CURRENT VALUE</div>
                    <div style={{ fontSize: 20, color: sig.color, fontWeight: "bold" }}>
                      {sig.currentValue.toFixed(3)}{" "}
                      <span style={{ fontSize: 14, color: trendColor }}>{trendIcon}</span>
                    </div>
                  </div>
                  <div style={{ border: `1px solid ${T.dim}`, padding: "4px 6px" }}>
                    <div style={{ fontSize: 9, color: T.dim }}>CONVICTION</div>
                    <div
                      style={{
                        fontSize: 20,
                        color:
                          sig.conviction > 0.6 ? T.green : sig.conviction > 0.4 ? T.amber : T.red,
                        fontWeight: "bold",
                      }}
                    >
                      {(sig.conviction * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <StatRow label="AVG IC" value={sig.avgIC.toFixed(4)} color={T.cyan} />
                <StatRow label="WEIGHT" value={`${(sig.weight * 100).toFixed(0)}%`} />
                <StatRow label="HALF-LIFE" value={`${sig.halfLife}d`} color={T.white} />
                <StatRow
                  label="BRIER SCORE"
                  value={sig.brierScore.toFixed(3)}
                  color={sig.brierScore < 0.25 ? T.green : sig.brierScore < 0.3 ? T.amber : T.red}
                />
                <div style={{ marginTop: 6, marginBottom: 4 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 9,
                      color: T.dim,
                      marginBottom: 2,
                    }}
                  >
                    <span>CONVICTION</span>
                    <span style={{ color: sig.color }}>{(sig.conviction * 100).toFixed(0)}%</span>
                  </div>
                  <div
                    style={{ height: 5, background: `${T.dim}33`, border: `1px solid ${T.dim}` }}
                  >
                    <div
                      style={{
                        width: `${sig.conviction * 100}%`,
                        height: "100%",
                        background: sig.color,
                      }}
                    />
                  </div>
                </div>
                <div style={{ fontSize: 9, color: T.dim, marginBottom: 2 }}>IC HISTORY (60d)</div>
                <ResponsiveContainer width="100%" height={50}>
                  <ComposedChart
                    data={icHistory}
                    margin={{ top: 0, right: 0, bottom: 0, left: 20 }}
                  >
                    <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.2} />
                    <XAxis dataKey="t" tick={false} />
                    <YAxis tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }} width={22} />
                    <Tooltip content={<TermTip />} />
                    <Line
                      type="monotone"
                      dataKey="ic"
                      stroke={sig.color}
                      strokeWidth={1}
                      dot={false}
                      name="IC"
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </Panel>
            );
          })}

          {/* Signal combination */}
          <Panel title="SIGNAL COMBINATION">
            <div
              style={{
                textAlign: "center",
                padding: 8,
                border: `1px solid ${compositeColor}`,
                marginBottom: 8,
              }}
            >
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: "0.15em" }}>
                COMBINED SIGNAL
              </div>
              <div
                style={{
                  fontSize: 24,
                  color: compositeColor,
                  fontWeight: "bold",
                  textShadow: compositeColor === T.green ? T.glow : T.glowA,
                }}
              >
                {compositeDirection}
              </div>
              <div style={{ fontSize: 12, color: compositeColor }}>
                {compositeScore.toFixed(3)}
              </div>
            </div>
            <div style={{ fontSize: 9, color: T.dim, marginBottom: 6 }}>WEIGHT DISTRIBUTION</div>
            {signals.map((sig) => (
              <div key={sig.name} style={{ marginBottom: 5 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    marginBottom: 2,
                  }}
                >
                  <span style={{ color: T.dim, fontSize: 9 }}>{sig.name.split(" ")[0]}</span>
                  <span style={{ color: sig.color }}>{(sig.weight * 100).toFixed(0)}%</span>
                </div>
                <div style={{ height: 3, background: `${T.dim}33` }}>
                  <div
                    style={{
                      width: `${sig.weight * 100 * 4}%`,
                      height: "100%",
                      background: sig.color,
                    }}
                  />
                </div>
              </div>
            ))}
          </Panel>

          {/* Funding data chart */}
          <Panel title="FUNDING RATE SIGNAL">
            <ResponsiveContainer width="100%" height={100}>
              <ComposedChart
                data={fundingData.slice(-30)}
                margin={{ top: 2, right: 4, bottom: 2, left: 28 }}
              >
                <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} />
                <XAxis
                  dataKey="t"
                  tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
                  interval={9}
                />
                <YAxis
                  tick={{ fill: T.dim, fontSize: 8, fontFamily: T.font }}
                  tickFormatter={(v: number) => `${v.toFixed(2)}%`}
                  width={30}
                />
                <Tooltip content={<TermTip />} />
                <Line
                  type="monotone"
                  dataKey="funding"
                  stroke={T.amber}
                  strokeWidth={1.5}
                  dot={false}
                  name="Funding%"
                />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>
        </div>

        {/* RIGHT: regime + ablation */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <Panel title="REGIME PERFORMANCE">
            {regimes.map((r, i) => (
              <div
                key={r.name}
                style={{
                  border: `1px solid ${i === currentRegimeIdx ? T.green : T.dim}`,
                  padding: "6px 8px",
                  marginBottom: 4,
                  background: i === currentRegimeIdx ? `${T.green}09` : T.black,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 3,
                  }}
                >
                  <span
                    style={{
                      fontSize: 9,
                      color: i === currentRegimeIdx ? T.green : T.dim,
                      letterSpacing: "0.1em",
                      textShadow: i === currentRegimeIdx ? T.glow : "none",
                    }}
                  >
                    {r.name}
                    {i === currentRegimeIdx ? " ◀" : ""}
                  </span>
                  <span style={{ fontSize: 14, color: T.green, fontWeight: "bold" }}>
                    {r.sharpe.toFixed(2)}
                  </span>
                </div>
                <StatRow label="ANN RETURN" value={`${r.ret.toFixed(1)}%`} color={T.cyan} />
                <StatRow label="TRADES" value={`${r.trades}`} color={T.white} />
                <StatRow label="FREQUENCY" value={`${r.pct}%`} color={T.dim} />
                <div style={{ marginTop: 4, height: 3, background: `${T.dim}44` }}>
                  <div
                    style={{
                      width: `${r.pct}%`,
                      height: "100%",
                      background: i === currentRegimeIdx ? T.green : T.dim,
                    }}
                  />
                </div>
              </div>
            ))}
          </Panel>

          <Panel title="SIGNAL ABLATION — ΔSharpe">
            <div style={{ fontSize: 10, color: T.dim, marginBottom: 4 }}>
              FULL SYSTEM:{" "}
              <span style={{ color: T.green, textShadow: T.glow }}>{fmt(D.sharpeAnn)}</span>
            </div>
            <ResponsiveContainer width="100%" height={170}>
              <BarChart
                data={ablation}
                layout="vertical"
                margin={{ top: 2, right: 30, bottom: 2, left: 90 }}
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
                  tick={{ fill: T.white, fontSize: 9, fontFamily: T.font }}
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

          <Panel title="BRIER SCORE ACCURACY">
            <div style={{ fontSize: 9, color: T.dim, marginBottom: 6 }}>
              Lower = more accurate (0=perfect, 1=worst)
            </div>
            {signals.map((sig) => (
              <div key={sig.name} style={{ marginBottom: 6 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    marginBottom: 2,
                  }}
                >
                  <span style={{ color: T.dim, fontSize: 9 }}>{sig.name.split(" ")[0]}</span>
                  <span
                    style={{
                      color:
                        sig.brierScore < 0.25 ? T.green : sig.brierScore < 0.3 ? T.amber : T.red,
                      fontWeight: "bold",
                    }}
                  >
                    {sig.brierScore.toFixed(3)}
                  </span>
                </div>
                <div style={{ height: 4, background: `${T.dim}33`, border: `1px solid ${T.dim}` }}>
                  <div
                    style={{
                      width: `${sig.brierScore * 200}%`,
                      height: "100%",
                      background:
                        sig.brierScore < 0.25 ? T.green : sig.brierScore < 0.3 ? T.amber : T.red,
                    }}
                  />
                </div>
              </div>
            ))}
          </Panel>
        </div>
      </div>
    </VictoriaPage>
  );
}
