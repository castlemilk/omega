import type { Span } from "../gen/omega/v1/types_pb";

interface TraceWaterfallProps {
  spans: Span[];
}

export default function TraceWaterfall({ spans }: TraceWaterfallProps) {
  if (!spans.length) return <p className="text-gray-500 text-sm">No spans.</p>;

  const sorted = [...spans].sort(
    (a, b) => Number(a.startedAt?.seconds ?? 0) - Number(b.startedAt?.seconds ?? 0)
  );
  const minTs = Number(sorted[0]?.startedAt?.seconds ?? 0);
  const maxTs = sorted.reduce(
    (m, s) => Math.max(m, Number(s.endedAt?.seconds ?? s.startedAt?.seconds ?? 0)),
    0
  );
  const totalMs = Math.max(1, (maxTs - minTs) * 1000);

  const depthMap = new Map<string, number>();
  for (const span of sorted) {
    depthMap.set(span.spanId, span.parentSpanId ? (depthMap.get(span.parentSpanId) ?? 0) + 1 : 0);
  }

  return (
    <div className="space-y-1 font-mono text-xs">
      {sorted.map((span) => {
        const depth = depthMap.get(span.spanId) ?? 0;
        const offsetMs = (Number(span.startedAt?.seconds ?? 0) - minTs) * 1000;
        const durMs = span.durationMs;
        const leftPct = (offsetMs / totalMs) * 100;
        const widthPct = Math.max(0.5, (durMs / totalMs) * 100);
        const isErr = span.status === "error";

        return (
          <div key={span.spanId} className="flex items-center gap-2">
            <div
              className="shrink-0 text-gray-400 truncate"
              style={{ width: 200, paddingLeft: depth * 12 }}
            >
              <span className={isErr ? "text-red-400" : "text-green-400"}>
                {isErr ? "✗" : "✓"}
              </span>{" "}
              {span.nodeName || span.operation}
            </div>
            <div className="flex-1 relative h-5 bg-gray-700 rounded overflow-hidden">
              <div
                className={`absolute h-full rounded ${isErr ? "bg-red-600" : "bg-indigo-500"}`}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                title={span.operation}
              />
            </div>
            <div className="shrink-0 text-gray-500 w-16 text-right">{durMs.toFixed(0)}ms</div>
          </div>
        );
      })}
    </div>
  );
}
