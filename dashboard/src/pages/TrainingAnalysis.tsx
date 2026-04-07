import { useEffect, useState } from "react";
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
} from "recharts";
import { BarChart2 } from "lucide-react";

const BASE = "";
const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const GRID_COLOR = "#374151";
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };

// ── JSONL row shape (new fields from feat(observability)) ──────────────────────

interface MetricRow {
  cycle: number;
  ts: string;
  version: string;
  regime: string;
  composite_score: number | null;
  trade_action: string;
  sit_out_reason: string | null;
  active_signals: number;
  ring1_pass: boolean;
  conviction: string;
  new_trades: number;
  total_closed: number;
  elapsed_s: number;
  breaker_tripped: boolean;
  vol_low_threshold: number | null;
  // Enhanced fields
  basket_std: number;
  basket_mean: number;
  zero_streak: number;
  regime_hmm: string;
  regime_consolidated: string;
  stale_symbols: string[];
  active_filters: string[];
}

interface SymbolStats {
  symbol: string;
  trades: number;
  win_rate: number;
  total_pnl: number;
}

interface TrainingMetrics {
  symbol_breakdown: SymbolStats[];
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  current_cycle: number;
  total_cycles: number;
  status: string;
}

// ── Symbol colour palette ──────────────────────────────────────────────────────

const SYM_COLORS: Record<string, string> = {
  ETHUSDT: "#6366f1",
  DOTUSDT: "#f59e0b",
  LINKUSDT: "#ef4444",
  SOLUSDT: "#10b981",
  BTCUSDT: "#f97316",
};
const FALLBACK_COLORS = ["#8b5cf6", "#06b6d4", "#84cc16", "#ec4899", "#14b8a6"];
function symColor(sym: string, idx: number): string {
  return SYM_COLORS[sym] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
}

// ── Derived chart data helpers ─────────────────────────────────────────────────



// ── Regime audit row ───────────────────────────────────────────────────────────

