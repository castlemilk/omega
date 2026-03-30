import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Activity, Play, Square, TrendingUp, TrendingDown } from "lucide-react";

const BASE = "";
const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const GRID_COLOR = "#374151";
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };

// ── Types ──────────────────────────────────────────────────────────────────────

interface ActivityEntry {
  cycle: number;
  type: string;
  message: string;
}

interface PnlPoint {
  cycle: number;
  pnl: number;
}

interface WinRatePoint {
  cycle: number;
  win_rate: number;
}

interface TrainingProgress {
  run_id: string;
  total_cycles: number;
  current_cycle: number;
  started_at: string;
  status: "running" | "idle" | "complete";
  pnl_history: PnlPoint[];
  win_rate_history: WinRatePoint[];
  activity_log: ActivityEntry[];
  current_regime: { name: string; confidence: number; dominant_signal: string };
  config: { symbols: string[]; initial_capital: number; kelly_fraction: number };
}

interface TrainingMetrics {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  realised_pnl: number;
  unrealised_pnl: number;
  symbol_breakdown: Array<{
    symbol: string;
    trades: number;
    win_rate: number;
    total_pnl: number;
  }>;
  current_cycle: number;
  total_cycles: number;
  status: string;
}

interface DiagData {
  cycle: number;
  regime: string;
  longs: number;
  shorts: number;
  active_signals: number;
  total_signals: number;
  pnl: number;
  blockers: string[];
  sit_out: boolean;
  sit_out_reason: string;
  data_freshness_seconds: number;
}

// ── Win Rate Gauge (SVG circle) ────────────────────────────────────────────────

