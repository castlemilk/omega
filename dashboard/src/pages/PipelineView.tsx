import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { GitBranch, AlertTriangle, RefreshCw } from "lucide-react";

const BASE = "";

// ── Types ──────────────────────────────────────────────────────────────────

interface PipelineStep {
  id: string;
  name: string;
  status: "idle" | "running" | "complete" | "error";
  duration_ms: number;
  last_run_at: string;
  error_count: number;
  deps_on: string[];
  is_bottleneck: boolean;
}

interface PipelineResponse {
  project_id: string;
  steps: PipelineStep[];
  avg_step_ms: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  idle: "border-gray-600 bg-gray-800 text-gray-400",
  running: "border-blue-500 bg-blue-900/30 text-blue-300",
  complete: "border-green-600 bg-green-900/20 text-green-300",
  error: "border-red-600 bg-red-900/20 text-red-300",
};

const STATUS_DOT: Record<string, string> = {
  idle: "bg-gray-600",
  running: "bg-blue-400 animate-pulse",
  complete: "bg-green-400",
  error: "bg-red-400",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="flex items-center gap-1 text-xs font-medium capitalize">
      <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[status] ?? "bg-gray-500"}`} />
      {status}
    </span>
  );
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "—";
  }
}

function formatDuration(ms: number): string {
  if (ms === 0) return "—";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Step Node ──────────────────────────────────────────────────────────────

function StepNode({
  step,
  avgMs,
}: {
  step: PipelineStep;
  avgMs: number;
}) {
  const [hovered, setHovered] = useState(false);
  const borderClass = STATUS_COLORS[step.status] ?? STATUS_COLORS.idle;
  const isBottleneck = step.is_bottleneck;

  return (
    <div
      className={`relative rounded-xl border-2 p-3 transition-all cursor-default select-none
        ${borderClass}
        ${isBottleneck ? "ring-2 ring-red-500/50" : ""}
        ${hovered ? "shadow-lg scale-105" : ""}
      `}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ minWidth: 160, maxWidth: 200 }}
    >
      {isBottleneck && (
        <div className="absolute -top-2 -right-2 bg-red-500 text-white text-xs px-1 py-0.5 rounded-full font-bold">
          ⚠ slow
        </div>
      )}

      <div className="flex items-start justify-between gap-1 mb-2">
        <p className="text-xs font-semibold text-white leading-tight">{step.name}</p>
        <StatusBadge status={step.status} />
      </div>

      <div className="space-y-0.5 text-xs">
        <div className="flex items-center justify-between text-gray-500">
          <span>Duration</span>
          <span
            className={`font-mono ${isBottleneck ? "text-red-400 font-bold" : "text-gray-300"}`}
          >
            {formatDuration(step.duration_ms)}
          </span>
        </div>
        {step.error_count > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-gray-500">Errors</span>
            <span className="font-mono text-red-400 font-bold">{step.error_count}</span>
          </div>
        )}
        <div className="flex items-center justify-between text-gray-500">
          <span>Last run</span>
          <span className="font-mono text-gray-400">{formatTime(step.last_run_at)}</span>
        </div>
      </div>

      {/* Bottleneck bar indicator */}
      {avgMs > 0 && step.duration_ms > 0 && (
        <div className="mt-2">
          <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-1 rounded-full transition-all ${
                isBottleneck ? "bg-red-500" : step.duration_ms > avgMs ? "bg-amber-400" : "bg-green-500"
              }`}
              style={{ width: `${Math.min((step.duration_ms / (avgMs * 3)) * 100, 100)}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ── DAG Layout ─────────────────────────────────────────────────────────────
// Assigns columns (0-based) via topological sort

function computeColumns(steps: PipelineStep[]): Map<string, number> {
  const colMap = new Map<string, number>();
  const inDegree = new Map<string, number>();
  const childOf = new Map<string, string[]>();

  for (const s of steps) {
    inDegree.set(s.id, s.deps_on.length);
    for (const dep of s.deps_on) {
      if (!childOf.has(dep)) childOf.set(dep, []);
      childOf.get(dep)!.push(s.id);
    }
  }

  // BFS topological order
  const queue: string[] = [];
  for (const s of steps) {
    if ((inDegree.get(s.id) ?? 0) === 0) queue.push(s.id);
  }

  while (queue.length > 0) {
    const id = queue.shift()!;
    const col = colMap.get(id) ?? 0;
    for (const child of childOf.get(id) ?? []) {
      const cur = colMap.get(child) ?? 0;
      colMap.set(child, Math.max(cur, col + 1));
      const newDeg = (inDegree.get(child) ?? 1) - 1;
      inDegree.set(child, newDeg);
      if (newDeg === 0) queue.push(child);
    }
  }

  for (const s of steps) {
    if (!colMap.has(s.id)) colMap.set(s.id, 0);
  }

  return colMap;
}

// ── Arrow connector (SVG overlay) ─────────────────────────────────────────
// We draw simple arrows as text rather than SVG for simplicity

function ColumnGroup({
  steps,
  col,
  avgMs,
}: {
  steps: PipelineStep[];
  col: number;
  avgMs: number;
}) {
  return (
    <div className="flex flex-col gap-3 items-center">
      <div className="text-xs text-gray-600 mb-1">Step {col + 1}</div>
      {steps.map((step) => (
        <StepNode key={step.id} step={step} avgMs={avgMs} />
      ))}
    </div>
  );
}

// ── Summary bar ────────────────────────────────────────────────────────────

function PipelineSummary({ steps, avgMs }: { steps: PipelineStep[]; avgMs: number }) {
  const total = steps.filter((s) => s.status !== "idle").length;
  const errors = steps.filter((s) => s.status === "error").length;
  const bottlenecks = steps.filter((s) => s.is_bottleneck).length;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
      {[
        { label: "Steps", value: steps.length, accent: "text-white" },
        { label: "Active", value: total, accent: "text-blue-400" },
        { label: "Errors", value: errors, accent: errors > 0 ? "text-red-400" : "text-gray-500" },
        {
          label: "Bottlenecks",
          value: bottlenecks,
          accent: bottlenecks > 0 ? "text-amber-400" : "text-gray-500",
        },
        {
          label: "Avg step",
          value: `${avgMs.toFixed(0)}ms`,
          accent: "text-gray-300",
        },
      ].map((c) => (
        <div key={c.label} className="bg-gray-800 border border-gray-700 rounded-xl p-3">
          <p className="text-xs text-gray-500 mb-0.5">{c.label}</p>
          <p className={`text-xl font-bold ${c.accent}`}>{c.value}</p>
        </div>
      ))}
    </div>
  );
}

// ── Step List (fallback / detail table) ───────────────────────────────────

function StepList({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-700">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Step Details
        </h3>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-600 border-b border-gray-700">
            <th className="text-left px-4 py-2 font-medium">Step</th>
            <th className="text-left px-4 py-2 font-medium">Deps</th>
            <th className="text-center px-4 py-2 font-medium">Status</th>
            <th className="text-right px-4 py-2 font-medium">Duration</th>
            <th className="text-right px-4 py-2 font-medium">Errors</th>
            <th className="text-right px-4 py-2 font-medium">Last run</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((step) => (
            <tr
              key={step.id}
              className={`border-b border-gray-700/50 hover:bg-gray-700/30 transition-colors ${
                step.is_bottleneck ? "bg-red-900/10" : ""
              }`}
            >
              <td className="px-4 py-2">
                <div className="flex items-center gap-1.5">
                  {step.is_bottleneck && <AlertTriangle size={11} className="text-red-400" />}
                  <span className="text-gray-200 font-medium">{step.name}</span>
                </div>
                <p className="text-gray-600 font-mono mt-0.5">{step.id}</p>
              </td>
              <td className="px-4 py-2 text-gray-500 font-mono">
                {step.deps_on.length > 0 ? step.deps_on.join(", ") : "—"}
              </td>
              <td className="px-4 py-2 text-center">
                <StatusBadge status={step.status} />
              </td>
              <td
                className={`px-4 py-2 text-right font-mono ${
                  step.is_bottleneck ? "text-red-400 font-bold" : "text-gray-300"
                }`}
              >
                {formatDuration(step.duration_ms)}
              </td>
              <td className="px-4 py-2 text-right font-mono">
                <span className={step.error_count > 0 ? "text-red-400 font-bold" : "text-gray-600"}>
                  {step.error_count}
                </span>
              </td>
              <td className="px-4 py-2 text-right font-mono text-gray-500">
                {formatTime(step.last_run_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PipelineView() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<PipelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Default Victoria pipeline structure shown when API is unavailable
  const DEFAULT_DATA: PipelineResponse = {
    project_id: id ?? "victoria",
    avg_step_ms: 0,
    steps: [
      { id: "data_ingestion", name: "Data Ingestion", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: [], is_bottleneck: false },
      { id: "regime_detection", name: "Regime Detection", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["data_ingestion"], is_bottleneck: false },
      { id: "signal_generation", name: "Signal Generation", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["data_ingestion"], is_bottleneck: false },
      { id: "alt_data_signals", name: "Alt-Data Signals", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["data_ingestion"], is_bottleneck: false },
      { id: "factor_model", name: "Factor Model", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["signal_generation", "alt_data_signals"], is_bottleneck: false },
      { id: "meta_model", name: "Meta Model", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["factor_model", "regime_detection"], is_bottleneck: false },
      { id: "position_sizing", name: "Position Sizing", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["meta_model"], is_bottleneck: false },
      { id: "risk_management", name: "Risk Management", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["position_sizing"], is_bottleneck: false },
      { id: "reporting", name: "Reporting", status: "idle", duration_ms: 0, last_run_at: "", error_count: 0, deps_on: ["risk_management"], is_bottleneck: false },
    ],
  };

  const fetchData = useCallback(async () => {
    try {
      const url = id
        ? `${BASE}/api/v1/dashboard/obs/pipeline/${id}`
        : `${BASE}/api/v1/dashboard/obs/pipeline`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
      setData(DEFAULT_DATA);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 20000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Build column groups for DAG display
  const colMap = data ? computeColumns(data.steps) : new Map<string, number>();
  const maxCol = Math.max(0, ...Array.from(colMap.values()));
  const columns: PipelineStep[][] = Array.from({ length: maxCol + 1 }, () => []);
  if (data) {
    for (const step of data.steps) {
      const col = colMap.get(step.id) ?? 0;
      columns[col].push(step);
    }
  }

  const projectLabel = id ?? "Victoria";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <GitBranch size={20} className="text-indigo-400" />
            Signal Pipeline
            <span className="text-gray-600 font-normal text-base">· {projectLabel}</span>
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            DAG visualization of pipeline steps — red border = bottleneck (&gt;2× avg)
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-xs text-gray-600 font-mono">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-surface-700 hover:bg-surface-600 text-gray-300 rounded-lg border border-surface-600 transition-colors"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-3 text-xs text-red-400 flex items-center gap-2">
          <AlertTriangle size={13} />
          {error} — showing default Victoria pipeline structure
        </div>
      )}

      {loading && (
        <div className="text-center py-12 text-gray-600 text-sm animate-pulse">Loading pipeline…</div>
      )}

      {!loading && data && (
        <>
          {/* Summary KPIs */}
          <PipelineSummary steps={data.steps} avgMs={data.avg_step_ms} />

          {/* DAG visualization */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 overflow-x-auto">
            <div className="flex items-start gap-6 min-w-max">
              {columns.map((colSteps, colIdx) => (
                <div key={colIdx} className="flex items-start gap-0">
                  <ColumnGroup steps={colSteps} col={colIdx} avgMs={data.avg_step_ms} />
                  {/* Arrow between columns */}
                  {colIdx < columns.length - 1 && (
                    <div className="flex items-center self-center mx-2 text-gray-600">
                      <div className="w-6 h-px bg-gray-600" />
                      <div
                        className="w-0 h-0"
                        style={{
                          borderTop: "4px solid transparent",
                          borderBottom: "4px solid transparent",
                          borderLeft: "6px solid #4b5563",
                        }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap items-center gap-4 text-xs text-gray-500">
            {[
              { color: "bg-gray-600", label: "Idle" },
              { color: "bg-blue-400 animate-pulse", label: "Running" },
              { color: "bg-green-400", label: "Complete" },
              { color: "bg-red-400", label: "Error" },
            ].map((l) => (
              <span key={l.label} className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${l.color}`} />
                {l.label}
              </span>
            ))}
            <span className="flex items-center gap-1.5 ml-4">
              <span className="text-red-400 font-bold">⚠</span>
              Bottleneck (&gt;2× avg duration)
            </span>
          </div>

          {/* Detail table */}
          <StepList steps={data.steps} />
        </>
      )}
    </div>
  );
}
