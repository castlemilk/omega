// NODE HEALTH — platform-wide health overview: per-node scores, radar charts, lifecycle, alerts
import { useEffect, useState, useCallback } from "react";
import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  HeartPulse,
  Server,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Activity,
} from "lucide-react";
import { client } from "../client";

const BASE = "";
const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };

// ── Types ──────────────────────────────────────────────────────────────────────

interface NodeSnapshot {
  nodeId: string;
  name: string;
  version: string;
  health: number;       // 0.0–1.0
  status: string;       // "healthy" | "degraded" | "offline" | "starting" | etc.
  avgLatencyMs: number;
  p95LatencyMs: number;
  errorRate: number;
  executionsTotal: number;
  improvementCount: number;
  registeredAt?: string;
  lastUpdated?: string;
}

interface Alert {
  id: string;
  node: string;
  severity: "critical" | "warning" | "info";
  message: string;
  triggered_at: string;
}

// ── Mock data ──────────────────────────────────────────────────────────────────

const MOCK_NODES: NodeSnapshot[] = [
  {
    nodeId: "victoria-v2",
    name: "Victoria",
    version: "v2.3",
    health: 0.94,
    status: "healthy",
    avgLatencyMs: 45.2,
    p95LatencyMs: 118.0,
    errorRate: 0.018,
    executionsTotal: 1247,
    improvementCount: 8,
    registeredAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 14).toISOString(),
    lastUpdated: new Date(Date.now() - 1000 * 45).toISOString(),
  },
  {
    nodeId: "devils-advocate",
    name: "Devil's Advocate",
    version: "v1.2",
    health: 0.87,
    status: "healthy",
    avgLatencyMs: 82.4,
    p95LatencyMs: 210.0,
    errorRate: 0.04,
    executionsTotal: 843,
    improvementCount: 3,
    registeredAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 10).toISOString(),
    lastUpdated: new Date(Date.now() - 1000 * 90).toISOString(),
  },
  {
    nodeId: "signal-router",
    name: "Signal Router",
    version: "v1.5",
    health: 0.76,
    status: "degraded",
    avgLatencyMs: 12.1,
    p95LatencyMs: 28.0,
    errorRate: 0.02,
    executionsTotal: 5812,
    improvementCount: 2,
    registeredAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 20).toISOString(),
    lastUpdated: new Date(Date.now() - 1000 * 30).toISOString(),
  },
  {
    nodeId: "memory-consolidator",
    name: "Memory Consolidator",
    version: "v1.0",
    health: 0.52,
    status: "degraded",
    avgLatencyMs: 210.0,
    p95LatencyMs: 650.0,
    errorRate: 0.11,
    executionsTotal: 312,
    improvementCount: 1,
    registeredAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 7).toISOString(),
    lastUpdated: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
  },
  {
    nodeId: "alignment-gate",
    name: "Alignment Gate",
    version: "v2.0",
    health: 0.91,
    status: "healthy",
    avgLatencyMs: 33.0,
    p95LatencyMs: 89.0,
    errorRate: 0.008,
    executionsTotal: 2104,
    improvementCount: 5,
    registeredAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 12).toISOString(),
    lastUpdated: new Date(Date.now() - 1000 * 20).toISOString(),
  },
  {
    nodeId: "adversarial-engine",
    name: "Adversarial Engine",
    version: "v1.8",
    health: 0.30,
    status: "offline",
    avgLatencyMs: 520.0,
    p95LatencyMs: 1200.0,
    errorRate: 0.28,
    executionsTotal: 95,
    improvementCount: 0,
    registeredAt: new Date(Date.now() - 1000 * 60 * 60 * 24 * 5).toISOString(),
    lastUpdated: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
  },
];

const MOCK_ALERTS: Alert[] = [
  {
    id: "a1",
    node: "Adversarial Engine",
    severity: "critical",
    message: "Error rate 28% — exceeds threshold (10%)",
    triggered_at: new Date(Date.now() - 1000 * 60 * 8).toISOString(),
  },
  {
    id: "a2",
    node: "Memory Consolidator",
    severity: "warning",
    message: "P95 latency 650ms — exceeds threshold (500ms)",
    triggered_at: new Date(Date.now() - 1000 * 60 * 22).toISOString(),
  },
  {
    id: "a3",
    node: "Memory Consolidator",
    severity: "warning",
    message: "Health score 52 — below warning threshold (60)",
    triggered_at: new Date(Date.now() - 1000 * 60 * 35).toISOString(),
  },
];

// ── Helpers ────────────────────────────────────────────────────────────────────

function healthColor(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 50) return "#eab308";
  return "#ef4444";
}

function healthBorderCls(score: number): string {
  if (score >= 80) return "border-green-700";
  if (score >= 50) return "border-yellow-700";
  return "border-red-700";
}

