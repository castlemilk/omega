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
  BarChart,
  Bar,
  Cell,
  ReferenceLine,
} from "recharts";
import { BarChart2, X, TrendingUp, TrendingDown, Minus } from "lucide-react";

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
  // Per-cycle signal snapshots (from feat(training) waterfall logging)
  signal_snapshot?: Record<string, number>;
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
  recent_trades?: RecentTrade[];
}

interface RecentTrade {
  ts: string;
  sym: string;
  side: string;
  size: number;
  entry: number;
  exit_price: number;
  pnl: number;
  conviction?: number;
  regime?: string;
}

// ── Signal weights (router_weights.json shape) ────────────────────────────────

interface RouterWeights {
  trained_at?: string;
  n_outcomes?: number;
  node_weights?: Record<string, number>;
  node_stats?: Record<string, { ema: number; n: number; mean: number; min: number; max: number }>;
}

// ── New-signals panel types ───────────────────────────────────────────────────

interface SignalLatest {
  name: string;
  value: number;
  prev_value: number;
  cycle: number;
}

// ── Tab type ──────────────────────────────────────────────────────────────────

type TabId = "overview" | "signals" | "analysis";

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

// ── Panel 1: ML Combiner Weights ───────────────────────────────────────────────

// Mock fallback — mirrors signal names used in Victoria strategy
const MOCK_SIGNAL_WEIGHTS: { signal: string; weight: number; category: string }[] = [
  { signal: "momentum", weight: 0.18, category: "technical" },
  { signal: "funding_rate", weight: 0.14, category: "derivatives" },
  { signal: "hmm_regime", weight: 0.13, category: "regime" },
  { signal: "fear_greed", weight: 0.11, category: "sentiment" },
  { signal: "dxy", weight: 0.10, category: "macro" },
  { signal: "smart_money", weight: 0.09, category: "onchain" },
  { signal: "liquidation", weight: 0.08, category: "derivatives" },
  { signal: "rmt_denoiser", weight: 0.07, category: "statistical" },
  { signal: "wavelet", weight: 0.06, category: "statistical" },
  { signal: "finbert", weight: 0.04, category: "sentiment" },
];

const CATEGORY_COLORS: Record<string, string> = {
  technical: "#6366f1",
  derivatives: "#f59e0b",
  regime: "#10b981",
  sentiment: "#ec4899",
  macro: "#06b6d4",
  onchain: "#8b5cf6",
  statistical: "#84cc16",
};

