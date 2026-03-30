import { useEffect, useRef, useState } from "react";
import { Zap, AlertTriangle } from "lucide-react";

const BASE = "";

// ── Types ──────────────────────────────────────────────────────────────────────

interface SignalInfo {
  name: string;
  last_value: number;
  non_zero: boolean;
  error_count: number;
  last_run_at: string;
  duration_ms: number;
}

interface ServicesResponse {
  signal_health: SignalInfo[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

type TileState = "active" | "low_ic" | "inactive" | "error";

function getTileState(sig: SignalInfo): TileState {
  if (sig.error_count > 0 && !sig.non_zero) return "error";
  if (!sig.non_zero || sig.last_value === 0) return "inactive";
  if (Math.abs(sig.last_value) < 0.05) return "low_ic";
  return "active";
}

const TILE_STYLES: Record<
  TileState,
  { bg: string; border: string; dot: string; label: string; textColor: string; sparkColor: string }
> = {
  active: {
    bg: "bg-green-900/20",
    border: "border-green-800/50",
    dot: "bg-green-400",
    label: "active",
    textColor: "text-green-400",
    sparkColor: "#4ade80",
  },
  low_ic: {
    bg: "bg-yellow-900/20",
    border: "border-yellow-800/50",
    dot: "bg-yellow-400",
    label: "low IC",
    textColor: "text-yellow-400",
    sparkColor: "#facc15",
  },
  inactive: {
    bg: "bg-gray-800",
    border: "border-gray-700",
    dot: "bg-gray-500",
    label: "inactive",
    textColor: "text-gray-500",
    sparkColor: "#6b7280",
  },
  error: {
    bg: "bg-red-900/20",
    border: "border-red-800/50",
    dot: "bg-red-400",
    label: "error",
    textColor: "text-red-400",
    sparkColor: "#f87171",
  },
};

function formatTime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "—";
  }
}

function timeSince(iso: string): string {
  if (!iso) return "—";
  try {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  } catch {
    return "—";
  }
}

// ── Sparkline (inline SVG polyline) ───────────────────────────────────────────

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) {
    return (
      <div className="h-10 flex items-center justify-center text-gray-600 text-xs">
        — not enough data —
      </div>
    );
  }
  const w = 200;
  const h = 40;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      width="100%"
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="overflow-visible"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* Zero line */}
      {min < 0 && max > 0 && (
        <line
          x1="0"
          y1={(h - ((0 - min) / range) * (h - 4) - 2).toFixed(1)}
          x2={w}
          y2={(h - ((0 - min) / range) * (h - 4) - 2).toFixed(1)}
          stroke="#374151"
          strokeWidth="1"
          strokeDasharray="3 3"
        />
      )}
    </svg>
  );
}

// ── Signal Tile ────────────────────────────────────────────────────────────────

function SignalTile({
  sig,
  selected,
  onClick,
}: {
  sig: SignalInfo;
  selected: boolean;
  onClick: () => void;
}) {
  const state = getTileState(sig);
  const styles = TILE_STYLES[state];
  // Shorten long signal names for display
  const displayName = sig.name.replace(/_signal$/, "").replace(/_/g, " ");

  return (
    <button
      onClick={onClick}
      className={`rounded-xl border p-3 text-left transition-all w-full ${styles.bg} ${styles.border} ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1 ring-offset-gray-900" : "hover:ring-1 hover:ring-gray-600"
      }`}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`w-2 h-2 rounded-full shrink-0 ${styles.dot}`} />
        <span className={`text-xs font-semibold uppercase tracking-wide ${styles.textColor}`}>
          {styles.label}
        </span>
      </div>
      <p className="text-xs font-mono text-gray-300 truncate leading-tight" title={sig.name}>
        {displayName}
      </p>
      <p className="text-xs font-mono text-gray-500 mt-1">
        {sig.last_value !== 0 ? sig.last_value.toFixed(4) : "0.0000"}
      </p>
    </button>
  );
}

// ── Detail Panel ───────────────────────────────────────────────────────────────