function statusLabel(status: string): { label: string; cls: string } {
  switch (status.toLowerCase()) {
    case "starting":  return { label: "STARTING",  cls: "text-blue-400" };
    case "healthy":   return { label: "HEALTHY",   cls: "text-emerald-400" };
    case "degraded":  return { label: "DEGRADED",  cls: "text-yellow-400" };
    case "offline":   return { label: "OFFLINE",   cls: "text-gray-600" };
    case "stopping":  return { label: "STOPPING",  cls: "text-orange-400" };
    case "error":     return { label: "ERROR",     cls: "text-red-400" };
    default:          return { label: status.toUpperCase() || "UNKNOWN", cls: "text-gray-500" };
  }
}

function timeAgo(iso: string | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.round(diff / 60000)}m ago`;
  return `${Math.round(diff / 3600000)}h ago`;
}

function nodeRadarData(node: NodeSnapshot) {
  return [
    { subject: "Health", value: Math.round(node.health * 100) },
    { subject: "Latency", value: Math.max(0, Math.round(100 - node.avgLatencyMs / 2)) },
    { subject: "Errors", value: Math.max(0, Math.round(100 - node.errorRate * 200)) },
    { subject: "Throughput", value: Math.min(100, Math.round(node.executionsTotal / 20)) },
    { subject: "Improvement", value: Math.min(100, node.improvementCount * 12) },
  ];
}

// ── Node card ──────────────────────────────────────────────────────────────────

function NodeCard({ node }: { node: NodeSnapshot }) {
  const healthScore = Math.round(node.health * 100);
  const color = healthColor(healthScore);
  const borderCls = healthBorderCls(healthScore);
  const statusInfo = statusLabel(node.status);
  const radarData = nodeRadarData(node);

  return (
    <div className={`bg-gray-800 rounded-xl border-2 ${borderCls} p-4`}>
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-gray-400 shrink-0" />
            <span className="text-sm font-semibold text-white">{node.name}</span>
            <span className="text-xs text-gray-600 font-mono">{node.version}</span>
          </div>
          <div className="mt-0.5">
            <span className={`text-xs font-mono font-medium ${statusInfo.cls}`}>
              {statusInfo.label}
            </span>
            <span className="text-xs text-gray-600 ml-2">
              updated {timeAgo(node.lastUpdated)}
            </span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <span className="text-2xl font-bold tabular-nums" style={{ color }}>
            {healthScore}
          </span>
          <span className="text-xs text-gray-500">/100</span>
        </div>
      </div>

      {/* Radar chart */}
      <div className="h-28 -mx-2 my-1">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={radarData} margin={{ top: 2, right: 16, bottom: 2, left: 16 }}>
            <PolarGrid stroke="#374151" />
            <PolarAngleAxis dataKey="subject" tick={{ fontSize: 9, fill: "#9ca3af" }} />
            <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} axisLine={false} />
            <Radar
              dataKey="value"
              stroke={color}
              fill={color}
              fillOpacity={0.15}
              strokeWidth={1.5}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mt-1">
        <span className="text-gray-500">avg latency</span>
        <span className="font-mono text-gray-300 text-right">{node.avgLatencyMs.toFixed(0)}ms</span>
        <span className="text-gray-500">p95 latency</span>
        <span className="font-mono text-gray-300 text-right">{node.p95LatencyMs.toFixed(0)}ms</span>
        <span className="text-gray-500">error rate</span>
        <span
          className={`font-mono text-right ${node.errorRate > 0.1 ? "text-red-400" : "text-gray-300"}`}
        >
          {(node.errorRate * 100).toFixed(1)}%
        </span>
        <span className="text-gray-500">executions</span>
        <span className="font-mono text-gray-300 text-right">
          {node.executionsTotal.toLocaleString()}
        </span>
        <span className="text-gray-500">improvements</span>
        <span className="font-mono text-indigo-400 text-right">{node.improvementCount}</span>
      </div>
    </div>
  );
}

// ── Health overview bar chart ──────────────────────────────────────────────────

function HealthOverviewChart({ nodes }: { nodes: NodeSnapshot[] }) {
  const data = nodes.map((n) => ({
    name: n.name.split(" ")[0],
    health: Math.round(n.health * 100),
  }));

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Health Score Overview
      </p>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={TICK_STYLE} />
          <YAxis domain={[0, 100]} tick={TICK_STYLE} width={28} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number) => [`${v}/100`, "Health"]}
          />
          <Bar dataKey="health" radius={[3, 3, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={healthColor(d.health)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Alert row ──────────────────────────────────────────────────────────────────

function AlertRow({ alert }: { alert: Alert }) {
  const icon =
    alert.severity === "critical" ? (
      <XCircle className="w-4 h-4 text-red-400 shrink-0" />
    ) : alert.severity === "warning" ? (
      <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0" />
    ) : (
      <CheckCircle className="w-4 h-4 text-blue-400 shrink-0" />
    );

  const bgCls =
    alert.severity === "critical"
      ? "bg-red-900/20 border-red-800"
      : alert.severity === "warning"
      ? "bg-yellow-900/20 border-yellow-800"
      : "bg-blue-900/20 border-blue-800";

  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${bgCls}`}>
      {icon}
      <div className="flex-1 min-w-0">
        <span className="text-xs font-semibold text-gray-300">{alert.node}</span>
        <span className="text-xs text-gray-400 ml-2">{alert.message}</span>
      </div>
      <span className="text-xs text-gray-600 shrink-0 font-mono">
        {timeAgo(alert.triggered_at)}
      </span>
    </div>
  );
}

