import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Radio,
  TrendingUp,
  XCircle,
  Cpu,
  BarChart2,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

const API = "http://localhost:8080";

// ── Types ──────────────────────────────────────────────────────────────────

interface NodeStatus {
  node_id: string;
  node_type: string;
  health: "healthy" | "degraded" | "stale" | "dead" | "unknown";
  last_seen: string; // RFC3339
  metrics: Record<string, string>;
  blockers: string[];
  stale: boolean;
}

interface Diagnostics {
  available?: boolean;
  node_id: string;
  cycle: number;
  regime: string;
  data_freshness_seconds: number;
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

interface BlockersResponse {
  node_id: string;
  blockers: string[];
}

// ── Style helpers ──────────────────────────────────────────────────────────

const HEALTH_COLOR: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-yellow-400",
  stale: "text-orange-400",
  dead: "text-red-400",
  unknown: "text-gray-500",
};

const HEALTH_BG: Record<string, string> = {
  healthy: "bg-green-900/30 border-green-800",
  degraded: "bg-yellow-900/30 border-yellow-800",
  stale: "bg-orange-900/30 border-orange-800",
  dead: "bg-red-900/30 border-red-800",
  unknown: "bg-gray-800 border-gray-700",
};

const HEALTH_DOT: Record<string, string> = {
  healthy: "bg-green-400 animate-pulse",
  degraded: "bg-yellow-400 animate-pulse",
  stale: "bg-orange-400",
  dead: "bg-red-600",
  unknown: "bg-gray-500",
};

function HealthIcon({ health }: { health: string }) {
  if (health === "healthy") return <CheckCircle size={14} className="text-green-400 shrink-0" />;
  if (health === "dead") return <XCircle size={14} className="text-red-400 shrink-0" />;
  if (health === "stale") return <Clock size={14} className="text-orange-400 shrink-0" />;
  if (health === "degraded") return <AlertTriangle size={14} className="text-yellow-400 shrink-0" />;
  return <Activity size={14} className="text-gray-500 shrink-0" />;
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const now = Date.now();
    const diffS = Math.floor((now - d.getTime()) / 1000);
    if (diffS < 60) return `${diffS}s ago`;
    if (diffS < 3600) return `${Math.floor(diffS / 60)}m ago`;
    return d.toLocaleTimeString();
  } catch {
    return "—";
  }
}

// ── BlockersBanner ─────────────────────────────────────────────────────────

