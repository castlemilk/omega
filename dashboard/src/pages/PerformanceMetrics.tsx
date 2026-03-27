import { useEffect, useState } from "react";
import {
  BarChart2,
  TrendingUp,
  AlertTriangle,
  Clock,
} from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  ComposedChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";

const BASE = "";

// ── Types ──────────────────────────────────────────────────────────────────

interface MetricPoint {
  ts: string;
  value_ms: number;
  cycle: number;
}

interface SignalTiming {
  name: string;
  avg_ms: number;
  max_ms: number;
  exec_count: number;
}

interface MetricsResponse {
  cycle_latency: MetricPoint[];
  signal_timings: SignalTiming[];
  api_response_p50_ms: number;
  api_response_p95_ms: number;
  db_query_p50_ms: number;
  db_query_p95_ms: number;
}

// ── Chart helpers ──────────────────────────────────────────────────────────

const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const GRID = "#374151";
const TICK = { fontSize: 10, fill: "#6b7280" };

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

// Color scale for bar chart: green → amber → red
function barColor(ms: number, avg: number): string {
  if (avg === 0) return "#6366f1";
  const ratio = ms / avg;
  if (ratio > 2) return "#ef4444";
  if (ratio > 1.3) return "#f59e0b";
  return "#22c55e";
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  unit,
  accent,
}: {
  label: string;
  value: number | string;
  unit?: string;
  accent?: string;
}) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent ?? "text-white"}`}>
        {typeof value === "number" ? value.toFixed(0) : value}
        {unit && <span className="text-sm text-gray-500 ml-1">{unit}</span>}
      </p>
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-48 flex items-center justify-center text-gray-600 text-xs font-mono border border-dashed border-gray-700 rounded-lg">
      {label}
    </div>
  );
}

function CycleLatencyChart({ data }: { data: MetricPoint[] }) {
  if (!data || data.length === 0) {
    return <EmptyChart label="No cycle data yet — run a cycle to populate" />;
  }

  const chartData = data.map((p) => ({
    time: formatTs(p.ts),
    ms: Math.round(p.value_ms),
    cycle: p.cycle,
  }));

  const p95 = [...data].sort((a, b) => a.value_ms - b.value_ms)[
    Math.floor(data.length * 0.95)
  ]?.value_ms ?? 0;

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="time" tick={TICK} interval="preserveStartEnd" />
          <YAxis
            tick={TICK}
            width={45}
            tickFormatter={(v) => `${v}ms`}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number) => [`${v}ms`, "Latency"]}
            labelFormatter={(label, payload) => {
              const cycle = payload?.[0]?.payload?.cycle;
              return `${label}${cycle ? ` · cycle #${cycle}` : ""}`;
            }}
          />
          <Line
            type="monotone"
            dataKey="ms"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
          {/* p95 reference — rendered as dashed overlay via recharts ReferenceLine not imported; use second line */}
          <Line
            type="monotone"
            dataKey={() => Math.round(p95)}
            stroke="#ef4444"
            strokeWidth={1}
            strokeDasharray="4 4"
            dot={false}
            name="p95"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function SignalTimingChart({ data }: { data: SignalTiming[] }) {
  if (!data || data.length === 0) {
    return <EmptyChart label="No node execution data yet" />;
  }

  const avg = data.reduce((s, d) => s + d.avg_ms, 0) / data.length;
  const chartData = data.slice(0, 15).map((d) => ({
    name: d.name.length > 20 ? d.name.slice(0, 18) + "…" : d.name,
    fullName: d.name,
    avg_ms: Math.round(d.avg_ms),
    max_ms: Math.round(d.max_ms),
    executions: d.exec_count,
    color: barColor(d.avg_ms, avg),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={TICK} tickFormatter={(v) => `${v}ms`} />
          <YAxis type="category" dataKey="name" tick={{ ...TICK, fontSize: 9 }} width={120} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number, name: string) => [`${v}ms`, name === "avg_ms" ? "Avg" : "Max"]}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.fullName ?? ""}
          />
          <Bar dataKey="avg_ms" name="avg_ms" radius={[0, 3, 3, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={entry.color} />
            ))}
          </Bar>
          <Bar dataKey="max_ms" name="max_ms" fill="#374151" opacity={0.5} radius={[0, 3, 3, 0]} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function APILatencyChart({ p50, p95 }: { p50: number; p95: number }) {
  const bars = [
    { label: "API p50", ms: p50, fill: "#22c55e" },
    { label: "API p95", ms: p95, fill: "#6366f1" },
  ];
  return (
    <div className="h-32">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bars} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="label" tick={TICK} />
          <YAxis tick={TICK} tickFormatter={(v) => `${v}ms`} width={40} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number) => [`${v}ms`]}
          />
          <Bar dataKey="ms" radius={[4, 4, 0, 0]}>
            {bars.map((b, i) => (
              <Cell key={i} fill={b.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function DBLatencyChart({ p50, p95 }: { p50: number; p95: number }) {
  const bars = [
    { label: "DB p50", ms: p50, fill: "#22c55e" },
    { label: "DB p95", ms: p95, fill: "#f59e0b" },
  ];
  return (
    <div className="h-32">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bars} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="label" tick={TICK} />
          <YAxis tick={TICK} tickFormatter={(v) => `${v}ms`} width={40} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number) => [`${v}ms`]}
          />
          <Bar dataKey="ms" radius={[4, 4, 0, 0]}>
            {bars.map((b, i) => (
              <Cell key={i} fill={b.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

const EMPTY: MetricsResponse = {
  cycle_latency: [],
  signal_timings: [],
  api_response_p50_ms: 0,
  api_response_p95_ms: 0,
  db_query_p50_ms: 0,
  db_query_p95_ms: 0,
};

export default function PerformanceMetrics() {
  const [data, setData] = useState<MetricsResponse>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    try {
      const res = await fetch(`${BASE}/api/v1/dashboard/obs/metrics`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30000);
    return () => clearInterval(id);
  }, []);

  // Compute averages from cycle latency
  const cycleAvg =
    data.cycle_latency.length > 0
      ? data.cycle_latency.reduce((s, p) => s + p.value_ms, 0) / data.cycle_latency.length
      : 0;
  const cycleP95 =
    data.cycle_latency.length > 0
      ? [...data.cycle_latency].sort((a, b) => a.value_ms - b.value_ms)[
          Math.floor(data.cycle_latency.length * 0.95)
        ]?.value_ms ?? 0
      : 0;

  const slowestSignal =
    data.signal_timings.length > 0
      ? data.signal_timings.reduce((a, b) => (a.avg_ms > b.avg_ms ? a : b))
      : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BarChart2 size={20} className="text-indigo-400" />
            Performance Metrics
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Cycle latency, signal timing, and API/DB response times
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            className="text-xs px-3 py-1.5 bg-surface-700 hover:bg-surface-600 text-gray-300 rounded-lg border border-surface-600 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-3 text-xs text-red-400 flex items-center gap-2">
          <AlertTriangle size={13} />
          Backend unavailable ({error})
        </div>
      )}

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Loading metrics…
        </div>
      )}

      {!loading && (
        <>
          {/* KPI strip */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <StatCard
              label="Cycle avg"
              value={cycleAvg}
              unit="ms"
              accent={cycleAvg > 5000 ? "text-red-400" : cycleAvg > 2000 ? "text-amber-400" : "text-green-400"}
            />
            <StatCard label="Cycle p95" value={cycleP95} unit="ms" />
            <StatCard label="API p50" value={data.api_response_p50_ms} unit="ms" accent="text-green-400" />
            <StatCard label="API p95" value={data.api_response_p95_ms} unit="ms" />
            <StatCard
              label="Slowest signal"
              value={slowestSignal ? `${slowestSignal.avg_ms.toFixed(0)}ms` : "—"}
              accent="text-amber-400"
            />
          </div>

          {/* Cycle latency chart */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                Cycle Latency Over Time
              </h2>
              <span className="text-xs text-gray-600">
                <span className="inline-block w-3 h-0.5 bg-indigo-400 mr-1 align-middle" />
                actual
                <span className="inline-block w-3 h-0.5 bg-red-400 border-dashed border-t ml-3 mr-1 align-middle" />
                p95
              </span>
            </div>
            <CycleLatencyChart data={data.cycle_latency} />
          </div>

          {/* Signal computation breakdown */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
              Node Execution Time Breakdown
            </h2>
            <p className="text-xs text-gray-600">Avg (colored by ratio to mean) + max (grey). Top 15 slowest.</p>
            <SignalTimingChart data={data.signal_timings} />
          </div>

          {/* API + DB latency row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2">
                <TrendingUp size={14} className="text-indigo-400" />
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                  API Response Time
                </h2>
              </div>
              <APILatencyChart
                p50={data.api_response_p50_ms}
                p95={data.api_response_p95_ms}
              />
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2">
                <Clock size={14} className="text-amber-400" />
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                  DB Query Latency
                </h2>
              </div>
              <DBLatencyChart
                p50={data.db_query_p50_ms}
                p95={data.db_query_p95_ms}
              />
            </div>
          </div>

          {/* Signal timings table */}
          {data.signal_timings.length > 0 && (
            <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-700">
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                  All Node Timings
                </h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-600 border-b border-gray-700">
                      <th className="text-left px-4 py-2 font-medium">Node</th>
                      <th className="text-right px-4 py-2 font-medium">Avg</th>
                      <th className="text-right px-4 py-2 font-medium">Max</th>
                      <th className="text-right px-4 py-2 font-medium">Executions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.signal_timings.map((t) => {
                      const avg = data.signal_timings.reduce((s, x) => s + x.avg_ms, 0) / data.signal_timings.length;
                      const isBottleneck = t.avg_ms > avg * 2;
                      return (
                        <tr
                          key={t.name}
                          className={`border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors ${
                            isBottleneck ? "bg-red-900/10" : ""
                          }`}
                        >
                          <td className="px-4 py-2 font-mono text-gray-300 flex items-center gap-2">
                            {isBottleneck && (
                              <span className="text-red-400 text-xs">⚠</span>
                            )}
                            {t.name}
                          </td>
                          <td
                            className={`px-4 py-2 text-right font-mono font-semibold ${
                              isBottleneck ? "text-red-400" : "text-gray-300"
                            }`}
                          >
                            {t.avg_ms.toFixed(1)}ms
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-gray-500">
                            {t.max_ms.toFixed(1)}ms
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-gray-500">
                            {t.exec_count.toLocaleString()}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
