// VICTORIA SIGNALS — signal generators, conviction, Brier scores, regime view + drill-down
import { useEffect, useState } from "react";
import {
  ComposedChart,
  BarChart,
  Bar,
  Cell,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { ArrowLeft } from "lucide-react";
import * as mock from "../mocks/victoria";
import type { Signal } from "../mocks/victoria";
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

// Synthetic conviction history (30 data points)
function buildConvictionHistory(base: number, n = 30) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const drift = 0.04 * Math.sin(i / 5 + base * 20);
    const noise = 0.02 * Math.cos(i * 0.9 + base * 30);
    out.push({ t: i + 1, conviction: +Math.max(0, Math.min(1, base + drift + noise)).toFixed(3) });
  }
  return out;
}

function calcComposite(sigs: typeof mock.signals) {
  const score = sigs.reduce((s, sig) => s + sig.conviction * sig.weight, 0);
  const direction = score > 0.5 ? "LONG" : score < 0.35 ? "SHORT" : "FLAT";
  return { score, direction };
}

function CleanTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | string; color?: string }[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-2.5 shadow-lg text-xs">
      {label !== undefined && <p className="text-slate-500 mb-1">{label}</p>}
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color ?? "#10b981" }}>
          {p.name && `${p.name}: `}
          {typeof p.value === "number" ? p.value.toFixed(4) : p.value}
        </p>
      ))}
    </div>
  );
}

function Skel({ h = 12, w = "100%" }: { h?: number; w?: string | number }) {
  return (
    <div className="animate-pulse bg-slate-700/60 rounded" style={{ height: h, width: w }} />
  );
}

function convClass(c: number) {
  return c > 0.6 ? "text-emerald-400" : c > 0.4 ? "text-amber-400" : "text-red-400";
}
function brierClass(b: number) {
  return b < 0.25 ? "text-emerald-400" : b < 0.3 ? "text-amber-400" : "text-red-400";
}
function trendIcon(trend: string) {
  return trend === "up" ? "↑" : trend === "down" ? "↓" : "→";
}
function trendClass(trend: string) {
  return trend === "up" ? "text-emerald-400" : trend === "down" ? "text-red-400" : "text-amber-400";
}