// ── Lifecycle timeline ─────────────────────────────────────────────────────────

function LifecycleTimeline({ nodes }: { nodes: NodeSnapshot[] }) {
  const events = nodes
    .flatMap((n) => [
      n.registeredAt
        ? { time: n.registeredAt, node: n.name, event: "registered", color: "bg-indigo-500" }
        : null,
      n.lastUpdated
        ? { time: n.lastUpdated, node: n.name, event: "last active", color: "bg-green-500" }
        : null,
    ])
    .filter(Boolean)
    .sort((a, b) => new Date(b!.time).getTime() - new Date(a!.time).getTime())
    .slice(0, 10) as { time: string; node: string; event: string; color: string }[];

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Lifecycle Timeline
      </p>
      <div className="space-y-2">
        {events.map((ev, i) => (
          <div key={i} className="flex items-center gap-3 text-xs">
            <div className={`w-2 h-2 rounded-full shrink-0 ${ev.color}`} />
            <span className="text-gray-500 font-mono w-32 shrink-0">
              {timeAgo(ev.time)}
            </span>
            <span className="text-gray-300 font-medium">{ev.node}</span>
            <span className="text-gray-500">{ev.event}</span>
          </div>
        ))}
        {events.length === 0 && (
          <p className="text-xs text-gray-600 italic">No lifecycle events</p>
        )}
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function NodeHealth() {
  const [nodes, setNodes] = useState<NodeSnapshot[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(false);
  const [fromMock, setFromMock] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);

    // Try Connect-RPC first, fall back to mock
    try {
      const res = await client.listNodes({});
      const mapped: NodeSnapshot[] = res.nodes.map((n) => ({
        nodeId: n.nodeId,
        name: n.name,
        version: n.version,
        health: n.health,
        status: n.status,
        avgLatencyMs: n.avgLatencyMs,
        p95LatencyMs: n.p95LatencyMs,
        errorRate: n.errorRate,
        executionsTotal: Number(n.executionsTotal),
        improvementCount: Number(n.improvementCount),
        registeredAt: n.registeredAt
          ? new Date(Number(n.registeredAt.seconds) * 1000).toISOString()
          : undefined,
        lastUpdated: n.lastUpdated
          ? new Date(Number(n.lastUpdated.seconds) * 1000).toISOString()
          : undefined,
      }));
      if (mapped.length > 0) {
        setNodes(mapped);
        setFromMock(false);
      } else {
        setNodes(MOCK_NODES);
        setFromMock(true);
      }
    } catch {
      setNodes(MOCK_NODES);
      setFromMock(true);
    }

    // Try to fetch alerts from adversarial endpoint
    try {
      const r = await fetch(`${BASE}/api/v1/adversarial/alerts`);
      if (r.ok) {
        const json = await r.json();
        setAlerts(json.alerts ?? MOCK_ALERTS);
      } else {
        setAlerts(MOCK_ALERTS);
      }
    } catch {
      setAlerts(MOCK_ALERTS);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const healthy = nodes.filter((n) => n.health >= 0.8).length;
  const degraded = nodes.filter((n) => n.health >= 0.5 && n.health < 0.8).length;
  const critical = nodes.filter((n) => n.health < 0.5).length;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <HeartPulse className="w-5 h-5 text-indigo-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Node Health</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Per-node health scores, latency, error rates — refreshes every 15s
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {fromMock && (
            <span className="text-xs px-2 py-1 bg-blue-900/40 text-blue-300 border border-blue-800 rounded">
              mock data
            </span>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-surface-800 border border-surface-600 rounded hover:bg-surface-700 text-gray-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Nodes", value: nodes.length, color: "text-white" },
          { label: "Healthy (≥80)", value: healthy, color: "text-green-400" },
          { label: "Degraded (50–80)", value: degraded, color: "text-yellow-400" },
          { label: "Critical (<50)", value: critical, color: "text-red-400" },
        ].map((s) => (
          <div key={s.label} className="bg-gray-800 rounded-xl border border-gray-700 px-4 py-3">
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Health overview bar chart */}
      <HealthOverviewChart nodes={nodes} />

      {/* Node cards */}
      <div>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
          Node Details
        </h2>
        {nodes.length === 0 ? (
          <div className="text-center py-12">
            <Activity className="w-8 h-8 text-gray-600 mx-auto mb-2" />
            <p className="text-sm text-gray-500">No nodes registered</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
            {nodes.map((node) => (
              <NodeCard key={node.nodeId} node={node} />
            ))}
          </div>
        )}
      </div>

      {/* Active alerts */}
      {alerts.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
            Active Alerts ({alerts.length})
          </h2>
          <div className="space-y-2">
            {alerts.map((a) => (
              <AlertRow key={a.id} alert={a} />
            ))}
          </div>
        </div>
      )}

      {/* Lifecycle timeline */}
      <LifecycleTimeline nodes={nodes} />
    </div>
  );
}
