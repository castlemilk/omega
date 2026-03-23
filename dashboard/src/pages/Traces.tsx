import { useEffect, useState } from "react";
import { client } from "../client";
import TraceWaterfall from "../components/TraceWaterfall";
import type { TraceSummary, Span } from "../gen/omega/v1/types_pb";

export default function Traces() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);

  useEffect(() => {
    client
      .listTraces({ limit: 30 })
      .then((r) => setTraces(r.traces))
      .catch(console.error);
  }, []);

  function selectTrace(id: string) {
    setSelected(id);
    client
      .getTrace({ traceId: id })
      .then((r) => setSpans(r.spans))
      .catch(console.error);
  }

  return (
    <div className="flex gap-4 h-full">
      <div className="w-72 shrink-0 bg-gray-800 rounded-xl border border-gray-700 overflow-auto">
        <div className="p-3 border-b border-gray-700 text-xs font-semibold text-gray-400 uppercase">
          Recent Traces
        </div>
        {traces.map((t) => (
          <button
            key={t.traceId}
            onClick={() => selectTrace(t.traceId)}
            className={`w-full text-left px-3 py-2.5 border-b border-gray-700 hover:bg-gray-700 transition-colors ${selected === t.traceId ? "bg-gray-700" : ""}`}
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
        {traces.length === 0 && (
          <p className="text-center text-gray-600 py-8 text-sm">No traces yet</p>
        )}
      </div>
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