function regimeMismatch(row: MetricRow): boolean {
  return (
    row.regime_hmm !== "" &&
    row.regime_consolidated !== "" &&
    row.regime_hmm !== row.regime_consolidated
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ZeroStreakBadge({ streak }: { streak: number }) {
  if (streak === 0) return null;
  const danger = streak > 15;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-semibold ${
        danger
          ? "bg-red-900/60 text-red-300 border border-red-700 animate-pulse"
          : streak > 5
            ? "bg-orange-900/40 text-orange-300 border border-orange-800"
            : "bg-gray-700 text-gray-400"
      }`}
      title={`${streak} consecutive zero-trade cycles`}
    >
      streak={streak}
    </span>
  );
}

function RegimeAuditPanel({ rows }: { rows: MetricRow[] }) {
  // Show last 40 cycles where there's a label to display
  const recent = rows.slice(-40).reverse();
  const mismatches = recent.filter(regimeMismatch);

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Regime Audit — HMM vs Consolidated
        </h3>
        {mismatches.length > 0 && (
          <span className="text-xs text-orange-400 font-mono">
            {mismatches.length} mismatch{mismatches.length !== 1 ? "es" : ""}
          </span>
        )}
      </div>
      <div className="overflow-y-auto max-h-64">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-800 z-10">
            <tr className="text-gray-600 border-b border-gray-700">
              <th className="text-left px-4 py-2 font-medium">Cycle</th>
              <th className="text-left px-4 py-2 font-medium">HMM</th>
              <th className="text-left px-4 py-2 font-medium">Consolidated</th>
              <th className="text-left px-4 py-2 font-medium">Zero Streak</th>
              <th className="text-left px-4 py-2 font-medium">Filters</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((row) => {
              const mismatch = regimeMismatch(row);
              return (
                <tr
                  key={row.cycle}
                  className={`border-b border-gray-700/50 ${
                    row.zero_streak > 15
                      ? "bg-red-900/20"
                      : mismatch
                        ? "bg-orange-900/10"
                        : "hover:bg-gray-700/20"
                  }`}
                >
                  <td className="px-4 py-1.5 font-mono text-gray-400">
                    #{row.cycle}
                  </td>
                  <td className="px-4 py-1.5 font-mono">
                    <span
                      className={
                        row.regime_hmm === "high_vol"
                          ? "text-orange-400"
                          : row.regime_hmm === "crisis" || row.regime_hmm === "bear"
                            ? "text-red-400"
                            : row.regime_hmm === "bull"
                              ? "text-green-400"
                              : "text-gray-400"
                      }
                    >
                      {row.regime_hmm || "—"}
                    </span>
                  </td>
                  <td className="px-4 py-1.5 font-mono">
                    <span
                      className={
                        row.regime_consolidated === "high_vol"
                          ? "text-orange-400"
                          : row.regime_consolidated === "crisis"
                            ? "text-red-400"
                            : row.regime_consolidated === "bull"
                              ? "text-green-400"
                              : "text-gray-400"
                      }
                    >
                      {row.regime_consolidated || "—"}
                    </span>
                    {mismatch && (
                      <span className="ml-1 text-orange-500">⚠</span>
                    )}
                  </td>
                  <td className="px-4 py-1.5">
                    <ZeroStreakBadge streak={row.zero_streak} />
                  </td>
                  <td className="px-4 py-1.5 text-gray-500 font-mono truncate max-w-[180px]">
                    {row.active_filters.join(", ") || "—"}
                  </td>
                </tr>
              );
            })}
            {recent.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-gray-600">
                  No JSONL data yet — start a training run
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── PnL + basket_std dual-axis chart ──────────────────────────────────────────

function PnlBasketChart({ rows }: { rows: MetricRow[] }) {
  // Build per-cycle cumulative PnL using total_closed as a proxy
  // (We don't have cycle-level PnL in JSONL — we use new_trades to detect trade cycles)
  // For the overlay demo, we show basket_std trend against the total_closed count
  type Point = {
    cycle: number;
    total_closed: number;
    basket_std: number;
    zero_streak: number;
  };

  const points: Point[] = rows.map((r) => ({
    cycle: r.cycle,
    total_closed: r.total_closed,
    basket_std: r.basket_std,
    zero_streak: r.zero_streak,
  }));

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Closed Trades + basket_std
        </h3>
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-indigo-400" /> Closed trades
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-amber-400" style={{ borderTop: "2px dashed #f59e0b", height: 0 }} />
            <span className="text-amber-400">basket_std</span>
          </span>
        </div>
      </div>
      <div className="h-52">
        {points.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points} margin={{ top: 4, right: 40, bottom: 0, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
              <XAxis dataKey="cycle" tick={TICK_STYLE} />
              <YAxis
                yAxisId="left"
                tick={TICK_STYLE}
                tickFormatter={(v: number) => String(v)}
                label={{ value: "trades", angle: -90, position: "insideLeft", fontSize: 9, fill: "#6b7280" }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={TICK_STYLE}
                tickFormatter={(v: number) => v.toFixed(3)}
                label={{ value: "std", angle: 90, position: "insideRight", fontSize: 9, fill: "#6b7280" }}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(val: number, name: string) =>
                  name === "basket_std"
                    ? [val.toFixed(4), "basket_std"]
                    : [val, "closed trades"]
                }
              />
              <defs>
                <linearGradient id="tradesGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="total_closed"
                stroke="#6366f1"
                fill="url(#tradesGrad)"
                strokeWidth={2}
                dot={false}
                name="total_closed"
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="basket_std"
                stroke="#f59e0b"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                name="basket_std"
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">
            No JSONL data yet
          </div>
        )}
      </div>
      {/* Zero-streak highlight band */}
      {rows.some((r) => r.zero_streak > 15) && (
        <div className="mt-1 px-3 py-2 bg-red-900/30 border border-red-800/50 rounded text-xs text-red-400 font-mono">
          ⚠ Extended zero-streak detected in this run (streak &gt; 15 cycles) — check basket_std spike
        </div>
      )}
    </div>
  );
}

// ── Per-symbol stacked PnL area chart ─────────────────────────────────────────

function SymbolPnLChart({ symbols }: { symbols: SymbolStats[] }) {
  if (symbols.length === 0) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
          Per-Symbol PnL
        </h3>
        <div className="flex items-center justify-center h-40 text-gray-600 text-sm">
          No symbol data yet
        </div>
      </div>
    );
  }

  // Build a single stacked bar data point per symbol (not time-series — we don't have that)
  // Show as horizontal bars sorted by PnL
  const sorted = [...symbols].sort((a, b) => b.total_pnl - a.total_pnl);

  type StackPoint = { name: string; [k: string]: number | string };
  const chartData: StackPoint[] = sorted.map((s) => ({
    name: s.symbol.replace("USDT", ""),
    pnl: s.total_pnl,
    trades: s.trades,
    wr: Math.round(s.win_rate * 100),
  }));

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
        Per-Symbol PnL
      </h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={chartData}
            layout="vertical"
            margin={{ top: 4, right: 40, bottom: 0, left: 32 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
            <XAxis
              type="number"
              tick={TICK_STYLE}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            />
            <YAxis type="category" dataKey="name" tick={TICK_STYLE} width={36} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(val: number) => [`$${val.toFixed(2)}`, "PnL"]}
            />
            {sorted.map((s, i) => (
              <Area
                key={s.symbol}
                type="monotone"
                dataKey="pnl"
                stroke={symColor(s.symbol, i)}
                fill={symColor(s.symbol, i)}
                fillOpacity={0.2}
                strokeWidth={2}
                dot={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {/* Symbol table */}
      <div className="overflow-x-auto mt-2">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-600 border-b border-gray-700">
              <th className="text-left px-2 py-1.5 font-medium">Symbol</th>
              <th className="text-right px-2 py-1.5 font-medium">Trades</th>
              <th className="text-right px-2 py-1.5 font-medium">WR%</th>
              <th className="text-right px-2 py-1.5 font-medium">PnL</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, i) => (
              <tr key={s.symbol} className="border-b border-gray-700/40 hover:bg-gray-700/20">
                <td className="px-2 py-1.5 font-mono flex items-center gap-1.5">
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: symColor(s.symbol, i) }}
                  />
                  {s.symbol}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-gray-400">
                  {s.trades}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">
                  <span className={s.win_rate >= 0.5 ? "text-green-400" : s.win_rate >= 0.35 ? "text-yellow-400" : "text-red-400"}>
                    {Math.round(s.win_rate * 100)}%
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right font-mono">
                  <span className={s.total_pnl >= 0 ? "text-green-400" : "text-red-400"}>
                    {s.total_pnl >= 0 ? "+" : ""}${s.total_pnl.toFixed(2)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function TrainingAnalysis() {
  const [rows, setRows] = useState<MetricRow[]>([]);
  const [metrics, setMetrics] = useState<TrainingMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [version, setVersion] = useState<string>("");

  async function fetchAll() {
    try {
      const [jsonlRes, metRes] = await Promise.all([
        fetch(`${BASE}/api/v1/training/jsonl${version ? `?version=${version}` : ""}`),
        fetch(`${BASE}/api/v1/training/metrics`),
      ]);
      if (jsonlRes.ok) {
        const arr: MetricRow[] = await jsonlRes.json();
        setRows(arr);
        if (arr.length > 0 && !version) {
          setVersion(arr[0].version);
        }
      }
      if (metRes.ok) setMetrics(await metRes.json());
      setLastUpdated(new Date());
    } catch {
      // swallow — training server may not be running
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 8000);
    return () => clearInterval(id);
  }, [version]);

  const latestRow = rows[rows.length - 1];
  const currentStreak = latestRow?.zero_streak ?? 0;
  const symbols = metrics?.symbol_breakdown ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BarChart2 size={20} className="text-amber-400" />
            Training Analysis
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            basket_std • regime audit • per-symbol PnL — auto-refreshes every 8s
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          {version && (
            <span className="text-xs font-mono px-2 py-1 bg-gray-800 border border-gray-700 rounded text-indigo-400">
              {version}
            </span>
          )}
          <ZeroStreakBadge streak={currentStreak} />
        </div>
      </div>

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Loading analysis data…
        </div>
      )}

      {!loading && (
        <>
          {/* Key stats strip */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">basket_std</p>
              <p className={`text-2xl font-bold font-mono ${
                (latestRow?.basket_std ?? 0) > 0.5 ? "text-red-400" : "text-amber-400"
              }`}>
                {latestRow ? latestRow.basket_std.toFixed(4) : "—"}
              </p>
              <p className="text-xs text-gray-600 mt-0.5">
                mean {latestRow ? latestRow.basket_mean.toFixed(4) : "—"}
              </p>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Zero Streak</p>
              <p className={`text-2xl font-bold font-mono ${
                currentStreak > 15 ? "text-red-400" : currentStreak > 5 ? "text-orange-400" : "text-gray-400"
              }`}>
                {currentStreak}
              </p>
              <p className="text-xs text-gray-600 mt-0.5">consecutive HOLD cycles</p>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Regime</p>
              <div className="space-y-0.5">
                <p className="text-sm font-mono text-gray-300">
                  hmm: <span className="text-indigo-400">{latestRow?.regime_hmm || "—"}</span>
                </p>
                <p className="text-sm font-mono text-gray-300">
                  consolidated: <span className={
                    latestRow?.regime_consolidated === "high_vol" ? "text-orange-400" :
                    latestRow?.regime_consolidated === "crisis" ? "text-red-400" : "text-green-400"
                  }>{latestRow?.regime_consolidated || "—"}</span>
                </p>
              </div>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Cycles</p>
              <p className="text-2xl font-bold font-mono text-white">{rows.length}</p>
              <p className="text-xs text-gray-600 mt-0.5">
                {latestRow?.total_closed ?? 0} trades closed
              </p>
            </div>
          </div>

          {/* PnL + basket_std chart */}
          <PnlBasketChart rows={rows} />

          {/* Regime audit + per-symbol side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <RegimeAuditPanel rows={rows} />
            <SymbolPnLChart symbols={symbols} />
          </div>
        </>
      )}
    </div>
  );
}
