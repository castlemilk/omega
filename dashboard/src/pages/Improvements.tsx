import { useCallback } from "react";
import { TrendingUp, CheckCircle2, XCircle, HelpCircle } from "lucide-react";
import { client } from "../client";
import { usePolling } from "../hooks/usePolling";

export default function Improvements() {
  const fetchFn = useCallback(() => client.getImprovementHistory({ limit: 50 }), []);
  const { data, error, loading } = usePolling(fetchFn);
  const records = data?.records ?? [];

  if (loading) return <div className="text-gray-500 text-sm">Loading improvement history…</div>;
  if (error) return <div className="text-red-400 text-sm">Error: {error}</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <TrendingUp size={18} className="text-green-400" />
        <h1 className="text-lg font-semibold text-white">Improvement History</h1>
        <span className="text-xs text-gray-500 ml-1">{records.length} cycles</span>
      </div>

      {records.length === 0 ? (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-8 text-center">
          <p className="text-gray-600 text-sm">No improvement cycles recorded yet</p>
        </div>
      ) : (
        <div className="space-y-3">
          {records.map((rec) => {
            const beforeKeys = Object.keys(rec.beforeMetrics);
            const afterKeys = Object.keys(rec.afterMetrics);
            const metricKeys = [...new Set([...beforeKeys, ...afterKeys])].slice(0, 4);

            return (
              <div
                key={rec.improveId}
                className="bg-gray-800 rounded-xl border border-gray-700 p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-white">
                        {rec.nodeName || rec.nodeId}
                      </span>
                      <span className="text-xs text-gray-500 font-mono">
                        {rec.fromVersion} → {rec.toVersion}
                      </span>
                      <span className="text-xs text-gray-600">cycle {Number(rec.cycle)}</span>
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">triggered by {rec.triggeredBy}</p>
                  </div>

                  {/* Alignment gate indicator */}
                  <div className="shrink-0 flex items-center gap-1.5">
                    {!rec.hasAlignmentDecision ? (
                      <HelpCircle size={15} className="text-gray-600" />
                    ) : rec.alignmentApproved ? (
                      <CheckCircle2 size={15} className="text-green-400" />
                    ) : (
                      <XCircle size={15} className="text-red-400" />
                    )}
                    <span className="text-xs text-gray-500">
                      {!rec.hasAlignmentDecision
                        ? "no gate"
                        : rec.alignmentApproved
                          ? "approved"
                          : "rejected"}
                    </span>
                  </div>
                </div>

                {/* Before / after metrics */}
                {metricKeys.length > 0 && (
                  <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1">
                    {metricKeys.map((k) => {
                      const before = rec.beforeMetrics[k];
                      const after = rec.afterMetrics[k];
                      const delta = before != null && after != null ? after - before : null;
                      return (
                        <div key={k} className="flex items-center justify-between text-xs">
                          <span className="text-gray-500 truncate max-w-[120px]">{k}</span>
                          <span className="font-mono text-gray-300">
                            {after?.toFixed(2) ?? "—"}
                            {delta != null && (
                              <span
                                className={`ml-1 ${
                                  delta >= 0 ? "text-green-400" : "text-red-400"
                                }`}
                              >
                                {delta >= 0 ? "+" : ""}
                                {delta.toFixed(2)}
                              </span>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Alignment reasons */}
                {rec.alignmentReasons.length > 0 && (
                  <p className="mt-2 text-xs text-gray-500 italic truncate">
                    {rec.alignmentReasons.join(" · ")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
