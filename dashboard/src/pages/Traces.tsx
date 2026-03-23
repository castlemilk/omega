import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { client } from "../client";
import TraceWaterfall from "../components/TraceWaterfall";
import type { TraceSummary, Span, Node } from "../gen/omega/v1/types_pb";

export default function Traces() {
  const [searchParams] = useSearchParams();
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [nodeFilter, setNodeFilter] = useState("");
  const [traceSearch, setTraceSearch] = useState("");

  useEffect(() => {
    client
      .listNodes({})
      .then((r) => setNodes(r.nodes))
      .catch(console.error);
  }, []);

  useEffect(() => {
    client
      .listTraces({ limit: 50, nodeFilter })
      .then((r) => setTraces(r.traces))
      .catch(console.error);
  }, [nodeFilter]);

  const visibleTraces = traceSearch
    ? traces.filter((t) => t.traceId.startsWith(traceSearch))
    : traces;

  function selectTrace(id: string) {
    setSelected(id);
    client
      .getTrace({ traceId: id })
      .then((r) => setSpans(r.spans))
      .catch(console.error);
  }

  useEffect(() => {
    const targetId = searchParams.get("traceId");
    if (!targetId) return;
    client
      .getTrace({ traceId: targetId })
      .then((r) => {
        setSelected(targetId);
        setSpans(r.spans);
      })
      .catch(console.error);
  }, [searchParams]);

  return (
    <div className="flex gap-4 h-full">
      {/* Left panel: filters + list */}
      <div className="w-72 shrink-0 flex flex-col bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        {/* Filter bar */}
        <div className="p-2 border-b border-gray-700 space-y-1.5">
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
              <option key={n.nodeId} value={n.name}>
                {n.name}
              </option>
            ))}
          </select>
        </div>

        {/* Trace list */}
        <div className="overflow-auto flex-1">
          <div className="px-3 py-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
            {visibleTraces.length} trace{visibleTraces.length !== 1 ? "s" : ""}
            {nodeFilter && <span className="text-indigo-400 ml-1">· {nodeFilter}</span>}
          </div>
          {visibleTraces.map((t) => (
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
          {visibleTraces.length === 0 && (
            <p className="text-center text-gray-600 py-8 text-sm">
              {traceSearch || nodeFilter ? "No matching traces" : "No traces yet"}
            </p>
          )}
        </div>
      </div>

      {/* Right panel: waterfall */}
      <div className="flex-1 bg-gray-800 rounded-xl border border-gray-700 p-4 overflow-auto">
        {selected ? (
          <>
            <p className="text-xs text-gray-500 mb-4 font-mono break-all">trace: {selected}</p>
            <TraceWaterfall spans={spans} />
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