function SignalDetail({
  sig,
  history,
  onClose,
}: {
  sig: SignalInfo;
  history: number[];
  onClose: () => void;
}) {
  const state = getTileState(sig);
  const styles = TILE_STYLES[state];

  return (
    <div className="bg-gray-800 border border-indigo-700/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-white font-mono">{sig.name}</h2>
          <p className="text-xs text-gray-500 mt-0.5">Signal detail</p>
        </div>
        <button
          onClick={onClose}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded border border-gray-700"
        >
          Close ✕
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
        <div>
          <p className="text-gray-500">Last value</p>
          <p className="font-mono font-semibold text-white text-lg mt-0.5">
            {sig.last_value.toFixed(6)}
          </p>
        </div>
        <div>
          <p className="text-gray-500">Status</p>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={`w-2 h-2 rounded-full ${styles.dot}`} />
            <span className={`font-semibold ${styles.textColor}`}>{styles.label}</span>
          </div>
        </div>
        <div>
          <p className="text-gray-500">Duration</p>
          <p className="font-mono text-gray-300 mt-0.5">{sig.duration_ms.toFixed(0)}ms</p>
        </div>
        <div>
          <p className="text-gray-500">Last run</p>
          <p className="font-mono text-gray-300 mt-0.5">{formatTime(sig.last_run_at)}</p>
          <p className="font-mono text-gray-600 mt-0.5">{timeSince(sig.last_run_at)}</p>
        </div>
      </div>

      {/* Sparkline history */}
      <div>
        <p className="text-xs text-gray-500 mb-2 uppercase tracking-widest font-semibold">
          Value history ({history.length} readings)
        </p>
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-3">
          <Sparkline values={history} color={styles.sparkColor} />
        </div>
        {history.length >= 2 && (
          <div className="flex justify-between text-xs font-mono text-gray-600 mt-1">
            <span>min: {Math.min(...history).toFixed(4)}</span>
            <span>max: {Math.max(...history).toFixed(4)}</span>
          </div>
        )}
      </div>

      {sig.error_count > 0 && (
        <div className="text-xs text-red-400 font-mono flex items-center gap-1.5">
          <AlertTriangle size={11} />
          {sig.error_count} error{sig.error_count !== 1 ? "s" : ""} recorded
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function SignalHealth() {
  const [signals, setSignals] = useState<SignalInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Rolling history: signal name → last 30 values
  const historyRef = useRef<Record<string, number[]>>({});

  async function fetchSignals() {
    try {
      const res = await fetch(`${BASE}/api/v1/dashboard/obs/services`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: ServicesResponse = await res.json();
      const sigs = json.signal_health ?? [];

      // Update rolling history (keep last 30)
      const h = historyRef.current;
      for (const sig of sigs) {
        if (!h[sig.name]) h[sig.name] = [];
        h[sig.name] = [...h[sig.name], sig.last_value].slice(-30);
      }

      setSignals(sigs);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchSignals();
    const id = setInterval(fetchSignals, 5000);
    return () => clearInterval(id);
  }, []);

  const countByState = (state: TileState) =>
    signals.filter((s) => getTileState(s) === state).length;

  const selectedSig = signals.find((s) => s.name === selected) ?? null;
  const selectedHistory = selected ? (historyRef.current[selected] ?? []) : [];

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Zap size={20} className="text-indigo-400" />
            Signal Health
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Live signal pipeline status — click a tile to inspect history
          </p>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          {/* Legend */}
          <div className="flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400" />
              <span className="text-gray-400">Active ({countByState("active")})</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-yellow-400" />
              <span className="text-gray-400">Low IC ({countByState("low_ic")})</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-gray-500" />
              <span className="text-gray-400">Inactive ({countByState("inactive")})</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-400" />
              <span className="text-gray-400">Error ({countByState("error")})</span>
            </span>
          </div>
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-sm text-red-400 flex items-center gap-2">
          <AlertTriangle size={14} />
          Backend unavailable ({error})
        </div>
      )}

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Loading signal data…
        </div>
      )}

      {!loading && signals.length === 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-8 text-center text-sm text-gray-600">
          No signal data — run a training cycle to populate signal health
        </div>
      )}

      {!loading && signals.length > 0 && (
        <>
          {/* Heatmap grid */}
          <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
            {signals.map((sig) => (
              <SignalTile
                key={sig.name}
                sig={sig}
                selected={selected === sig.name}
                onClick={() => setSelected(selected === sig.name ? null : sig.name)}
              />
            ))}
          </div>

          {/* Detail panel for selected signal */}
          {selectedSig && (
            <SignalDetail
              sig={selectedSig}
              history={selectedHistory}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}
    </div>
  );
}