// Signal card for main list
function SignalCard({
  sig,
  onClick,
}: {
  sig: Signal;
  onClick: () => void;
}) {
  const icHistory = buildICHistory(sig.avgIC, sig.halfLife);

  return (
    <div
      className="bg-slate-800 rounded-xl border border-slate-700 p-4 cursor-pointer hover:border-indigo-500/50 transition-colors"
      onClick={onClick}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider truncate">
          {sig.name}
        </h3>
        <span className="text-[10px] text-slate-600">▸ detail</span>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-slate-900 rounded-lg p-2.5 border border-slate-700">
          <p className="text-[9px] text-slate-500 mb-1">Current Value</p>
          <p className="text-lg font-bold text-slate-100">
            {sig.currentValue.toFixed(3)}{" "}
            <span className={`text-sm ${trendClass(sig.trend)}`}>{trendIcon(sig.trend)}</span>
          </p>
        </div>
        <div className="bg-slate-900 rounded-lg p-2.5 border border-slate-700">
          <p className="text-[9px] text-slate-500 mb-1">Conviction</p>
          <p className={`text-lg font-bold ${convClass(sig.conviction)}`}>
            {(sig.conviction * 100).toFixed(0)}%
          </p>
        </div>
      </div>

      <div className="space-y-1.5 text-xs mb-3">
        {[
          { l: "Avg IC", v: sig.avgIC.toFixed(4), cls: "text-blue-400" },
          { l: "Weight", v: `${(sig.weight * 100).toFixed(0)}%`, cls: "text-slate-300" },
          { l: "Half-life", v: `${sig.halfLife}d`, cls: "text-slate-300" },
          { l: "Brier", v: sig.brierScore.toFixed(3), cls: brierClass(sig.brierScore) },
        ].map(({ l, v, cls }) => (
          <div key={l} className="flex justify-between">
            <span className="text-slate-500">{l}</span>
            <span className={`font-mono ${cls}`}>{v}</span>
          </div>
        ))}
      </div>

      {/* Conviction bar */}
      <div className="mb-3">
        <div className="flex justify-between text-[9px] text-slate-500 mb-1">
          <span>Conviction</span>
          <span className={convClass(sig.conviction)}>{(sig.conviction * 100).toFixed(0)}%</span>
        </div>
        <div className="h-1.5 bg-slate-700 rounded-full">
          <div
            className={`h-1.5 rounded-full transition-all ${sig.conviction > 0.6 ? "bg-emerald-500" : sig.conviction > 0.4 ? "bg-amber-500" : "bg-red-500"}`}
            style={{ width: `${sig.conviction * 100}%` }}
          />
        </div>
      </div>

      {/* IC sparkline */}
      <p className="text-[9px] text-slate-500 mb-1">IC History (60d)</p>
      <div className="h-12">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={icHistory} margin={{ top: 0, right: 0, bottom: 0, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
            <XAxis dataKey="t" tick={false} />
            <YAxis tick={{ fontSize: 8, fill: "#64748b" }} width={20} />
            <Line type="monotone" dataKey="ic" stroke="#6366f1" strokeWidth={1} dot={false} name="IC" />
            <ReferenceLine y={0} stroke="#475569" strokeDasharray="2 2" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function VictoriaSignals() {
  const [signals, setSignals] = useState(mock.signals);
  const [regimes, setRegimes] = useState(mock.regimes);
  const [currentRegimeIdx, setCurrentRegimeIdx] = useState(mock.currentRegimeIdx);
  const [ablation, setAblation] = useState(mock.ablation);
  const [fundingData, setFundingData] = useState(mock.fundingData);
  const [D, setD] = useState(mock.backtestStats);
  const [fromMock, setFromMock] = useState(true);
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

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

  function openSignal(sig: Signal) {
    setDetailLoading(true);
    setSelectedSignal(sig);
    setTimeout(() => setDetailLoading(false), 360);
  }

  function backToList() {
    setSelectedSignal(null);
  }

  const { score: compositeScore, direction: compositeDirection } = calcComposite(signals);
  const compositeClass =
    compositeDirection === "LONG"
      ? "text-emerald-400"
      : compositeDirection === "SHORT"
        ? "text-red-400"
        : "text-amber-400";

  // ── Signal detail panel ──────────────────────────────────────────────
  if (selectedSignal !== null) {
    const sig = selectedSignal;
    const icHistory = buildICHistory(sig.avgIC, sig.halfLife, 60);
    const convHistory = buildConvictionHistory(sig.conviction, 30);

    return (
      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={backToList}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-100 bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg transition-colors"
            >
              <ArrowLeft size={13} />
              Back to Signals
            </button>
            <h2 className="text-sm font-semibold text-slate-300">Signal Detail</h2>
            {fromMock && (
              <span className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded">
                mock
              </span>
            )}
          </div>
          <div className="flex items-center gap-6">
            {[
              { l: "Signal", v: sig.name, cls: "text-slate-100 font-semibold text-sm" },
              {
                l: "Current Value",
                v: `${sig.currentValue.toFixed(3)} ${trendIcon(sig.trend)}`,
                cls: `text-sm font-semibold ${trendClass(sig.trend)}`,
              },
              {
                l: "Conviction",
                v: `${(sig.conviction * 100).toFixed(0)}%`,
                cls: `text-sm font-semibold ${convClass(sig.conviction)}`,
              },
              {
                l: "Brier Score",
                v: sig.brierScore.toFixed(3),
                cls: `text-sm font-semibold text-blue-400`,
              },
            ].map((s) => (
              <div key={s.l} className="text-right">
                <p className="text-[10px] text-slate-500 mb-0.5">{s.l}</p>
                <p className={s.cls}>{s.v}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-[1fr_240px] gap-4">
          {/* Left: charts */}
          <div className="space-y-4">
            {detailLoading ? (
              <>
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
                  <Skel h={14} w="40%" />
                  <Skel h={140} />
                </div>
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
                  <Skel h={14} w="40%" />
                  <Skel h={110} />
                </div>
              </>
            ) : (
              <>
                {/* IC trend */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                    IC Trend (60 Days)
                  </h3>
                  <p className="text-xs text-slate-600 mb-3">
                    Information Coefficient over rolling 60-day window. Positive IC = predictive.
                  </p>
                  <div className="h-36">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={icHistory} margin={{ top: 4, right: 12, bottom: 4, left: 44 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "#64748b" }} label={{ value: "days", position: "insideRight", fill: "#64748b", fontSize: 9, offset: 10 }} />
                        <YAxis tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={(v: number) => v.toFixed(3)} width={42} />
                        <Tooltip content={<CleanTooltip />} />
                        <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 2" />
                        <Line type="monotone" dataKey="ic" stroke="#6366f1" strokeWidth={1.5} dot={false} name="IC" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex gap-5 mt-3 pt-3 border-t border-slate-700 text-xs">
                    {[
                      { l: "Avg IC", v: (icHistory.reduce((s, d) => s + d.ic, 0) / icHistory.length).toFixed(4), cls: "text-blue-400" },
                      { l: "Max IC", v: Math.max(...icHistory.map((d) => d.ic)).toFixed(4), cls: "text-emerald-400" },
                      { l: "Min IC", v: Math.min(...icHistory.map((d) => d.ic)).toFixed(4), cls: "text-red-400" },
                      { l: "Half-life", v: `${sig.halfLife}d`, cls: "text-slate-300" },
                    ].map(({ l, v, cls }) => (
                      <div key={l}>
                        <span className="text-slate-500">{l}: </span>
                        <span className={`font-semibold font-mono ${cls}`}>{v}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Conviction history */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                    Conviction History (30 Cycles)
                  </h3>
                  <p className="text-xs text-slate-600 mb-3">
                    Rolling conviction score over recent pipeline cycles.
                  </p>
                  <div className="h-28">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={convHistory} margin={{ top: 4, right: 12, bottom: 4, left: 44 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="t" tick={{ fontSize: 9, fill: "#64748b" }} />
                        <YAxis domain={[0, 1]} tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} width={42} />
                        <Tooltip content={<CleanTooltip />} />
                        <ReferenceLine y={0.5} stroke="#475569" strokeDasharray="4 2" label={{ value: "50%", fill: "#64748b", fontSize: 9 }} />
                        <Line type="monotone" dataKey="conviction" stroke={sig.conviction > 0.6 ? "#10b981" : sig.conviction > 0.4 ? "#f59e0b" : "#ef4444"} strokeWidth={1.5} dot={false} name="Conviction" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Weight vs other signals */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                    Weight vs Other Signals
                  </h3>
                  <p className="text-xs text-slate-600 mb-3">IC-weighted allocation vs peer signals.</p>
                  <div className="h-28">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={signals.map((s) => ({ name: s.name.split(" ")[0], weight: s.weight, isSelf: s.name === sig.name }))}
                        layout="vertical"
                        margin={{ top: 2, right: 12, bottom: 2, left: 88 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: "#94a3b8" }} width={86} />
                        <Tooltip content={<CleanTooltip />} />
                        <Bar dataKey="weight" name="Weight" radius={3}>
                          {signals.map((s, i) => (
                            <Cell key={i} fill={s.name === sig.name ? "#6366f1" : "#334155"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Right: stats */}
          <div className="space-y-3">
            {/* Signal stats */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Signal Stats
              </h3>
              <div
                className={`text-center p-4 rounded-lg border mb-3 ${
                  sig.conviction > 0.6
                    ? "border-emerald-500/50 bg-emerald-500/10"
                    : sig.conviction > 0.4
                      ? "border-amber-500/50 bg-amber-500/10"
                      : "border-red-500/50 bg-red-500/10"
                }`}
              >
                <p className="text-xs text-slate-500 mb-1.5">Current Value</p>
                <p className={`text-3xl font-bold ${trendClass(sig.trend)}`}>
                  {sig.currentValue.toFixed(3)}
                </p>
                <p className={`text-xs mt-1 font-semibold ${trendClass(sig.trend)}`}>
                  {trendIcon(sig.trend)} {sig.trend.toUpperCase()}
                </p>
              </div>
              <div className="space-y-2 text-sm">
                {[
                  { l: "Avg IC", v: sig.avgIC.toFixed(4), cls: "text-blue-400" },
                  { l: "Weight", v: `${(sig.weight * 100).toFixed(0)}%`, cls: "text-slate-300" },
                  { l: "Half-life", v: `${sig.halfLife}d`, cls: "text-slate-300" },
                  { l: "Brier Score", v: sig.brierScore.toFixed(3), cls: brierClass(sig.brierScore) },
                  { l: "Conviction", v: `${(sig.conviction * 100).toFixed(0)}%`, cls: convClass(sig.conviction) },
                ].map(({ l, v, cls }) => (
                  <div key={l} className="flex justify-between">
                    <span className="text-slate-500">{l}</span>
                    <span className={`font-mono font-semibold ${cls}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quality assessment */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Quality Assessment
              </h3>
              <div className="space-y-2 text-sm">
                {[
                  { l: "IC Quality", v: sig.avgIC > 0.06 ? "STRONG" : sig.avgIC > 0.03 ? "MODERATE" : "WEAK", cls: sig.avgIC > 0.06 ? "text-emerald-400" : sig.avgIC > 0.03 ? "text-amber-400" : "text-red-400" },
                  { l: "Conviction", v: sig.conviction > 0.7 ? "HIGH" : sig.conviction > 0.5 ? "MODERATE" : "LOW", cls: convClass(sig.conviction) },
                  { l: "Brier Accuracy", v: sig.brierScore < 0.25 ? "ACCURATE" : sig.brierScore < 0.3 ? "FAIR" : "POOR", cls: brierClass(sig.brierScore) },
                  { l: "Weight Rank", v: `#${[...signals].sort((a, b) => b.weight - a.weight).findIndex((s) => s.name === sig.name) + 1} / ${signals.length}`, cls: "text-slate-300" },
                ].map(({ l, v, cls }) => (
                  <div key={l} className="flex justify-between">
                    <span className="text-slate-500">{l}</span>
                    <span className={`font-semibold ${cls}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Conviction + weight bars */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-4">
              {[
                { l: "Conviction Level", v: sig.conviction, cls: convClass(sig.conviction), barCls: sig.conviction > 0.6 ? "bg-emerald-500" : sig.conviction > 0.4 ? "bg-amber-500" : "bg-red-500", pct: sig.conviction * 100 },
                { l: "Portfolio Weight", v: sig.weight, cls: "text-indigo-400", barCls: "bg-indigo-500", pct: Math.min(100, sig.weight * 100 * 4) },
              ].map(({ l, v, cls, barCls, pct }) => (
                <div key={l}>
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-slate-500">{l}</span>
                    <span className={`font-mono font-semibold ${cls}`}>{(v * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full">
                    <div className={`h-2 rounded-full ${barCls}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Signal list (main view) ──────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { l: "Composite Signal", v: compositeDirection, cls: compositeClass },
          { l: "Composite Score", v: compositeScore.toFixed(3), cls: "text-slate-100" },
          { l: "Active Signals", v: `${signals.length}`, cls: "text-slate-100" },
          { l: "OOS Sharpe", v: D.sharpeOOS.toFixed(2), cls: D.sharpeOOS > 0.5 ? "text-emerald-400" : "text-amber-400" },
        ].map((s) => (
          <div key={s.l} className="bg-slate-800 rounded-xl border border-slate-700 px-4 py-3">
            <p className="text-xs text-slate-500 mb-1">{s.l}</p>
            <p className={`text-xl font-bold ${s.cls}`}>{s.v}</p>
            {fromMock && s.l === "Active Signals" && (
              <p className="text-[10px] text-amber-400 mt-0.5">mock data</p>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[1fr_1fr_280px] gap-4">
        {/* Signal cards col 1 */}
        <div className="space-y-3">
          {signals.slice(0, 3).map((sig) => (
            <SignalCard key={sig.name} sig={sig} onClick={() => openSignal(sig)} />
          ))}
        </div>

        {/* Signal cards col 2 */}
        <div className="space-y-3">
          {signals.slice(3).map((sig) => (
            <SignalCard key={sig.name} sig={sig} onClick={() => openSignal(sig)} />
          ))}

          {/* Signal combination */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Signal Combination
            </h3>
            <div
              className={`text-center p-3 rounded-lg border mb-3 ${
                compositeDirection === "LONG"
                  ? "border-emerald-500/50 bg-emerald-500/10"
                  : compositeDirection === "SHORT"
                    ? "border-red-500/50 bg-red-500/10"
                    : "border-amber-500/50 bg-amber-500/10"
              }`}
            >
              <p className="text-[10px] text-slate-500 mb-1">Combined Signal</p>
              <p className={`text-2xl font-bold ${compositeClass}`}>{compositeDirection}</p>
              <p className={`text-xs mt-0.5 font-mono ${compositeClass}`}>{compositeScore.toFixed(3)}</p>
            </div>
            <p className="text-[10px] text-slate-500 mb-2">Weight Distribution</p>
            <div className="space-y-2">
              {signals.map((sig) => (
                <div key={sig.name}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-400">{sig.name.split(" ")[0]}</span>
                    <span className="text-indigo-400 font-mono">{(sig.weight * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1 bg-slate-700 rounded-full">
                    <div className="h-1 bg-indigo-500 rounded-full" style={{ width: `${Math.min(100, sig.weight * 100 * 4)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Funding rate chart */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Funding Rate Signal
            </h3>
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={fundingData.slice(-30)} margin={{ top: 2, right: 4, bottom: 2, left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="t" tick={{ fontSize: 8, fill: "#64748b" }} interval={9} />
                  <YAxis tick={{ fontSize: 8, fill: "#64748b" }} tickFormatter={(v: number) => `${v.toFixed(2)}%`} width={30} />
                  <Tooltip content={<CleanTooltip />} />
                  <Line type="monotone" dataKey="funding" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="Funding%" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* RIGHT: regime + ablation */}
        <div className="space-y-3">
          {/* Regime performance */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Regime Performance
            </h3>
            <div className="space-y-2">
              {regimes.map((r, i) => (
                <div
                  key={r.name}
                  className={`rounded-lg border p-3 ${
                    i === currentRegimeIdx
                      ? "border-emerald-500/60 bg-emerald-500/10"
                      : "border-slate-700 bg-slate-900"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-xs font-semibold ${i === currentRegimeIdx ? "text-emerald-400" : "text-slate-400"}`}>
                      {r.name}{i === currentRegimeIdx ? " ◀" : ""}
                    </span>
                    <span className="text-sm font-bold text-slate-100">{r.sharpe.toFixed(2)}</span>
                  </div>
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between text-slate-500">
                      <span>Ann Return</span><span className="text-blue-400">{r.ret.toFixed(1)}%</span>
                    </div>
                    <div className="flex justify-between text-slate-500">
                      <span>Trades</span><span className="text-slate-300">{r.trades}</span>
                    </div>
                  </div>
                  <div className="mt-2 h-1 bg-slate-700 rounded-full">
                    <div
                      className={`h-1 rounded-full ${i === currentRegimeIdx ? "bg-emerald-500" : "bg-slate-500"}`}
                      style={{ width: `${r.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Signal ablation */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
              Signal Ablation (ΔSharpe)
            </h3>
            <p className="text-xs text-slate-500 mb-3">
              Full system: <span className="text-emerald-400 font-mono font-semibold">{D.sharpeAnn.toFixed(2)}</span>
            </p>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={ablation} layout="vertical" margin={{ top: 2, right: 24, bottom: 2, left: 90 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 9, fill: "#64748b" }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: "#94a3b8" }} width={88} />
                  <Tooltip content={<CleanTooltip />} />
                  <Bar dataKey="dSharpe" name="ΔSharpe" radius={3}>
                    {ablation.map((d, i) => (
                      <Cell key={i} fill={d.sig ? "#10b981" : "#475569"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Brier scores */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
              Brier Score Accuracy
            </h3>
            <p className="text-xs text-slate-600 mb-3">Lower = more accurate (0=perfect, 1=worst)</p>
            <div className="space-y-2.5">
              {signals.map((sig) => (
                <div key={sig.name}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-400">{sig.name.split(" ")[0]}</span>
                    <span className={`font-semibold font-mono ${brierClass(sig.brierScore)}`}>
                      {sig.brierScore.toFixed(3)}
                    </span>
                  </div>
                  <div className="h-1.5 bg-slate-700 rounded-full">
                    <div
                      className={`h-1.5 rounded-full ${brierClass(sig.brierScore).replace("text-", "bg-").replace("400", "500")}`}
                      style={{ width: `${sig.brierScore * 200}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
