// VICTORIA TRADES — full trade history, entry/exit, slippage, P&L with drill-down
import { useEffect, useRef, useState } from "react";
import {
  BarChart,
  Bar,
  Cell,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Line,
} from "recharts";
import { ArrowLeft } from "lucide-react";
import * as mock from "../mocks/victoria";
import type { Trade } from "../mocks/victoria";
import { fetchTrades } from "../api/victoria";

type FilterSym = "ALL" | "BTC/USDT" | "ETH/USDT" | "SOL/USDT";
type FilterSide = "ALL" | "LONG" | "SHORT";

const SIGNAL_NAMES = ["ORDERFLOW", "CROSS-ASSET", "MICRO", "SENTIMENT", "MOMENTUM"];

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

// Deterministic signal snapshot at trade entry (seeded by trade index)
function buildSignalSnapshot(trade: Trade, idx: number) {
  return SIGNAL_NAMES.map((name, i) => {
    const base = trade.pnl > 0 ? 0.35 : -0.25;
    const noise = Math.sin(idx * 1.7 + i * 2.3) * 0.28;
    const raw = trade.side === "LONG" ? base + noise : -(base + noise);
    const value = +Math.max(-1, Math.min(1, raw)).toFixed(3);
    return { name, value };
  });
}

// Shared clean tooltip
function CleanTooltip({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | string; color?: string }[];
  label?: string | number;
  formatter?: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-2.5 shadow-lg text-xs">
      {label !== undefined && <p className="text-slate-500 mb-1.5">{label}</p>}
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color ?? "#10b981" }}>
          {p.name && `${p.name}: `}
          {typeof p.value === "number" && formatter
            ? formatter(p.value)
            : typeof p.value === "number"
              ? p.value.toFixed(4)
              : p.value}
        </p>
      ))}
    </div>
  );
}

// Skeleton pulse block for detail loading
function Skel({ h = 12, w = "100%" }: { h?: number; w?: string | number }) {
  return (
    <div
      className="animate-pulse bg-slate-700/60 rounded"
      style={{ height: h, width: w }}
    />
  );
}

