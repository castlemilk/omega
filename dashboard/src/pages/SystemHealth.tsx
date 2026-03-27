import { useEffect, useState } from "react";
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Activity,
  Database,
  Server,
  Cpu,
  Brain,
  Clock,
} from "lucide-react";
const BASE = "";

// ── Types ──────────────────────────────────────────────────────────────────

interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  last_heartbeat: string;
  error_count_1h: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  uptime_seconds: number;
}

interface TracesSummary {
  total_spans_1h: number;
  error_spans_1h: number;
  slowest_op: string;
  slowest_op_ms: number;
  avg_duration_ms: number;
}

interface SignalHealth {
  name: string;
  last_value: number;
  non_zero: boolean;
  error_count: number;
  last_run_at: string;
  duration_ms: number;
}

interface MemoryStats {
  episodes_per_hour: number;
  shared_mem_per_hour: number;
  memory_ratings_count: number;
  total_episodes: number;
}

interface ServicesResponse {
  services: ServiceStatus[];
  traces_summary: TracesSummary;
  signal_health: SignalHealth[];
  memory_stats: MemoryStats;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-yellow-400",
  unhealthy: "text-red-400",
  unknown: "text-gray-500",
};

const STATUS_BG: Record<string, string> = {
  healthy: "bg-green-900/30 border-green-800",
  degraded: "bg-yellow-900/30 border-yellow-800",
  unhealthy: "bg-red-900/30 border-red-800",
  unknown: "bg-gray-800 border-gray-700",
};

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-green-400",
  degraded: "bg-yellow-400",
  unhealthy: "bg-red-400",
  unknown: "bg-gray-500",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "healthy")
    return <CheckCircle size={16} className="text-green-400 shrink-0" />;
  if (status === "unhealthy")
    return <XCircle size={16} className="text-red-400 shrink-0" />;
  if (status === "degraded")
    return <AlertTriangle size={16} className="text-yellow-400 shrink-0" />;
  return <Activity size={16} className="text-gray-500 shrink-0" />;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "—";
  }
}

const SERVICE_ICONS: Record<string, React.ElementType> = {
  "Go API": Server,
  "Python Bridge": Cpu,
  Postgres: Database,
  Frontend: Activity,
};

// ── ServiceCard ────────────────────────────────────────────────────────────

function ServiceCard({ svc }: { svc: ServiceStatus }) {
  const Icon = SERVICE_ICONS[svc.name] ?? Server;
  return (
    <div
      className={`rounded-xl border p-4 space-y-3 ${STATUS_BG[svc.status] ?? "bg-gray-800 border-gray-700"}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon size={18} className="text-gray-400" />
          <span className="font-semibold text-sm text-white">{svc.name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${STATUS_DOT[svc.status]}`} />
          <span className={`text-xs font-medium uppercase ${STATUS_COLOR[svc.status]}`}>
            {svc.status}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-gray-500">Last heartbeat</p>
          <p className="text-gray-300 font-mono">{formatTime(svc.last_heartbeat)}</p>
        </div>
        <div>
          <p className="text-gray-500">Errors / 1h</p>
          <p
            className={`font-mono font-semibold ${svc.error_count_1h > 0 ? "text-red-400" : "text-green-400"}`}
          >
            {svc.error_count_1h}
          </p>
        </div>
        <div>
          <p className="text-gray-500">p50 latency</p>
          <p className="text-gray-300 font-mono">{svc.p50_latency_ms.toFixed(0)}ms</p>
        </div>
        <div>
          <p className="text-gray-500">p95 latency</p>
          <p className="text-gray-300 font-mono">{svc.p95_latency_ms.toFixed(0)}ms</p>
        </div>
      </div>

      <div className="text-xs text-gray-600">
        <Clock size={11} className="inline mr-1" />
        Uptime: {formatUptime(svc.uptime_seconds)}
      </div>
    </div>
  );
}

// ── TracesSummary ──────────────────────────────────────────────────────────

function TracesSummaryCard({ summary }: { summary: TracesSummary }) {
  const errorRate =
    summary.total_spans_1h > 0
      ? ((summary.error_spans_1h / summary.total_spans_1h) * 100).toFixed(1)
      : "0.0";
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
        OTel Trace Summary · 1h
      </h3>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-2xl font-bold text-white">{summary.total_spans_1h.toLocaleString()}</p>
          <p className="text-xs text-gray-500">Total spans</p>
        </div>
        <div>
          <p className={`text-2xl font-bold ${summary.error_spans_1h > 0 ? "text-red-400" : "text-green-400"}`}>
            {summary.error_spans_1h}
          </p>
          <p className="text-xs text-gray-500">Error spans</p>
        </div>
        <div>
          <p className="text-2xl font-bold text-white">{errorRate}%</p>
          <p className="text-xs text-gray-500">Error rate</p>
        </div>
        <div>
          <p className="text-2xl font-bold text-white">{summary.avg_duration_ms.toFixed(0)}ms</p>
          <p className="text-xs text-gray-500">Avg span duration</p>
        </div>
      </div>
      {summary.slowest_op && summary.slowest_op !== "—" && (
        <div className="pt-1 border-t border-gray-700">
          <p className="text-xs text-gray-500">Slowest operation</p>
          <p className="text-xs text-amber-400 font-mono mt-0.5">
            {summary.slowest_op} ({summary.slowest_op_ms.toFixed(0)}ms)
          </p>
        </div>
      )}
    </div>
  );
}