function WinRateGauge({ rate }: { rate: number }) {
  const r = 36;
  const cx = 50;
  const cy = 50;
  const circ = 2 * Math.PI * r;
  const filled = circ * Math.min(rate, 1);
  const color = rate >= 0.6 ? "#4ade80" : rate >= 0.45 ? "#facc15" : "#f87171";

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#374151" strokeWidth="8" />
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`}
        />
        <text
          x={cx}
          y={cy + 5}
          textAnchor="middle"
          fill={color}
          fontSize="15"
          fontWeight="bold"
          fontFamily="monospace"
        >
          {(rate * 100).toFixed(0)}%
        </text>
      </svg>
      <p className="text-xs text-gray-500">Win Rate</p>
    </div>
  );
}

// ── Long/Short Split Bar ───────────────────────────────────────────────────────

function DirectionBar({ longs, shorts }: { longs: number; shorts: number }) {
  const total = longs + shorts;
  const longPct = total > 0 ? (longs / total) * 100 : 50;
  const shortPct = 100 - longPct;

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-gray-500">
        <div className="flex items-center gap-1">
          <TrendingUp size={10} className="text-green-400" />
          <span>Long {longs}</span>
        </div>
        <div className="flex items-center gap-1">
          <span>Short {shorts}</span>
          <TrendingDown size={10} className="text-red-400" />
        </div>
      </div>
      <div className="h-4 rounded-full overflow-hidden flex bg-gray-700">
        <div
          className="bg-green-500 transition-all duration-500"
          style={{ width: `${longPct}%` }}
        />
        <div
          className="bg-red-500 transition-all duration-500"
          style={{ width: `${shortPct}%` }}
        />
      </div>
      <div className="flex justify-between text-xs font-mono text-gray-500">
        <span>{longPct.toFixed(0)}%</span>
        <span>{shortPct.toFixed(0)}%</span>
      </div>
    </div>
  );
}

// ── Activity Log Table ─────────────────────────────────────────────────────────

const TYPE_COLOR: Record<string, string> = {
  trade: "text-blue-400 bg-blue-900/30",
  signal: "text-purple-400 bg-purple-900/30",
  memory: "text-indigo-400 bg-indigo-900/30",
  error: "text-red-400 bg-red-900/30",
  info: "text-gray-400 bg-gray-700/40",
};

function ActivityTable({
  log,
  pnlHistory,
}: {
  log: ActivityEntry[];
  pnlHistory: PnlPoint[];
}) {
  // Build a cycle → pnl delta map
  const pnlMap = new Map(pnlHistory.map((p) => [p.cycle, p.pnl]));

  // Deduplicate by cycle, take last 20 unique cycles (most recent first)
  const byCycle = new Map<number, ActivityEntry[]>();
  for (const entry of log) {
    if (!byCycle.has(entry.cycle)) byCycle.set(entry.cycle, []);
    byCycle.get(entry.cycle)!.push(entry);
  }
  const cycles = Array.from(byCycle.keys())
    .sort((a, b) => b - a)
    .slice(0, 20);

  if (cycles.length === 0) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 text-center text-sm text-gray-600">
        No activity yet — run a training cycle to see events
      </div>
    );
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-700">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Last {cycles.length} Cycles
        </h3>
      </div>
      <div className="overflow-y-auto max-h-72">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-800 z-10">
            <tr className="text-gray-600 border-b border-gray-700">
              <th className="text-left px-4 py-2 font-medium">Cycle</th>
              <th className="text-left px-4 py-2 font-medium">Events</th>
              <th className="text-right px-4 py-2 font-medium">PnL Δ</th>
            </tr>
          </thead>
          <tbody>
            {cycles.map((cycle) => {
              const entries = byCycle.get(cycle) ?? [];
              const pnlDelta = pnlMap.get(cycle);
              return (
                <tr
                  key={cycle}
                  className="border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors"
                >
                  <td className="px-4 py-2.5 font-mono text-gray-400 align-top">
                    #{cycle}
                  </td>
                  <td className="px-4 py-2.5 align-top">
                    <div className="flex flex-wrap gap-1">
                      {entries.map((e, i) => (
                        <span
                          key={i}
                          className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                            TYPE_COLOR[e.type] ?? TYPE_COLOR.info
                          }`}
                          title={e.message}
                        >
                          {e.type}
                        </span>
                      ))}
                    </div>
                    <p className="text-gray-500 mt-1 truncate max-w-sm">
                      {entries[0]?.message ?? "—"}
                    </p>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono align-top">
                    {pnlDelta !== undefined ? (
                      <span
                        className={pnlDelta >= 0 ? "text-green-400" : "text-red-400"}
                      >
                        {pnlDelta >= 0 ? "+" : ""}
                        {pnlDelta.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function Training() {
  const [progress, setProgress] = useState<TrainingProgress | null>(null);
  const [metrics, setMetrics] = useState<TrainingMetrics | null>(null);
  const [diag, setDiag] = useState<DiagData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchAll() {
    try {
      const [progRes, metRes, diagRes] = await Promise.all([
        fetch(`${BASE}/api/v1/training/progress`),
        fetch(`${BASE}/api/v1/training/metrics`),
        fetch(`${BASE}/api/v1/diagnostics`),
      ]);
      if (progRes.ok) setProgress(await progRes.json());
      if (metRes.ok) setMetrics(await metRes.json());
      if (diagRes.ok) {
        const d = await diagRes.json();
        if (d.available !== false) setDiag(d);
      }
      setLastUpdated(new Date());
    } catch {
      // swallow — training server may not be running
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => clearInterval(id);
  }, []);

  const currentCycle =
    progress?.current_cycle ?? metrics?.current_cycle ?? diag?.cycle ?? 0;
  const totalCycles = progress?.total_cycles ?? metrics?.total_cycles ?? 500;
  const status = progress?.status ?? (metrics?.status as TrainingProgress["status"]) ?? "idle";
  const progressPct =
    totalCycles > 0 ? Math.min((currentCycle / totalCycles) * 100, 100) : 0;
  const winRate = metrics?.win_rate ?? 0;
  const totalPnl =
    metrics?.total_pnl ?? progress?.pnl_history?.slice(-1)[0]?.pnl ?? 0;
  const pnlHistory = progress?.pnl_history ?? [];
  const activityLog = progress?.activity_log ?? [];
  const longs = diag?.longs ?? 0;
  const shorts = diag?.shorts ?? 0;
  const regime =
    diag?.regime ?? progress?.current_regime?.name ?? "—";
  const blockers = diag?.blockers ?? [];

  // Build cumulative PnL series
  const cumPnl = pnlHistory.reduce<Array<{ cycle: number; pnl: number; cumPnl: number }>>(
    (acc, p) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].cumPnl : 0;
      acc.push({ ...p, cumPnl: prev + p.pnl });
      return acc;
    },
    []
  );

  const statusColor =
    status === "running"
      ? "text-green-400"
      : status === "complete"
        ? "text-blue-400"
        : "text-gray-500";
  const regimeColor =
    regime === "bull"
      ? "text-green-400"
      : regime === "bear"
        ? "text-red-400"
        : "text-yellow-400";

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity size={20} className="text-indigo-400" />
            Training Feed
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Live training loop — auto-refreshes every 5s
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <div
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold uppercase ${
              status === "running"
                ? "border-green-700 bg-green-900/30 text-green-400"
                : status === "complete"
                  ? "border-blue-700 bg-blue-900/30 text-blue-400"
                  : "border-gray-700 bg-gray-800 text-gray-500"
            }`}
          >
            {status === "running" ? <Play size={11} /> : <Square size={11} />}
            {status}
          </div>
        </div>
      </div>

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Loading training data…
        </div>
      )}

      {!loading && (
        <>
          {/* Cycle progress bar */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                  Cycle Progress
                </span>
                <span className={`text-xs font-mono font-semibold uppercase ${statusColor}`}>
                  {status}
                </span>
              </div>
              <span className="text-xs font-mono text-gray-400">
                {currentCycle.toLocaleString()} / {totalCycles.toLocaleString()}
              </span>
            </div>
            <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-500">
              <span>{progressPct.toFixed(1)}% complete</span>
              <span>{Math.max(0, totalCycles - currentCycle).toLocaleString()} cycles remaining</span>
            </div>
          </div>

          {/* Stats row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Total PnL</p>
              <p
                className={`text-2xl font-bold font-mono ${
                  totalPnl >= 0 ? "text-green-400" : "text-red-400"
                }`}
              >
                {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}
              </p>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Regime</p>
              <p className={`text-2xl font-bold font-mono uppercase ${regimeColor}`}>
                {regime}
              </p>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">
                Active Signals
              </p>
              <p className="text-2xl font-bold font-mono text-white">
                {diag?.active_signals ?? "—"}
                <span className="text-gray-600">/{diag?.total_signals ?? "—"}</span>
              </p>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">
                Total Trades
              </p>
              <p className="text-2xl font-bold font-mono text-white">
                {metrics?.total_trades ?? "—"}
              </p>
            </div>
          </div>

          {/* Charts row: PnL curve + Win rate gauge + Direction bar */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Cumulative PnL area chart */}
            <div className="lg:col-span-2 bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                Cumulative PnL
              </h3>
              <div className="h-52">
                {cumPnl.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={cumPnl} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                      <defs>
                        <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                      <XAxis dataKey="cycle" tick={TICK_STYLE} />
                      <YAxis
                        tick={TICK_STYLE}
                        tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                      />
                      <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        formatter={(v: number) => [`$${v.toFixed(2)}`, "Cum PnL"]}
                      />
                      <Area
                        type="monotone"
                        dataKey="cumPnl"
                        stroke="#6366f1"
                        fill="url(#pnlGrad)"
                        strokeWidth={2}
                        dot={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-600 text-sm">
                    No PnL history yet
                  </div>
                )}
              </div>
            </div>

            {/* Win rate gauge + Direction bar stacked */}
            <div className="flex flex-col gap-4">
              <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 flex flex-col items-center justify-center gap-1">
                <WinRateGauge rate={winRate} />
                <p className="text-xs text-gray-600 font-mono">
                  {metrics?.total_trades ?? 0} trades
                </p>
              </div>
              <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                  Long / Short Split
                </h3>
                <DirectionBar longs={longs} shorts={shorts} />
              </div>
            </div>
          </div>

          {/* Active blockers */}
          {blockers.length > 0 && (
            <div className="bg-red-900/20 border border-red-800/50 rounded-xl p-4 space-y-1">
              <h3 className="text-xs font-semibold text-red-400 uppercase tracking-widest mb-2">
                Active Blockers
              </h3>
              {blockers.map((b, i) => (
                <p key={i} className="text-sm font-mono text-orange-400">
                  ⚠ {b}
                </p>
              ))}
            </div>
          )}

          {/* Cycle activity log */}
          <ActivityTable log={activityLog} pnlHistory={pnlHistory} />
        </>
      )}
    </div>
  );
}