function BlockersBanner({ blockers }: { blockers: BlockersResponse[] }) {
  const all = blockers.flatMap((b) => b.blockers.map((msg) => ({ node: b.node_id, msg })));
  if (all.length === 0) return null;
  return (
    <div className="bg-red-900/40 border border-red-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle size={16} className="text-red-400 shrink-0" />
        <span className="text-sm font-semibold text-red-300 uppercase tracking-wide">
          {all.length} Active Blocker{all.length !== 1 ? "s" : ""}
        </span>
      </div>
      <ul className="space-y-1">
        {all.map((b, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-red-300">
            <span className="font-mono text-red-500 shrink-0">[{b.node}]</span>
            <span>{b.msg}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── NodeCard ───────────────────────────────────────────────────────────────

function NodeCard({ node }: { node: NodeStatus }) {
  const health = node.health in HEALTH_BG ? node.health : "unknown";
  return (
    <div className={`rounded-xl border p-4 space-y-3 ${HEALTH_BG[health]}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Cpu size={15} className="text-gray-400 shrink-0" />
          <span className="font-semibold text-sm text-white truncate">{node.node_id}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`w-2 h-2 rounded-full ${HEALTH_DOT[health]}`} />
          <span className={`text-xs font-medium uppercase ${HEALTH_COLOR[health]}`}>
            {node.health}
          </span>
        </div>
      </div>

      {/* Type + last seen */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-gray-500">Type</p>
          <p className="text-gray-300 font-mono">{node.node_type || "—"}</p>
        </div>
        <div>
          <p className="text-gray-500">Last heartbeat</p>
          <p className={`font-mono ${node.stale ? "text-orange-400" : "text-gray-300"}`}>
            {formatTime(node.last_seen)}
            {node.stale && <span className="ml-1 text-orange-500">(stale)</span>}
          </p>
        </div>
      </div>

      {/* Extra metrics */}
      {Object.keys(node.metrics ?? {}).length > 0 && (
        <div className="grid grid-cols-2 gap-1.5 text-xs border-t border-white/5 pt-2">
          {Object.entries(node.metrics).map(([k, v]) => (
            <div key={k}>
              <p className="text-gray-600 truncate">{k}</p>
              <p className="text-gray-400 font-mono truncate">{v}</p>
            </div>
          ))}
        </div>
      )}

      {/* Per-node blockers */}
      {node.blockers.length > 0 && (
        <div className="border-t border-red-800/50 pt-2 space-y-1">
          {node.blockers.map((b, i) => (
            <p key={i} className="text-xs text-red-400 font-mono">⚠ {b}</p>
          ))}
        </div>
      )}
    </div>
  );
}

// ── DiagnosticsPanel ───────────────────────────────────────────────────────

function DiagnosticsPanel({ diag }: { diag: Diagnostics | null }) {
  if (!diag || diag.available === false) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 text-center">
        <Radio size={24} className="text-gray-600 mx-auto mb-2" />
        <p className="text-sm text-gray-600">No training diagnostics received yet</p>
      </div>
    );
  }

  const signalPct = diag.total_signals > 0
    ? Math.round((diag.active_signals / diag.total_signals) * 100)
    : 0;

  const totalPositions = diag.longs + diag.shorts;
  const longPct = totalPositions > 0 ? Math.round((diag.longs / totalPositions) * 100) : 50;

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-indigo-400" />
          <h3 className="text-sm font-semibold text-white">Training Diagnostics</h3>
        </div>
        <div className="flex items-center gap-2">
          {diag.sit_out && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-900/50 text-yellow-400 border border-yellow-800">
              SIT-OUT
            </span>
          )}
          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-900/40 text-indigo-300 font-mono border border-indigo-800">
            Cycle #{diag.cycle}
          </span>
          <span className="text-xs text-gray-600 font-mono">{formatTime(diag.timestamp)}</span>
        </div>
      </div>

      {/* Sit-out reason */}
      {diag.sit_out && diag.sit_out_reason && (
        <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-lg px-3 py-2 text-xs text-yellow-400">
          {diag.sit_out_reason}
        </div>
      )}

      {/* Stat grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-gray-900/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Regime</p>
          <p className="text-sm font-bold text-white uppercase">{diag.regime || "—"}</p>
        </div>
        <div className="bg-gray-900/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Signals</p>
          <p className="text-sm font-bold text-white">
            {diag.active_signals}
            <span className="text-gray-600 font-normal text-xs">/{diag.total_signals}</span>
            <span className="text-indigo-400 text-xs ml-1">({signalPct}%)</span>
          </p>
        </div>
        <div className="bg-gray-900/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">PnL</p>
          <p className={`text-sm font-bold ${diag.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
            {diag.pnl >= 0 ? "+" : ""}{diag.pnl.toFixed(4)}
          </p>
        </div>
        <div className="bg-gray-900/60 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Data age</p>
          <p className={`text-sm font-bold ${diag.data_freshness_seconds > 300 ? "text-orange-400" : "text-gray-200"}`}>
            {diag.data_freshness_seconds.toFixed(0)}s
          </p>
        </div>
      </div>

      {/* Trades row */}
      <div className="grid grid-cols-3 gap-3 text-xs">
        <div className="bg-gray-900/60 rounded-lg p-3 flex items-center justify-between">
          <span className="text-gray-500">Open trades</span>
          <span className="font-mono font-semibold text-gray-200">{diag.open_trades}</span>
        </div>
        <div className="bg-gray-900/60 rounded-lg p-3 flex items-center justify-between">
          <span className="text-gray-500">Closed trades</span>
          <span className="font-mono font-semibold text-gray-200">{diag.closed_trades}</span>
        </div>
        <div className="bg-gray-900/60 rounded-lg p-3">
          <p className="text-gray-500 mb-1.5">Long / Short</p>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-0.5 text-green-400 font-mono font-semibold">
              <ArrowUpRight size={11} />{diag.longs}
            </span>
            <span className="text-gray-600">/</span>
            <span className="flex items-center gap-0.5 text-red-400 font-mono font-semibold">
              <ArrowDownRight size={11} />{diag.shorts}
            </span>
            {totalPositions > 0 && (
              <span className="text-gray-600 text-xs ml-auto">{longPct}% L</span>
            )}
          </div>
        </div>
      </div>

      {/* Ticker convictions */}
      {Object.keys(diag.ticker_convictions ?? {}).length > 0 && (
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-widest mb-2">Ticker Convictions</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(diag.ticker_convictions)
              .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
              .slice(0, 10)
              .map(([ticker, conviction]) => (
                <div
                  key={ticker}
                  className={`text-xs px-2 py-1 rounded font-mono border ${
                    conviction > 0
                      ? "bg-green-900/30 border-green-800 text-green-300"
                      : "bg-red-900/30 border-red-800 text-red-300"
                  }`}
                >
                  {ticker}{" "}
                  <span className="opacity-70">
                    {conviction > 0 ? "+" : ""}{conviction.toFixed(3)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Diagnostic blockers */}
      {diag.blockers.length > 0 && (
        <div className="border-t border-gray-700 pt-3 space-y-1">
          <p className="text-xs text-gray-500 uppercase tracking-widest mb-1.5">Blockers</p>
          {diag.blockers.map((b, i) => (
            <p key={i} className="text-xs text-red-400 font-mono">⚠ {b}</p>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function ControlPlane() {
  const [nodes, setNodes] = useState<NodeStatus[]>([]);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [blockers, setBlockers] = useState<BlockersResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchAll() {
    try {
      const [nodesRes, diagRes, blockersRes] = await Promise.all([
        fetch(`${API}/api/v1/nodes`),
        fetch(`${API}/api/v1/diagnostics`),
        fetch(`${API}/api/v1/blockers`),
      ]);

      if (nodesRes.ok) setNodes(await nodesRes.json());
      if (diagRes.ok) setDiag(await diagRes.json());
      if (blockersRes.ok) setBlockers(await blockersRes.json());

      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => clearInterval(id);
  }, []);

  const healthyCount = nodes.filter((n) => n.health === "healthy").length;
  const deadCount = nodes.filter((n) => n.health === "dead").length;
  const totalBlockers = blockers.reduce((s, b) => s + b.blockers.length, 0);

  const overallHealth =
    deadCount > 0 ? "dead"
    : nodes.some((n) => n.stale || n.health === "stale") ? "stale"
    : nodes.some((n) => n.health === "degraded") ? "degraded"
    : nodes.length > 0 ? "healthy"
    : "unknown";

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Radio size={20} className="text-indigo-400" />
            Control Plane
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Node heartbeats, training diagnostics, and system blockers
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
              HEALTH_BG[overallHealth] ?? "bg-gray-800 border-gray-700"
            } ${HEALTH_COLOR[overallHealth]}`}
          >
            <HealthIcon health={overallHealth} />
            {overallHealth}
          </div>
        </div>
      </div>

      {/* Error strip */}
      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-3 text-xs text-red-400 flex items-center gap-2">
          <AlertTriangle size={13} className="shrink-0" />
          API unreachable — polling {API} ({error})
        </div>
      )}

      {/* Blockers banner */}
      {!loading && <BlockersBanner blockers={blockers} />}

      {/* Summary stat row */}
      {!loading && nodes.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Total nodes", value: nodes.length, color: "text-gray-200" },
            { label: "Healthy", value: healthyCount, color: "text-green-400" },
            { label: "Dead / stale", value: deadCount + nodes.filter((n) => n.stale).length, color: deadCount > 0 ? "text-red-400" : "text-gray-400" },
            { label: "Blockers", value: totalBlockers, color: totalBlockers > 0 ? "text-red-400" : "text-gray-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-gray-800 border border-gray-700 rounded-xl p-4">
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Connecting to control plane…
        </div>
      )}

      {!loading && (
        <>
          {/* Training Diagnostics */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <BarChart2 size={14} className="text-gray-500" />
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                Training Diagnostics
              </h2>
            </div>
            <DiagnosticsPanel diag={diag} />
          </section>

          {/* Node grid */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <Cpu size={14} className="text-gray-500" />
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
                Nodes ({nodes.length})
              </h2>
            </div>
            {nodes.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {nodes.map((n) => (
                  <NodeCard key={n.node_id} node={n} />
                ))}
              </div>
            ) : (
              <div className="bg-gray-800 border border-gray-700 rounded-xl p-8 text-center">
                <Cpu size={24} className="text-gray-600 mx-auto mb-2" />
                <p className="text-sm text-gray-600">No nodes reporting heartbeats yet</p>
                <p className="text-xs text-gray-700 mt-1">
                  Nodes send heartbeats via POST /api/v1/heartbeat
                </p>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