// ── SignalHealthTable ──────────────────────────────────────────────────────

function SignalHealthTable({ signals }: { signals: SignalHealth[] }) {
  if (!signals || signals.length === 0) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
          Signal Pipeline Health
        </h3>
        <p className="text-sm text-gray-600 text-center py-4">No signal data in last cycle</p>
      </div>
    );
  }
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-700">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Signal Pipeline Health · Last Cycle
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-600 border-b border-gray-700">
              <th className="text-left px-4 py-2 font-medium">Node</th>
              <th className="text-left px-4 py-2 font-medium">Status</th>
              <th className="text-right px-4 py-2 font-medium">Duration</th>
              <th className="text-right px-4 py-2 font-medium">Errors</th>
              <th className="text-right px-4 py-2 font-medium">Last run</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((sig) => (
              <tr
                key={sig.name}
                className="border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors"
              >
                <td className="px-4 py-2 font-mono text-gray-300">{sig.name}</td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                      sig.non_zero
                        ? "bg-green-900/40 text-green-400"
                        : "bg-red-900/40 text-red-400"
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${sig.non_zero ? "bg-green-400" : "bg-red-400"}`}
                    />
                    {sig.non_zero ? "OK" : "error"}
                  </span>
                </td>
                <td className="px-4 py-2 text-right font-mono text-gray-400">
                  {sig.duration_ms.toFixed(0)}ms
                </td>
                <td className="px-4 py-2 text-right">
                  <span
                    className={`font-mono font-semibold ${sig.error_count > 0 ? "text-red-400" : "text-gray-600"}`}
                  >
                    {sig.error_count}
                  </span>
                </td>
                <td className="px-4 py-2 text-right font-mono text-gray-500">
                  {formatTime(sig.last_run_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── MemoryStatsCard ────────────────────────────────────────────────────────

function MemoryStatsCard({ stats }: { stats: MemoryStats }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Brain size={15} className="text-indigo-400" />
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Memory System
        </h3>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xl font-bold text-white">{stats.episodes_per_hour.toFixed(0)}</p>
          <p className="text-xs text-gray-500">Episodes / hour</p>
        </div>
        <div>
          <p className="text-xl font-bold text-white">{stats.shared_mem_per_hour.toFixed(0)}</p>
          <p className="text-xs text-gray-500">Shared mem / hour</p>
        </div>
        <div>
          <p className="text-xl font-bold text-white">{stats.total_episodes.toLocaleString()}</p>
          <p className="text-xs text-gray-500">Total episodes</p>
        </div>
        <div>
          <p className="text-xl font-bold text-white">{stats.memory_ratings_count.toLocaleString()}</p>
          <p className="text-xs text-gray-500">Memory ratings</p>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

const EMPTY_RESPONSE: ServicesResponse = {
  services: [],
  traces_summary: {
    total_spans_1h: 0,
    error_spans_1h: 0,
    slowest_op: "—",
    slowest_op_ms: 0,
    avg_duration_ms: 0,
  },
  signal_health: [],
  memory_stats: {
    episodes_per_hour: 0,
    shared_mem_per_hour: 0,
    memory_ratings_count: 0,
    total_episodes: 0,
  },
};

export default function SystemHealth() {
  const [data, setData] = useState<ServicesResponse>(EMPTY_RESPONSE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    try {
      const res = await fetch(`${BASE}/api/v1/dashboard/obs/services`);
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
    const id = setInterval(fetchData, 15000);
    return () => clearInterval(id);
  }, []);

  const overallStatus = data.services.length === 0
    ? "unknown"
    : data.services.some((s) => s.status === "unhealthy")
    ? "unhealthy"
    : data.services.some((s) => s.status === "degraded")
    ? "degraded"
    : "healthy";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity size={20} className="text-indigo-400" />
            System Health
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Platform-level service status, traces, and pipeline health
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <div
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold uppercase ${
              STATUS_BG[overallStatus] ?? "bg-gray-800 border-gray-700"
            } ${STATUS_COLOR[overallStatus]}`}
          >
            <StatusIcon status={overallStatus} />
            {overallStatus}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-sm text-red-400">
          <AlertTriangle size={14} className="inline mr-2" />
          Backend unavailable — showing cached data. ({error})
        </div>
      )}

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Loading health data…
        </div>
      )}

      {!loading && (
        <>
          {/* Service cards */}
          <section>
            <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-widest mb-3">
              Services
            </h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {data.services.map((svc) => (
                <ServiceCard key={svc.name} svc={svc} />
              ))}
              {data.services.length === 0 &&
                ["Go API", "Python Bridge", "Postgres", "Frontend"].map((name) => (
                  <ServiceCard
                    key={name}
                    svc={{
                      name,
                      status: "unknown",
                      last_heartbeat: "",
                      error_count_1h: 0,
                      p50_latency_ms: 0,
                      p95_latency_ms: 0,
                      uptime_seconds: 0,
                    }}
                  />
                ))}
            </div>
          </section>

          {/* Traces + Memory row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2">
              <TracesSummaryCard summary={data.traces_summary} />
            </div>
            <MemoryStatsCard stats={data.memory_stats} />
          </div>

          {/* Signal health */}
          <SignalHealthTable signals={data.signal_health ?? []} />
        </>
      )}
    </div>
  );
}
