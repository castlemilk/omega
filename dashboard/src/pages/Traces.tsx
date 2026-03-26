import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { client } from "../client";
import TraceWaterfall from "../components/TraceWaterfall";
import type { TraceSummary, Span, Node } from "../gen/omega/v1/types_pb";

type ViewMode = "waterfall" | "timeline" | "groups";
type TimeRange = "1h" | "4h" | "24h" | "all";

const PAGE_SIZE = 20;

// Skeleton block for loading state
function SkeletonBar({ width = "100%", height = 12 }: { width?: string; height?: number }) {
  return (
    <div
      className="rounded"
      style={{
        width,
        height,
        background: "rgba(100,116,139,0.2)",
        animation: "pulse 1.4s ease-in-out infinite",
      }}
    />
  );
}

// Gantt-style pipeline timeline
function PipelineTimeline({ spans }: { spans: Span[] }) {
  if (spans.length === 0) return null;

  const totalMs = spans.reduce((s, sp) => s + sp.durationMs, 0) || 1;
  const sorted = [...spans].sort((a, b) => b.durationMs - a.durationMs);

  return (
    <div className="space-y-1 font-mono">
      <div className="flex items-center gap-4 text-[10px] text-gray-500 mb-3 pb-2 border-b border-gray-700">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-indigo-500" />
          <span>success</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-red-500" />
          <span>error</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-amber-500" />
          <span>&gt;100ms</span>
        </div>
        <span className="ml-auto text-gray-600">total: {totalMs.toFixed(1)}ms</span>
      </div>

      {sorted.map((span, i) => {
        const pct = Math.max(2, (span.durationMs / totalMs) * 100);
        const ok = span.status !== "error";
        const barColor = !ok
          ? "bg-red-500"
          : span.durationMs > 100
            ? "bg-amber-500"
            : "bg-indigo-500";
        return (
          <div key={i} className="group flex items-center gap-2 py-0.5">
            <div
              className="shrink-0 text-right text-[9px] text-gray-400 truncate"
              style={{ width: 130 }}
              title={`${span.nodeName} · ${span.operation}`}
            >
              <span className="text-gray-300">{span.operation}</span>
            </div>
            <div className="flex-1 relative h-5 bg-gray-900 border border-gray-700 rounded-sm overflow-hidden">
              <div
                className={`absolute top-0 h-full ${barColor} opacity-80 transition-all`}
                style={{ left: 0, width: `${pct}%` }}
              />
              <span className="absolute inset-0 flex items-center px-1.5 text-[8px] font-mono text-white/80 pointer-events-none">
                {span.durationMs.toFixed(1)}ms
              </span>
            </div>
            <div
              className={`shrink-0 text-[8px] px-1.5 py-0.5 rounded border ${
                ok ? "text-green-400 border-green-800" : "text-red-400 border-red-800"
              }`}
              style={{ minWidth: 36, textAlign: "center" }}
            >
              {ok ? "OK" : "ERR"}
            </div>
          </div>
        );
      })}

      <div className="mt-3 pt-2 border-t border-gray-700 text-[9px] text-gray-500 flex gap-6">
        <span>{spans.length} spans</span>
        <span>
          {spans.filter((s) => s.status !== "error").length} ok /{" "}
          <span className="text-red-400">{spans.filter((s) => s.status === "error").length} err</span>
        </span>
        <span>
          avg: <span className="text-indigo-400">{(totalMs / spans.length).toFixed(1)}ms</span>
        </span>
        <span>
          max:{" "}
          <span className="text-amber-400">
            {Math.max(...spans.map((s) => s.durationMs)).toFixed(1)}ms
          </span>
        </span>
      </div>
    </div>
  );
}

// Group spans by service/operation for collapsible display
type SpanGroup = { key: string; spans: Span[]; collapsed: boolean };

function groupSpans(spans: Span[]): SpanGroup[] {
  const map = new Map<string, Span[]>();
  for (const span of spans) {
    const key = span.nodeName || "unknown";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(span);
  }
  return Array.from(map.entries()).map(([key, s]) => ({ key, spans: s, collapsed: false }));
}