function MLCombinerWeightsPanel() {
  const [weights, setWeights] = useState<{ signal: string; weight: number; category: string }[]>([]);
  const [trainedAt, setTrainedAt] = useState<string>("");
  const [fromMock, setFromMock] = useState(false);

  useEffect(() => {
    fetch(`${BASE}/api/v1/training/signal-weights`)
      .then((r) => {
        if (!r.ok) throw new Error("not found");
        return r.json();
      })
      .then((data: { weights: typeof weights; trained_at?: string }) => {
        if (data.weights && data.weights.length > 0) {
          setWeights(data.weights);
          setTrainedAt(data.trained_at ?? "");
          setFromMock(false);
        } else {
          setWeights(MOCK_SIGNAL_WEIGHTS);
          setFromMock(true);
        }
      })
      .catch(() => {
        // Fall back to router_weights.json shape served by Go if available,
        // otherwise use static mock.
        fetch(`${BASE}/api/v1/training/router-weights`)
          .then((r) => (r.ok ? r.json() : Promise.reject()))
          .then((data: RouterWeights) => {
            if (data.node_weights && Object.keys(data.node_weights).length > 0) {
              const mapped = Object.entries(data.node_weights)
                .sort(([, a], [, b]) => b - a)
                .map(([name, weight]) => ({
                  signal: name,
                  weight,
                  category: "node",
                }));
              setWeights(mapped);
              setTrainedAt(data.trained_at ?? "");
              setFromMock(false);
            } else {
              setWeights(MOCK_SIGNAL_WEIGHTS);
              setFromMock(true);
            }
          })
          .catch(() => {
            setWeights(MOCK_SIGNAL_WEIGHTS);
            setFromMock(true);
          });
      });
  }, []);

  const sorted = [...weights].sort((a, b) => b.weight - a.weight);

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
            ML Combiner Weights
          </h3>
          {trainedAt && (
            <p className="text-xs text-gray-600 mt-0.5">
              trained {new Date(trainedAt).toLocaleDateString()}
            </p>
          )}
        </div>
        {fromMock && (
          <span className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded">
            mock
          </span>
        )}
      </div>

      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={sorted}
            layout="vertical"
            margin={{ top: 2, right: 48, bottom: 2, left: 88 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
            <XAxis
              type="number"
              tick={TICK_STYLE}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              domain={[0, "dataMax"]}
            />
            <YAxis
              type="category"
              dataKey="signal"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              width={86}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(val: number) => [`${(val * 100).toFixed(1)}%`, "weight"]}
            />
            <Bar dataKey="weight" name="Weight" radius={3}>
              {sorted.map((d, i) => (
                <Cell
                  key={i}
                  fill={CATEGORY_COLORS[d.category] ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length]}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Category legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 border-t border-gray-700">
        {[...new Set(sorted.map((d) => d.category))].map((cat) => (
          <span key={cat} className="flex items-center gap-1 text-xs text-gray-500">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: CATEGORY_COLORS[cat] ?? "#6b7280" }}
            />
            {cat}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Panel 2: New Signals panel ─────────────────────────────────────────────────

// The three focus signals added in recent feature work
const NEW_SIGNAL_KEYS = ["funding_rate", "fear_greed", "dxy"];

const SIGNAL_META: Record<string, { label: string; unit: string; color: string; description: string }> = {
  funding_rate: {
    label: "Funding Rate",
    unit: "%",
    color: "#f59e0b",
    description: "Perp funding — positive = longs pay shorts (bearish)",
  },
  fear_greed: {
    label: "Fear & Greed",
    unit: "/100",
    color: "#ec4899",
    description: "Crypto Fear & Greed Index — 0=extreme fear, 100=extreme greed",
  },
  dxy: {
    label: "DXY Signal",
    unit: "",
    color: "#06b6d4",
    description: "US Dollar Index cross-asset signal — negative DXY → BTC tailwind",
  },
};

// Mock latest values — used when signal_snapshot not present in JSONL
const MOCK_SIGNAL_LATEST: SignalLatest[] = [
  { name: "funding_rate", value: 0.0042, prev_value: 0.0038, cycle: 0 },
  { name: "fear_greed", value: 31.0, prev_value: 28.0, cycle: 0 },
  { name: "dxy", value: -0.062, prev_value: -0.045, cycle: 0 },
];

function directionIcon(curr: number, prev: number) {
  if (curr > prev + 1e-6) return <TrendingUp size={12} className="text-green-400" />;
  if (curr < prev - 1e-6) return <TrendingDown size={12} className="text-red-400" />;
  return <Minus size={12} className="text-gray-500" />;
}

function NewSignalsPanel({ rows }: { rows: MetricRow[] }) {
  // Build latest values from JSONL signal_snapshot; fall back to mock
  const latestSnaps: SignalLatest[] = NEW_SIGNAL_KEYS.map((key) => {
    // Walk backward through rows to find the most recent snapshot containing this key
    for (let i = rows.length - 1; i >= 0; i--) {
      const snap = rows[i].signal_snapshot;
      if (snap && key in snap) {
        const prev = (() => {
          for (let j = i - 1; j >= 0; j--) {
            const ps = rows[j].signal_snapshot;
            if (ps && key in ps) return ps[key];
          }
          return snap[key];
        })();
        return { name: key, value: snap[key], prev_value: prev, cycle: rows[i].cycle };
      }
    }
    return MOCK_SIGNAL_LATEST.find((s) => s.name === key) ?? { name: key, value: 0, prev_value: 0, cycle: 0 };
  });

  const isMock = latestSnaps.every((s) => s.cycle === 0);

  // Build trend data per signal (last 30 cycles with snapshot)
  const trendData: Record<string, { cycle: number; value: number }[]> = {};
  for (const key of NEW_SIGNAL_KEYS) {
    trendData[key] = rows
      .filter((r) => r.signal_snapshot && key in r.signal_snapshot)
      .slice(-30)
      .map((r) => ({ cycle: r.cycle, value: r.signal_snapshot![key] }));
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          New Signals — Latest Values
        </h3>
        {isMock && (
          <span className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded">
            mock
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4">
        {latestSnaps.map((s) => {
          const meta = SIGNAL_META[s.name] ?? { label: s.name, unit: "", color: "#6b7280", description: "" };
          const trend = trendData[s.name] ?? [];
          const hasTrend = trend.length > 2;

          return (
            <div key={s.name} className="bg-gray-900 border border-gray-700 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold" style={{ color: meta.color }}>
                    {meta.label}
                  </p>
                  <p className="text-[10px] text-gray-600 mt-0.5">{meta.description}</p>
                </div>
                <div className="text-right">
                  <div className="flex items-center gap-1 justify-end">
                    {directionIcon(s.value, s.prev_value)}
                    <span className="text-lg font-bold font-mono text-white">
                      {Math.abs(s.value) < 0.01 ? s.value.toFixed(4) : s.value.toFixed(3)}
                    </span>
                    <span className="text-xs text-gray-500">{meta.unit}</span>
                  </div>
                  <p className="text-[10px] text-gray-600 font-mono">
                    prev {Math.abs(s.prev_value) < 0.01 ? s.prev_value.toFixed(4) : s.prev_value.toFixed(3)}
                  </p>
                </div>
              </div>
              {hasTrend && (
                <div className="h-14">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={trend} margin={{ top: 2, right: 4, bottom: 0, left: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                      <XAxis dataKey="cycle" tick={false} />
                      <YAxis tick={{ fontSize: 8, fill: "#6b7280" }} width={32} tickFormatter={(v: number) => v.toFixed(3)} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number) => [v.toFixed(4), meta.label]} />
                      <ReferenceLine y={0} stroke="#374151" strokeDasharray="2 2" />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={meta.color}
                        strokeWidth={1.5}
                        dot={false}
                        name={meta.label}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
              {!hasTrend && (
                <p className="text-[10px] text-gray-600 text-center py-2">
                  No trend data yet — needs signal_snapshot in JSONL
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Panel 3: Signal Waterfall for Selected Trade ───────────────────────────────

// Build a waterfall dataset from: (a) signal_snapshot on the cycle closest to
// the trade, or (b) a synthetic set from conviction + regime when no snapshot exists.
function buildWaterfallData(
  trade: RecentTrade,
  rows: MetricRow[]
): { signal: string; value: number }[] {
  // Find the JSONL row whose cycle is nearest to the trade (by ts proximity)
  const tradeTs = new Date(trade.ts).getTime();
  let nearest: MetricRow | null = null;
  let minDiff = Infinity;
  for (const row of rows) {
    const diff = Math.abs(new Date(row.ts).getTime() - tradeTs);
    if (diff < minDiff) {
      minDiff = diff;
      nearest = row;
    }
  }

  if (nearest?.signal_snapshot && Object.keys(nearest.signal_snapshot).length > 0) {
    return Object.entries(nearest.signal_snapshot)
      .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
      .map(([signal, value]) => ({ signal, value }));
  }

  // Fallback: synthesise from available trade fields
  const conviction = trade.conviction ?? 0.1;
  const sideSign = trade.side === "long" ? 1 : -1;
  return [
    { signal: "conviction", value: conviction * sideSign },
    { signal: "regime", value: trade.regime === "normal" ? 0.05 : trade.regime === "high_vol" ? -0.05 : -0.1 },
    { signal: "momentum", value: conviction * 0.6 * sideSign },
    { signal: "funding_rate", value: (MOCK_SIGNAL_LATEST.find((s) => s.name === "funding_rate")?.value ?? 0.004) * sideSign },
    { signal: "fear_greed", value: ((MOCK_SIGNAL_LATEST.find((s) => s.name === "fear_greed")?.value ?? 30) - 50) / 200 },
    { signal: "dxy", value: MOCK_SIGNAL_LATEST.find((s) => s.name === "dxy")?.value ?? -0.06 },
  ];
}

function SignalWaterfallPanel({
  trade,
  rows,
  onClose,
}: {
  trade: RecentTrade;
  rows: MetricRow[];
  onClose: () => void;
}) {
  const data = buildWaterfallData(trade, rows);
  const isSynthetic = rows.every((r) => !r.signal_snapshot || Object.keys(r.signal_snapshot).length === 0);

  return (
    <div className="bg-gray-800 border border-indigo-700/50 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-widest flex items-center gap-2">
            Signal Waterfall
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                trade.pnl >= 0
                  ? "bg-green-900/50 text-green-400 border border-green-800"
                  : "bg-red-900/50 text-red-400 border border-red-800"
              }`}
            >
              {trade.side.toUpperCase()} {trade.sym}
            </span>
            <span className={`text-xs font-mono font-semibold ${trade.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {trade.pnl >= 0 ? "+" : ""}${trade.pnl.toFixed(2)}
            </span>
          </h3>
          <p className="text-[10px] text-gray-600 mt-0.5">
            {new Date(trade.ts).toLocaleString()} · regime: {trade.regime ?? "—"}
            {isSynthetic && " · synthetic (no signal_snapshot in JSONL)"}
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded text-gray-500 hover:text-gray-300 hover:bg-gray-700 transition-colors"
          title="Close waterfall"
        >
          <X size={14} />
        </button>
      </div>

      <div style={{ height: Math.max(140, data.length * 24) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 2, right: 48, bottom: 2, left: 100 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} horizontal={false} />
            <XAxis
              type="number"
              tick={TICK_STYLE}
              tickFormatter={(v: number) => v.toFixed(3)}
            />
            <YAxis
              type="category"
              dataKey="signal"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              width={98}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(val: number, _name: string, props: { payload?: { signal?: string } }) => [
                val.toFixed(4),
                props.payload?.signal ?? "value",
              ]}
            />
            <ReferenceLine x={0} stroke="#6b7280" strokeDasharray="3 3" />
            <Bar dataKey="value" name="Signal Value" radius={3}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.value >= 0 ? "#10b981" : "#ef4444"} fillOpacity={0.8} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[10px] text-gray-600">
        Green = bullish contribution · Red = bearish · Sorted by absolute magnitude
      </p>
    </div>
  );
}

// ── Trades table with click-to-waterfall ──────────────────────────────────────

function TradesTable({
  metrics,
  rows,
}: {
  metrics: TrainingMetrics | null;
  rows: MetricRow[];
}) {
  const [selectedTrade, setSelectedTrade] = useState<RecentTrade | null>(null);

  const trades: RecentTrade[] = metrics?.recent_trades ?? [];

  function toggleTrade(trade: RecentTrade) {
    setSelectedTrade((prev) =>
      prev && prev.ts === trade.ts && prev.sym === trade.sym ? null : trade
    );
  }

  return (
    <div className="space-y-3">
      <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-700">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
            Recent Trades
            <span className="ml-2 text-gray-600 normal-case font-normal">click a row to see signal waterfall</span>
          </h3>
        </div>
        <div className="overflow-y-auto max-h-72">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-800 z-10">
              <tr className="text-gray-600 border-b border-gray-700">
                <th className="text-left px-4 py-2 font-medium">Time</th>
                <th className="text-left px-4 py-2 font-medium">Symbol</th>
                <th className="text-left px-4 py-2 font-medium">Side</th>
                <th className="text-right px-4 py-2 font-medium">Entry</th>
                <th className="text-right px-4 py-2 font-medium">Exit</th>
                <th className="text-right px-4 py-2 font-medium">PnL</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-600">
                    No trades yet
                  </td>
                </tr>
              )}
              {trades.map((t, i) => {
                const isSelected =
                  selectedTrade?.ts === t.ts && selectedTrade?.sym === t.sym;
                return (
                  <tr
                    key={i}
                    onClick={() => toggleTrade(t)}
                    className={`border-b border-gray-700/50 cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-indigo-900/30 border-l-2 border-l-indigo-500"
                        : "hover:bg-gray-700/20"
                    }`}
                  >
                    <td className="px-4 py-1.5 font-mono text-gray-500">
                      {new Date(t.ts).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-1.5 font-mono text-gray-300">{t.sym}</td>
                    <td className="px-4 py-1.5">
                      <span
                        className={`text-xs font-semibold ${
                          t.side === "long" ? "text-green-400" : "text-red-400"
                        }`}
                      >
                        {t.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-1.5 text-right font-mono text-gray-400">
                      ${t.entry.toFixed(2)}
                    </td>
                    <td className="px-4 py-1.5 text-right font-mono text-gray-400">
                      ${t.exit_price.toFixed(2)}
                    </td>
                    <td className="px-4 py-1.5 text-right font-mono">
                      <span className={t.pnl >= 0 ? "text-green-400" : "text-red-400"}>
                        {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {selectedTrade && (
        <SignalWaterfallPanel
          trade={selectedTrade}
          rows={rows}
          onClose={() => setSelectedTrade(null)}
        />
      )}
    </div>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

function TabBar({
  active,
  onChange,
}: {
  active: TabId;
  onChange: (t: TabId) => void;
}) {
  const tabs: { id: TabId; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "signals", label: "Signal Analysis" },
    { id: "analysis", label: "ML Weights" },
  ];
  return (
    <div className="flex gap-1 border-b border-gray-700 pb-0">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-4 py-2 text-xs font-medium rounded-t transition-colors ${
            active === t.id
              ? "bg-gray-800 border border-b-0 border-gray-700 text-white"
              : "text-gray-500 hover:text-gray-300"
          }`}
        >
          {t.label}
        </button>
      ))}
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
  const [activeTab, setActiveTab] = useState<TabId>("overview");

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
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BarChart2 size={20} className="text-amber-400" />
            Training Analysis
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            basket_std • regime audit • per-symbol PnL • ML weights • signal waterfall — auto-refreshes every 8s
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
          {/* Key stats strip — always visible */}
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

          {/* Tab bar */}
          <TabBar active={activeTab} onChange={setActiveTab} />

          {/* Tab: Overview */}
          {activeTab === "overview" && (
            <div className="space-y-4">
              <PnlBasketChart rows={rows} />
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <RegimeAuditPanel rows={rows} />
                <SymbolPnLChart symbols={symbols} />
              </div>
            </div>
          )}

          {/* Tab: Signal Analysis */}
          {activeTab === "signals" && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <NewSignalsPanel rows={rows} />
              <TradesTable metrics={metrics} rows={rows} />
            </div>
          )}

          {/* Tab: ML Weights */}
          {activeTab === "analysis" && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <MLCombinerWeightsPanel />
              <div className="space-y-4">
                <TradesTable metrics={metrics} rows={rows} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
