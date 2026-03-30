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
  Radio,
  TrendingUp,
  TrendingDown,
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

// ── Heartbeat / Control Plane Types ───────────────────────────────────────

interface HeartbeatNode {
  node_id: string;
  node_type: string;
  health: "healthy" | "degraded" | "stale" | "dead" | "unknown";
  last_seen: string;
  metrics: Record<string, string>;
  blockers: string[];
  stale: boolean;
}

interface TrainingDiagnostics {
  node_id: string;
  cycle: number;
  regime: string;
  active_signals: number;
  total_signals: number;
  sit_out: boolean;
  sit_out_reason: string;
  open_trades: number;
  closed_trades: number;
  pnl: number;
  longs: number;
  shorts: number;
  blockers: string[];
  ticker_convictions: Record<string, number>;
  timestamp: string;
}

const HEALTH_COLOR: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-yellow-400",
  stale: "text-orange-400",
  dead: "text-red-400",
  unknown: "text-gray-500",
};

const HEALTH_BG: Record<string, string> = {
  healthy: "bg-green-900/20 border-green-800/40",
  degraded: "bg-yellow-900/20 border-yellow-800/40",
  stale: "bg-orange-900/20 border-orange-800/40",
  dead: "bg-red-900/20 border-red-800/40",
  unknown: "bg-gray-800 border-gray-700",
};

function timeSince(iso: string): string {
  if (!iso) return "never";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function HeartbeatNodeCard({ node }: { node: HeartbeatNode }) {
  const health = node.stale ? "stale" : node.health;
  return (
    <div className={`rounded-xl border p-3 space-y-2 ${HEALTH_BG[health] ?? HEALTH_BG.unknown}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Radio size={12} className={HEALTH_COLOR[health]} />
          <span className="font-mono text-xs text-white truncate max-w-[140px]">{node.node_id}</span>
        </div>
        <span className={`text-xs font-semibold uppercase ${HEALTH_COLOR[health]}`}>{health}</span>
      </div>
      <div className="flex justify-between text-xs">
        <span className="text-gray-500">{node.node_type || "node"}</span>
        <span className="font-mono text-gray-400">{timeSince(node.last_seen)}</span>
      </div>
      {node.blockers.length > 0 && (
        <div className="space-y-0.5">
          {node.blockers.slice(0, 2).map((b, i) => (
            <p key={i} className="text-xs text-orange-400 font-mono truncate">
              ⚠ {b}
            </p>
          ))}
        </div>
      )}
      {node.metrics.cycle && (
        <div className="flex gap-3 text-xs text-gray-500 font-mono">
          <span>cycle {node.metrics.cycle}</span>
          {node.metrics.regime && <span>· {node.metrics.regime}</span>}
          {node.metrics.pnl && (
            <span className={parseFloat(node.metrics.pnl) >= 0 ? "text-green-400" : "text-red-400"}>
              · ${parseFloat(node.metrics.pnl).toFixed(2)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function TrainingDiagnosticsCard({ diag }: { diag: TrainingDiagnostics | null }) {
  if (!diag) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 text-center text-sm text-gray-600">
        No training diagnostics — start a training run
      </div>
    );
  }
  const pnlPositive = diag.pnl >= 0;
  const regimeColor =
    diag.regime === "bull" ? "text-green-400"
      : diag.regime === "bear" ? "text-red-400"
      : "text-yellow-400";
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Training Loop · Live
        </h3>
        <span className="text-xs font-mono text-gray-500">{formatTime(diag.timestamp)}</span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <p className="text-2xl font-bold text-white font-mono">#{diag.cycle}</p>
          <p className="text-xs text-gray-500">Cycle</p>
        </div>
        <div>
          <p className={`text-2xl font-bold font-mono ${pnlPositive ? "text-green-400" : "text-red-400"}`}>
            {pnlPositive ? "+" : ""}${diag.pnl.toFixed(2)}
          </p>
          <p className="text-xs text-gray-500">Realised PnL</p>
        </div>
        <div>
          <p className={`text-xl font-bold font-mono uppercase ${regimeColor}`}>{diag.regime || "—"}</p>
          <p className="text-xs text-gray-500">Regime</p>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2 text-xs border-t border-gray-700 pt-2">
        <div>
          <p className="text-gray-500">Signals</p>
          <p className="font-mono text-gray-300">{diag.active_signals}/{diag.total_signals}</p>
        </div>
        <div>
          <p className="text-gray-500">Trades</p>
          <p className="font-mono text-gray-300">{diag.open_trades} open</p>
        </div>
        <div>
          <p className="text-gray-500">Direction</p>
          <div className="flex gap-1 items-center">
            <TrendingUp size={10} className="text-green-400" />
            <span className="font-mono text-green-400">{diag.longs}</span>
            <TrendingDown size={10} className="text-red-400 ml-1" />
            <span className="font-mono text-red-400">{diag.shorts}</span>
          </div>
        </div>
        <div>
          <p className="text-gray-500">Sit-out</p>
          <p className={`font-mono ${diag.sit_out ? "text-orange-400" : "text-green-400"}`}>
            {diag.sit_out ? diag.sit_out_reason || "yes" : "no"}
          </p>
        </div>
      </div>
      {diag.blockers.length > 0 && (
        <div className="border-t border-gray-700 pt-2 space-y-1">
          {diag.blockers.map((b, i) => (
            <p key={i} className="text-xs font-mono text-orange-400">⚠ {b}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function NodeHeartbeatPanel() {
  const [nodes, setNodes] = useState<HeartbeatNode[]>([]);
  const [diag, setDiag] = useState<TrainingDiagnostics | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchHeartbeats() {
    try {
      const [nodesRes, diagRes] = await Promise.all([
        fetch(`${BASE}/api/v1/nodes`),
        fetch(`${BASE}/api/v1/diagnostics`),
      ]);
      if (nodesRes.ok) setNodes(await nodesRes.json());
      if (diagRes.ok) {
        const d = await diagRes.json();
        if (d.available !== false) setDiag(d);
      }
      setLastUpdated(new Date());
    } catch {
      // silently swallow — control plane may not be running
    }
  }

  useEffect(() => {
    fetchHeartbeats();
    const id = setInterval(fetchHeartbeats, 5000);
    return () => clearInterval(id);
  }, []);

  const liveCount = nodes.filter((n) => !n.stale && n.health === "healthy").length;
  const staleCount = nodes.filter((n) => n.stale || n.health === "stale").length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio size={14} className="text-indigo-400" />
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
            Node Heartbeats
          </h2>
          {nodes.length > 0 && (
            <span className="text-xs text-gray-600">
              {liveCount} live · {staleCount} stale
            </span>
          )}
        </div>
        {lastUpdated && (
          <span className="text-xs text-gray-600 font-mono">
            {timeSince(lastUpdated.toISOString())}
          </span>
        )}
      </div>

      <TrainingDiagnosticsCard diag={diag} />

      {nodes.length > 0 ? (
        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {nodes.map((n) => (
            <HeartbeatNodeCard key={n.node_id} node={n} />
          ))}
        </div>
      ) : (
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 text-center text-sm text-gray-600">
          No nodes reporting — Go control plane may not be running
        </div>
      )}
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

          {/* Node heartbeats + training diagnostics */}
          <NodeHeartbeatPanel />
        </>
      )}
    </div>
  );
}