function CollapsibleGroups({ spans }: { spans: Span[] }) {
  const [groups, setGroups] = useState<SpanGroup[]>(() => groupSpans(spans));

  useEffect(() => {
    setGroups(groupSpans(spans));
  }, [spans]);

  function toggle(idx: number) {
    setGroups((g) => g.map((grp, i) => (i === idx ? { ...grp, collapsed: !grp.collapsed } : grp)));
  }

  if (groups.length === 0) return <p className="text-gray-600 text-sm text-center py-8">No spans</p>;

  return (
    <div className="space-y-2">
      {groups.map((grp, i) => {
        const errCount = grp.spans.filter((s) => s.status === "error").length;
        const totalMs = grp.spans.reduce((s, sp) => s + sp.durationMs, 0);
        return (
          <div key={grp.key} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(i)}
              className="w-full flex items-center gap-3 px-3 py-2 bg-gray-850 hover:bg-gray-700/60 transition-colors text-left"
            >
              <span className="text-[10px] text-gray-400 font-mono w-3">{grp.collapsed ? "▶" : "▼"}</span>
              <span className="text-xs font-semibold text-gray-200 flex-1 truncate">{grp.key}</span>
              <span className="text-[10px] text-gray-500 font-mono">{grp.spans.length} spans</span>
              <span className="text-[10px] text-indigo-400 font-mono">{totalMs.toFixed(0)}ms</span>
              {errCount > 0 && (
                <span className="text-[10px] text-red-400 font-mono">{errCount} err</span>
              )}
            </button>
            {!grp.collapsed && (
              <div className="px-3 py-2 bg-gray-900/40 space-y-1">
                {grp.spans.map((span, j) => (
                  <div key={j} className="flex items-center gap-2 text-[10px] font-mono">
                    <span className={span.status !== "error" ? "text-green-400" : "text-red-400"}>
                      {span.status !== "error" ? "✓" : "✗"}
                    </span>
                    <span className="text-gray-300 flex-1 truncate">{span.operation}</span>
                    <span className="text-indigo-400">{span.durationMs.toFixed(1)}ms</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function filterByTimeRange(traces: TraceSummary[], range: TimeRange): TraceSummary[] {
  if (range === "all") return traces;
  const now = Date.now();
  const cutoffMs = range === "1h" ? 3600_000 : range === "4h" ? 14400_000 : 86400_000;
  return traces.filter((t) => {
    if (!t.traceStarted) return true;
    const ts = Number(t.traceStarted.seconds) * 1000;
    return now - ts <= cutoffMs;
  });
}

export default function Traces() {
  const [searchParams] = useSearchParams();
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodeFilter, setNodeFilter] = useState("");
  const [traceSearch, setTraceSearch] = useState("");
  const [spansLoading, setSpansLoading] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("waterfall");
  const [timeRange, setTimeRange] = useState<TimeRange>("all");
  const [page, setPage] = useState(0);

  useEffect(() => {
    client.listNodes({}).then((r) => setNodes(r.nodes)).catch(console.error);
  }, []);

  useEffect(() => {
    client
      .listTraces({ limit: 200, nodeFilter })
      .then((r) => setTraces(r.traces))
      .catch(console.error);
    setPage(0);
  }, [nodeFilter]);

  // Apply time range + search filters
  const timeFiltered = filterByTimeRange(traces, timeRange);
  const visibleTraces = traceSearch
    ? timeFiltered.filter((t) => t.traceId.startsWith(traceSearch))
    : timeFiltered;

  const totalPages = Math.ceil(visibleTraces.length / PAGE_SIZE);
  const pagedTraces = visibleTraces.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Reset page when filters change
  useEffect(() => { setPage(0); }, [traceSearch, timeRange, nodeFilter]);

  function selectTrace(id: string) {
    setSelected(id);
    setSpans([]);
    setSpansLoading(true);
    client
      .getTrace({ traceId: id })
      .then((r) => setSpans(r.spans))
      .catch(console.error)
      .finally(() => setSpansLoading(false));
  }

  function clearSelection() {
    setSelected(null);
    setSpans([]);
  }

  useEffect(() => {
    const targetId = searchParams.get("traceId");
    if (!targetId) return;
    client
      .getTrace({ traceId: targetId })
      .then((r) => { setSelected(targetId); setSpans(r.spans); })
      .catch(console.error);
  }, [searchParams]);

  return (
    <div className="flex gap-4 h-full">
      {/* Left panel: filters + list */}
      <div className="w-72 shrink-0 flex flex-col bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        {/* Filter bar */}
        <div className="p-2 border-b border-gray-700 space-y-1.5">
          {/* Time range filter */}
          <div className="flex gap-1">
            {(["1h", "4h", "24h", "all"] as TimeRange[]).map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`flex-1 text-[10px] font-mono py-1 rounded transition-colors ${
                  timeRange === r
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-900 text-gray-500 hover:text-gray-300 border border-gray-700"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <input
            type="text"
            placeholder="Search trace ID…"
            value={traceSearch}
            onChange={(e) => setTraceSearch(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 text-xs font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition-colors"
          />
          <select
            value={nodeFilter}
            onChange={(e) => setNodeFilter(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded-md px-2 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-indigo-500 transition-colors"
          >
            <option value="">All nodes</option>
            {nodes.map((n) => (
              <option key={n.nodeId} value={n.name}>{n.name}</option>
            ))}
          </select>
        </div>

        {/* Trace list */}
        <div className="overflow-auto flex-1">
          <div className="px-3 py-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
            {visibleTraces.length} trace{visibleTraces.length !== 1 ? "s" : ""}
            {nodeFilter && <span className="text-indigo-400 ml-1">· {nodeFilter}</span>}
            {timeRange !== "all" && <span className="text-amber-400 ml-1">· {timeRange}</span>}
          </div>
          {pagedTraces.map((t) => (
            <button
              key={t.traceId}
              onClick={() => selectTrace(t.traceId)}
              className={`w-full text-left px-3 py-2.5 border-b border-gray-700/60 hover:bg-gray-700/50 transition-colors ${
                selected === t.traceId ? "bg-gray-700" : ""
              }`}
            >
              <p className="text-xs font-mono text-indigo-400 truncate" title={t.traceId}>
                {t.traceId.slice(0, 20)}…
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {String(t.spanCount)} spans · {t.totalDurationMs.toFixed(0)}ms · cycle{" "}
                {String(t.cycle)}
                {Number(t.errorSpans) > 0 && (
                  <span className="text-red-400 ml-1">{String(t.errorSpans)} err</span>
                )}
              </p>
            </button>
          ))}
          {pagedTraces.length === 0 && (
            <p className="text-center text-gray-600 py-8 text-sm">
              {traceSearch || nodeFilter ? "No matching traces" : "No traces yet"}
            </p>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="border-t border-gray-700 px-3 py-2 flex items-center justify-between">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="text-[10px] font-mono text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed px-2 py-1 rounded hover:bg-gray-700 transition-colors"
            >
              ← prev
            </button>
            <span className="text-[10px] text-gray-500 font-mono">
              {page + 1} / {totalPages}
            </span>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              className="text-[10px] font-mono text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed px-2 py-1 rounded hover:bg-gray-700 transition-colors"
            >
              next →
            </button>
          </div>
        )}
      </div>

      {/* Right panel: detail */}
      <div className="flex-1 bg-gray-800 rounded-xl border border-gray-700 p-4 overflow-auto">
        {selected ? (
          <>
            {/* Detail header with back button and view toggle */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <button
                  onClick={clearSelection}
                  className="text-xs font-mono text-gray-400 hover:text-gray-200 border border-gray-600 hover:border-gray-400 px-2.5 py-1 rounded transition-colors"
                >
                  ← BACK TO LIST
                </button>
                <p className="text-xs text-gray-500 font-mono break-all">
                  trace: {selected.slice(0, 24)}…
                </p>
              </div>

              {/* View mode toggle */}
              <div className="flex rounded border border-gray-600 overflow-hidden text-[10px] font-mono">
                {(["waterfall", "timeline", "groups"] as ViewMode[]).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-1 transition-colors ${
                      viewMode === mode
                        ? "bg-indigo-600 text-white"
                        : "text-gray-400 hover:text-gray-200 hover:bg-gray-700"
                    }`}
                  >
                    {mode.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* Loading skeleton */}
            {spansLoading ? (
              <div className="space-y-3 mt-2">
                <div className="flex items-center gap-3">
                  <SkeletonBar width="120px" height={10} />
                  <SkeletonBar width="80px" height={10} />
                </div>
                {[...Array(6)].map((_, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <SkeletonBar width="130px" height={10} />
                    <SkeletonBar width={`${30 + i * 8}%`} height={20} />
                    <SkeletonBar width="36px" height={16} />
                  </div>
                ))}
              </div>
            ) : viewMode === "waterfall" ? (
              <TraceWaterfall spans={spans} />
            ) : viewMode === "timeline" ? (
              <PipelineTimeline spans={spans} />
            ) : (
              <CollapsibleGroups spans={spans} />
            )}
          </>
        ) : (
          <p className="text-gray-500 text-sm text-center mt-20">
            Select a trace to view the waterfall
          </p>
        )}
      </div>
    </div>
  );
}
