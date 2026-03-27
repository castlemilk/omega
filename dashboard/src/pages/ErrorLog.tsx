import { useEffect, useState, useMemo } from "react";
import { AlertTriangle, XCircle, AlertCircle, Info, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";

const BASE = "";

// ── Types ──────────────────────────────────────────────────────────────────

interface ErrorEntry {
  id: string;
  source: string;
  severity: string;
  message: string;
  count: number;
  first_seen: string;
  last_seen: string;
}

type Window = "1h" | "4h" | "24h" | "7d";
type SeverityFilter = "all" | "error" | "warning" | "info";
type SourceFilter = "all" | "pipeline" | "adversarial" | "db" | "api";

// ── Helpers ────────────────────────────────────────────────────────────────

const SEV_ICON: Record<string, React.ElementType> = {
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const SEV_COLOR: Record<string, string> = {
  error: "text-red-400",
  warning: "text-yellow-400",
  info: "text-blue-400",
};

const SEV_BG: Record<string, string> = {
  error: "bg-red-900/20 border-red-800/50",
  warning: "bg-yellow-900/20 border-yellow-800/50",
  info: "bg-blue-900/20 border-blue-800/50",
};

const SOURCE_COLOR: Record<string, string> = {
  pipeline: "text-indigo-400",
  adversarial: "text-orange-400",
  db: "text-cyan-400",
  api: "text-purple-400",
};

const SOURCE_BG: Record<string, string> = {
  pipeline: "bg-indigo-900/30",
  adversarial: "bg-orange-900/30",
  db: "bg-cyan-900/30",
  api: "bg-purple-900/30",
};

function formatTime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function timeSince(iso: string): string {
  if (!iso) return "—";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return "—";
  }
}

// ── ErrorRow ───────────────────────────────────────────────────────────────

function ErrorRow({ entry }: { entry: ErrorEntry }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = SEV_ICON[entry.severity] ?? AlertCircle;

  return (
    <div
      className={`border rounded-xl overflow-hidden transition-colors ${SEV_BG[entry.severity] ?? "bg-gray-800 border-gray-700"}`}
    >
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors"
        onClick={() => setExpanded((e) => !e)}
      >
        {/* expand icon */}
        <span className="text-gray-600 shrink-0">
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>

        {/* severity icon */}
        <Icon size={15} className={`shrink-0 ${SEV_COLOR[entry.severity] ?? "text-gray-400"}`} />

        {/* source badge */}
        <span
          className={`text-xs font-mono px-1.5 py-0.5 rounded shrink-0 ${SOURCE_BG[entry.source] ?? "bg-gray-700"} ${SOURCE_COLOR[entry.source] ?? "text-gray-400"}`}
        >
          {entry.source}
        </span>

        {/* message */}
        <span className="text-sm text-gray-200 flex-1 truncate font-mono">{entry.message}</span>

        {/* count badge */}
        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-300 font-semibold shrink-0">
          ×{entry.count}
        </span>

        {/* last seen */}
        <span className="text-xs text-gray-500 shrink-0">{timeSince(entry.last_seen)}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-3 border-t border-gray-700/50 pt-3 space-y-2">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
            <div>
              <span className="text-gray-500">Error ID</span>
              <p className="text-gray-300 font-mono mt-0.5">{entry.id}</p>
            </div>
            <div>
              <span className="text-gray-500">Count</span>
              <p className="text-gray-300 font-mono mt-0.5">{entry.count}</p>
            </div>
            <div>
              <span className="text-gray-500">First seen</span>
              <p className="text-gray-300 font-mono mt-0.5">{formatTime(entry.first_seen)}</p>
            </div>
            <div>
              <span className="text-gray-500">Last seen</span>
              <p className="text-gray-300 font-mono mt-0.5">{formatTime(entry.last_seen)}</p>
            </div>
          </div>
          <div className="mt-2">
            <span className="text-xs text-gray-500">Full message</span>
            <pre className="mt-1 bg-gray-900 rounded-lg px-3 py-2 text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">
              {entry.message}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

const WINDOWS: { label: string; value: Window }[] = [
  { label: "1h", value: "1h" },
  { label: "4h", value: "4h" },
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
];

export default function ErrorLog() {
  const [errors, setErrors] = useState<ErrorEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [window, setWindow] = useState<Window>("24h");
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");

  async function fetchData(win: Window) {
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/api/v1/dashboard/obs/errors?window=${win}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setErrors(Array.isArray(json) ? json : []);
      setLastUpdated(new Date());
      setFetchError(null);
    } catch (e) {
      setFetchError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData(window);
  }, [window]);

  const filtered = useMemo(() => {
    return errors.filter((e) => {
      if (severityFilter !== "all" && e.severity !== severityFilter) return false;
      if (sourceFilter !== "all" && e.source !== sourceFilter) return false;
      return true;
    });
  }, [errors, severityFilter, sourceFilter]);

  // Stats
  const stats = useMemo(() => {
    const bySev: Record<string, number> = {};
    const bySrc: Record<string, number> = {};
    for (const e of errors) {
      bySev[e.severity] = (bySev[e.severity] ?? 0) + e.count;
      bySrc[e.source] = (bySrc[e.source] ?? 0) + e.count;
    }
    return { bySev, bySrc, total: errors.reduce((s, e) => s + e.count, 0) };
  }, [errors]);

  const sources = useMemo(
    () => Array.from(new Set(errors.map((e) => e.source))).sort(),
    [errors]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <XCircle size={20} className="text-red-400" />
            Error Log
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Aggregated errors grouped by source and severity
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => fetchData(window)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-surface-700 hover:bg-surface-600 text-gray-300 rounded-lg border border-surface-600 transition-colors"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        </div>
      </div>

      {fetchError && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-3 text-xs text-red-400 flex items-center gap-2">
          <AlertTriangle size={13} />
          Backend unavailable ({fetchError})
        </div>
      )}

      {/* Stats row */}
      {errors.length > 0 && (
        <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
          {(["error", "warning", "info"] as const).map((sev) => {
            const Icon = SEV_ICON[sev];
            return (
              <div key={sev} className="bg-gray-800 border border-gray-700 rounded-xl p-3">
                <div className={`flex items-center gap-1.5 mb-1 ${SEV_COLOR[sev]}`}>
                  <Icon size={13} />
                  <span className="text-xs font-semibold capitalize">{sev}</span>
                </div>
                <p className="text-xl font-bold text-white">{(stats.bySev[sev] ?? 0).toLocaleString()}</p>
              </div>
            );
          })}
          {sources.slice(0, 3).map((src) => (
            <div key={src} className="bg-gray-800 border border-gray-700 rounded-xl p-3">
              <div className={`text-xs font-semibold mb-1 ${SOURCE_COLOR[src] ?? "text-gray-400"}`}>
                {src}
              </div>
              <p className="text-xl font-bold text-white">{(stats.bySrc[src] ?? 0).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Time window */}
        <div className="flex rounded-lg border border-gray-700 overflow-hidden text-xs">
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              onClick={() => setWindow(w.value)}
              className={`px-3 py-1.5 font-medium transition-colors ${
                window === w.value
                  ? "bg-indigo-600 text-white"
                  : "bg-surface-700 text-gray-400 hover:text-white"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>

        {/* Severity filter */}
        <div className="flex rounded-lg border border-gray-700 overflow-hidden text-xs">
          {(["all", "error", "warning", "info"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setSeverityFilter(f)}
              className={`px-3 py-1.5 font-medium capitalize transition-colors ${
                severityFilter === f
                  ? "bg-surface-600 text-white"
                  : "bg-surface-700 text-gray-400 hover:text-white"
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Source filter */}
        {sources.length > 1 && (
          <div className="flex rounded-lg border border-gray-700 overflow-hidden text-xs">
            <button
              onClick={() => setSourceFilter("all")}
              className={`px-3 py-1.5 font-medium transition-colors ${
                sourceFilter === "all"
                  ? "bg-surface-600 text-white"
                  : "bg-surface-700 text-gray-400 hover:text-white"
              }`}
            >
              all sources
            </button>
            {sources.map((src) => (
              <button
                key={src}
                onClick={() => setSourceFilter(src as SourceFilter)}
                className={`px-3 py-1.5 font-medium capitalize transition-colors ${
                  sourceFilter === src
                    ? "bg-surface-600 text-white"
                    : "bg-surface-700 text-gray-400 hover:text-white"
                }`}
              >
                {src}
              </button>
            ))}
          </div>
        )}

        <span className="text-xs text-gray-600 ml-auto">
          {filtered.length} of {errors.length} entries
        </span>
      </div>

      {/* Error list */}
      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">
          Loading errors…
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-gray-600">
          <AlertCircle size={32} className="mb-3 opacity-40" />
          <p className="text-sm">
            {errors.length === 0
              ? `No errors recorded in the last ${window}`
              : "No errors match the current filters"}
          </p>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="space-y-2">
          {filtered.map((entry) => (
            <ErrorRow key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