export default function VictoriaTrades() {
  const [trades, setTrades] = useState<Trade[]>(mock.trades);
  const [fromMock, setFromMock] = useState(true);
  const [symFilter, setSymFilter] = useState<FilterSym>("ALL");
  const [sideFilter, setSideFilter] = useState<FilterSide>("ALL");
  const [selectedTrade, setSelectedTrade] = useState<{ trade: Trade; idx: number } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const tableScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchTrades().then((result) => {
      if (!result.fromMock) setTrades(result.trades);
      setFromMock(result.fromMock);
    });
  }, []);

  // Preserve scroll position across detail view
  useEffect(() => {
    const el = tableScrollRef.current;
    if (!el) return;
    const saved = sessionStorage.getItem("victoria-trades-scroll");
    if (saved && !selectedTrade) el.scrollTop = parseInt(saved, 10);
    return () => {
      if (el) sessionStorage.setItem("victoria-trades-scroll", String(el.scrollTop));
    };
  }, [selectedTrade]);

  function openDetail(trade: Trade, idx: number) {
    if (tableScrollRef.current) {
      sessionStorage.setItem("victoria-trades-scroll", String(tableScrollRef.current.scrollTop));
    }
    setDetailLoading(true);
    setSelectedTrade({ trade, idx });
    setTimeout(() => setDetailLoading(false), 380);
  }

  function backToList() {
    setSelectedTrade(null);
    requestAnimationFrame(() => {
      const el = tableScrollRef.current;
      if (!el) return;
      const saved = sessionStorage.getItem("victoria-trades-scroll");
      if (saved) el.scrollTop = parseInt(saved, 10);
    });
  }

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

  // ── Trade detail panel ────────────────────────────────────────────────
  if (selectedTrade !== null) {
    const { trade: t, idx } = selectedTrade;
    const snapshot = buildSignalSnapshot(t, idx);
    const isWin = t.pnl >= 0;
    const pnlCls = isWin ? "text-emerald-400" : "text-red-400";
    const sideCls = t.side === "LONG" ? "text-emerald-400" : "text-amber-400";

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
              Back to Trades
            </button>
            <h2 className="text-sm font-semibold text-slate-300">Trade Detail</h2>
            {fromMock && (
              <span className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded">
                mock
              </span>
            )}
          </div>
          <div className="flex items-center gap-6">
            {[
              { l: "Symbol", v: t.sym, cls: "text-slate-100 font-semibold" },
              { l: "Side", v: t.side, cls: `font-semibold ${sideCls}` },
              { l: "P&L", v: `${isWin ? "+" : ""}$${t.pnl.toFixed(2)}`, cls: `font-bold ${pnlCls}` },
              { l: "Timestamp", v: t.ts, cls: "text-slate-400" },
            ].map((s) => (
              <div key={s.l} className="text-right">
                <p className="text-[10px] text-slate-500 mb-0.5">{s.l}</p>
                <p className={`text-sm ${s.cls}`}>{s.v}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-[1fr_240px] gap-4">
          {/* Left column */}
          <div className="space-y-4">
            {detailLoading ? (
              <>
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
                  <Skel h={14} w="40%" />
                  <Skel h={140} />
                  <Skel h={10} w="60%" />
                </div>
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
                  <Skel h={14} w="40%" />
                  {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="flex justify-between">
                      <Skel h={10} w="35%" />
                      <Skel h={10} w="25%" />
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                {/* Signal snapshot */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                    Signal Snapshot at Entry
                  </h3>
                  <p className="text-xs text-slate-600 mb-3">
                    Signal values driving this trade decision. Positive = bullish, negative = bearish.
                  </p>
                  <div className="h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={snapshot}
                        layout="vertical"
                        margin={{ top: 4, right: 16, bottom: 4, left: 90 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                        <XAxis
                          type="number"
                          domain={[-1, 1]}
                          tick={{ fontSize: 10, fill: "#64748b" }}
                          tickFormatter={(v: number) => v.toFixed(1)}
                        />
                        <YAxis
                          dataKey="name"
                          type="category"
                          tick={{ fontSize: 10, fill: "#94a3b8" }}
                          width={86}
                        />
                        <Tooltip
                          content={
                            <CleanTooltip formatter={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(3)}`} />
                          }
                        />
                        <ReferenceLine x={0} stroke="#475569" />
                        <Bar dataKey="value" name="Signal" radius={3}>
                          {snapshot.map((d, i) => (
                            <Cell key={i} fill={d.value >= 0.05 ? "#10b981" : d.value <= -0.05 ? "#ef4444" : "#f59e0b"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  {/* Composite direction */}
                  <div className="mt-3 pt-3 border-t border-slate-700 flex items-center justify-between">
                    <span className="text-xs text-slate-500">Composite Direction</span>
                    <span className={`text-sm font-semibold ${sideCls}`}>
                      {t.side === "LONG" ? "↑ LONG" : "↓ SHORT"}
                    </span>
                    <span className="text-xs text-slate-500">
                      avg{" "}
                      <span className="text-blue-400 font-mono">
                        {(snapshot.reduce((s, d) => s + d.value, 0) / snapshot.length).toFixed(3)}
                      </span>
                    </span>
                  </div>
                </div>

                {/* Execution breakdown */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                    Execution Breakdown
                  </h3>
                  <div className="grid grid-cols-2 gap-3 mb-4">
                    {[
                      { l: "Entry Price", v: t.entry.toLocaleString() },
                      { l: "Exit Price", v: t.exit.toLocaleString() },
                      {
                        l: "Price Move",
                        v: `${t.side === "LONG" ? "+" : "-"}${Math.abs(t.exit - t.entry).toLocaleString()}`,
                        cls: pnlCls,
                      },
                      { l: "Position Size", v: t.size.toString(), cls: "text-blue-400" },
                    ].map(({ l, v, cls }) => (
                      <div key={l} className="bg-slate-900 rounded-lg p-3 border border-slate-700">
                        <p className="text-[10px] text-slate-500 mb-1">{l}</p>
                        <p className={`text-base font-bold ${cls ?? "text-slate-100"}`}>{v}</p>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2 text-sm">
                    {[
                      {
                        l: "Slippage",
                        v: `${(t.slippage * 100).toFixed(3)}%`,
                        cls: t.slippage > 0.018 ? "text-amber-400" : "text-emerald-400",
                      },
                      { l: "Duration", v: t.duration, cls: "text-slate-300" },
                      {
                        l: "Slippage Cost",
                        v: `$${(t.size * t.entry * t.slippage).toFixed(2)}`,
                        cls: "text-amber-400",
                      },
                      {
                        l: "Net P&L",
                        v: `${isWin ? "+" : ""}$${t.pnl.toFixed(2)}`,
                        cls: pnlCls,
                      },
                    ].map(({ l, v, cls }) => (
                      <div key={l} className="flex items-center justify-between">
                        <span className="text-slate-500">{l}</span>
                        <span className={`font-semibold font-mono ${cls}`}>{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Right column */}
          <div className="space-y-4">
            {/* Trade outcome */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Trade Outcome
              </h3>
              <div
                className={`text-center p-4 rounded-lg border mb-3 ${
                  isWin ? "border-emerald-500/50 bg-emerald-500/10" : "border-red-500/50 bg-red-500/10"
                }`}
              >
                <p className="text-xs text-slate-500 mb-1.5">Realized P&L</p>
                <p className={`text-3xl font-bold ${pnlCls}`}>
                  {isWin ? "+" : ""}${t.pnl.toFixed(2)}
                </p>
                <p className={`text-xs mt-1.5 font-semibold ${pnlCls}`}>
                  {isWin ? "WIN" : "LOSS"}
                </p>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">Return %</span>
                <span className={`font-semibold font-mono ${pnlCls}`}>
                  {(((t.exit - t.entry) / t.entry) * (t.side === "LONG" ? 1 : -1) * 100).toFixed(2)}%
                </span>
              </div>
            </div>

            {/* Signal legend */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Signal Legend
              </h3>
              <div className="space-y-2">
                {SIGNAL_NAMES.map((name, i) => {
                  const d = snapshot[i];
                  const valCls =
                    d.value >= 0.05
                      ? "text-emerald-400"
                      : d.value <= -0.05
                        ? "text-red-400"
                        : "text-amber-400";
                  return (
                    <div key={name} className="flex items-center justify-between py-1 border-b border-slate-700/50 last:border-0">
                      <span className="text-xs text-slate-400">{name}</span>
                      <span className={`text-xs font-semibold font-mono ${valCls}`}>
                        {d.value >= 0 ? "+" : ""}
                        {d.value.toFixed(3)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Trade metadata */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Metadata
              </h3>
              <div className="space-y-2 text-sm">
                {[
                  { l: "Symbol", v: t.sym, cls: "text-slate-100 font-semibold" },
                  { l: "Direction", v: t.side, cls: sideCls + " font-semibold" },
                  { l: "Timestamp", v: t.ts, cls: "text-slate-400" },
                  { l: "Trade #", v: `#${idx + 1}`, cls: "text-slate-500" },
                ].map(({ l, v, cls }) => (
                  <div key={l} className="flex items-center justify-between">
                    <span className="text-slate-500">{l}</span>
                    <span className={cls}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Main trade list ──────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { l: "Total Trades", v: `${trades.length}`, cls: "text-slate-100" },
          {
            l: "Win Rate",
            v: filtered.length > 0 ? `${((wins / filtered.length) * 100).toFixed(1)}%` : "—",
            cls: "text-emerald-400",
          },
          {
            l: "Total P&L",
            v: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(0)}`,
            cls: totalPnl >= 0 ? "text-emerald-400" : "text-red-400",
          },
          {
            l: "Profit Factor",
            v: isFinite(profitFactor) ? profitFactor.toFixed(2) : "∞",
            cls: "text-slate-100",
          },
        ].map((s) => (
          <div key={s.l} className="bg-slate-800 rounded-xl border border-slate-700 px-4 py-3">
            <p className="text-xs text-slate-500 mb-1">{s.l}</p>
            <p className={`text-xl font-bold ${s.cls}`}>{s.v}</p>
            {fromMock && s.l === "Total Trades" && (
              <p className="text-[10px] text-amber-400 mt-0.5">mock data</p>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[1fr_240px] gap-4">
        {/* Left: charts + table */}
        <div className="space-y-4">
          {/* Cumulative P&L chart */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Cumulative P&L
            </h3>
            <div className="h-28">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={cumPnl} margin={{ top: 4, right: 4, bottom: 4, left: 44 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="i" tick={{ fontSize: 9, fill: "#64748b" }} />
                  <YAxis tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={(v: number) => `$${v.toFixed(0)}`} width={42} />
                  <Tooltip
                    content={<CleanTooltip formatter={(v) => `$${v.toFixed(2)}`} />}
                  />
                  <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 2" />
                  <Bar dataKey="pnl" name="Trade P&L" radius={1}>
                    {cumPnl.map((d, i) => (
                      <Cell key={i} fill={d.pnl >= 0 ? "#10b981" : "#ef4444"} />
                    ))}
                  </Bar>
                  <Line type="monotone" dataKey="cum" stroke="#6366f1" strokeWidth={2} dot={false} name="Cumulative" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-500">Symbol:</span>
              {(["ALL", "BTC/USDT", "ETH/USDT", "SOL/USDT"] as FilterSym[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setSymFilter(f)}
                  className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                    symFilter === f
                      ? "bg-indigo-600 border-indigo-500 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-500">Side:</span>
              {(["ALL", "LONG", "SHORT"] as FilterSide[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setSideFilter(f)}
                  className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                    sideFilter === f
                      ? "bg-indigo-600 border-indigo-500 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          {/* Trade table */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden" ref={tableScrollRef}>
            <div className="p-3 border-b border-slate-700 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Trade History — {filtered.length} trades · click row for detail
            </div>
            <div className="overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-800 z-10">
                  <tr className="border-b border-slate-700">
                    {["Timestamp", "Symbol", "Side", "Size", "Entry", "Exit", "P&L", "Slippage", "Duration"].map((h) => (
                      <th key={h} className="text-left px-3 py-2 text-xs font-semibold text-slate-500 whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/50">
                  {filtered.map((t, i) => (
                    <tr
                      key={i}
                      onClick={() => openDetail(t, i)}
                      className="hover:bg-slate-700/40 cursor-pointer transition-colors"
                    >
                      <td className="px-3 py-2 text-slate-500 text-xs font-mono whitespace-nowrap">{t.ts}</td>
                      <td className="px-3 py-2 text-slate-200 font-semibold text-xs">{t.sym}</td>
                      <td className={`px-3 py-2 font-semibold text-xs ${t.side === "LONG" ? "text-emerald-400" : "text-amber-400"}`}>
                        {t.side === "LONG" ? "↑" : "↓"} {t.side}
                      </td>
                      <td className="px-3 py-2 text-slate-300 text-xs">{t.size}</td>
                      <td className="px-3 py-2 text-slate-400 text-xs font-mono">{t.entry.toLocaleString()}</td>
                      <td className="px-3 py-2 text-slate-400 text-xs font-mono">{t.exit.toLocaleString()}</td>
                      <td className={`px-3 py-2 font-semibold text-xs font-mono ${t.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                      </td>
                      <td className={`px-3 py-2 text-xs font-mono ${t.slippage > 0.018 ? "text-amber-400" : "text-slate-500"}`}>
                        {(t.slippage * 100).toFixed(3)}%
                      </td>
                      <td className="px-3 py-2 text-slate-500 text-xs">{t.duration}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right: stats sidebar */}
        <div className="space-y-3">
          {/* Trade statistics */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Statistics</h3>
            <div className="space-y-2 text-sm">
              {[
                { l: "Total Trades", v: `${trades.length}`, cls: "text-slate-300" },
                { l: "Filtered", v: `${filtered.length}`, cls: "text-slate-500" },
                { l: "Wins", v: `${wins}`, cls: "text-emerald-400" },
                { l: "Losses", v: `${losses}`, cls: "text-red-400" },
                { l: "Win Rate", v: `${filtered.length > 0 ? ((wins / filtered.length) * 100).toFixed(1) : "0.0"}%`, cls: "text-emerald-400" },
                { l: "Avg Win", v: `+$${avgWin.toFixed(2)}`, cls: "text-emerald-400" },
                { l: "Avg Loss", v: `-$${avgLoss.toFixed(2)}`, cls: "text-red-400" },
                { l: "Profit Factor", v: isFinite(profitFactor) ? profitFactor.toFixed(2) : "∞", cls: "text-slate-100 font-semibold" },
                { l: "Total P&L", v: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`, cls: totalPnl >= 0 ? "text-emerald-400 font-semibold" : "text-red-400 font-semibold" },
                { l: "Avg Slippage", v: `${(avgSlippage * 100).toFixed(3)}%`, cls: "text-amber-400" },
              ].map(({ l, v, cls }) => (
                <div key={l} className="flex items-center justify-between">
                  <span className="text-slate-500">{l}</span>
                  <span className={`font-mono ${cls}`}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* By symbol */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">By Symbol</h3>
            <div className="space-y-3">
              {(["BTC/USDT", "ETH/USDT", "SOL/USDT"] as const).map((sym) => {
                const st = trades.filter((t) => t.sym === sym);
                const sp = st.reduce((s, t) => s + t.pnl, 0);
                const sw = st.filter((t) => t.pnl > 0).length;
                return (
                  <div key={sym} className="border-b border-slate-700/50 pb-3 last:border-0 last:pb-0">
                    <p className="text-xs font-semibold text-slate-300 mb-1.5">{sym}</p>
                    <div className="space-y-1 text-xs">
                      <div className="flex justify-between text-slate-500">
                        <span>Trades</span><span className="text-slate-400">{st.length}</span>
                      </div>
                      <div className="flex justify-between text-slate-500">
                        <span>Win Rate</span>
                        <span className="text-emerald-400">{st.length > 0 ? ((sw / st.length) * 100).toFixed(0) : 0}%</span>
                      </div>
                      <div className="flex justify-between text-slate-500">
                        <span>P&L</span>
                        <span className={`font-semibold font-mono ${sp >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {sp >= 0 ? "+" : ""}${sp.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Slippage */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Slippage</h3>
            <div className="space-y-2 text-sm">
              {[
                { l: "Avg", v: `${(avgSlippage * 100).toFixed(3)}%`, cls: "text-amber-400" },
                { l: "Max", v: `${(Math.max(...trades.map((t) => t.slippage)) * 100).toFixed(3)}%`, cls: "text-red-400" },
                { l: "Min", v: `${(Math.min(...trades.map((t) => t.slippage)) * 100).toFixed(3)}%`, cls: "text-emerald-400" },
              ].map(({ l, v, cls }) => (
                <div key={l} className="flex justify-between">
                  <span className="text-slate-500">{l}</span>
                  <span className={`font-mono ${cls}`}>{v}</span>
                </div>
              ))}
              <p className="text-[10px] text-slate-600 border-t border-slate-700 pt-2 mt-2">
                0.10% taker commission · target &lt;0.015%
              </p>
            </div>
          </div>

          {/* Recent trades */}
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Last 5 Trades</h3>
            <div className="space-y-2">
              {trades.slice(0, 5).map((t, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className={t.side === "LONG" ? "text-emerald-400" : "text-amber-400"}>
                    {t.side === "LONG" ? "↑" : "↓"} {t.sym.split("/")[0]}
                  </span>
                  <span className={`font-semibold font-mono ${t.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
