import { useEffect, useState } from "react";
import { client } from "../client";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { ConvergencePoint, ImprovementRecord } from "../gen/omega/v1/types_pb";

export default function Convergence() {
  const [points, setPoints] = useState<ConvergencePoint[]>([]);
  const [improvements, setImprovements] = useState<ImprovementRecord[]>([]);

  useEffect(() => {
    client
      .getConvergence({ limit: 200 })
      .then((r) => setPoints(r.points))
      .catch(console.error);
    client
      .listImprovements({ nodeId: "", limit: 50 })
      .then((r) => setImprovements(r.improvements))
      .catch(console.error);
  }, []);

  const chartData = points.map((p) => ({
    cycle: Number(p.cycle),
    score: p.score,
    ms: p.pipelineMs,
  }));

  return (
    <div className="space-y-6">
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
        <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">Convergence Score</h3>
        {chartData.length > 1 ? (
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="cycle"
                  tick={{ fontSize: 11, fill: "#6b7280" }}
                  label={{ value: "Cycle", position: "insideBottom", fill: "#6b7280" }}
                />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#6b7280" }} />
                <Tooltip
                  contentStyle={{
                    background: "#1f2937",
                    border: "1px solid #374151",
                    borderRadius: 8,
                  }}
                  formatter={(v: number) => [v.toFixed(4), "Score"]}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#6366f1"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-gray-600 text-sm text-center py-8">
            Run the orchestrator to generate convergence data
          </p>
        )}
      </div>

      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="p-3 border-b border-gray-700 text-xs font-semibold text-gray-400 uppercase">
          Improvement Log ({improvements.length})
        </div>
        <div className="divide-y divide-gray-700 max-h-96 overflow-auto">
          {improvements.map((imp) => (
            <div key={imp.improveId} className="px-4 py-3 flex items-center gap-3 text-sm">
              <span className="text-gray-500 text-xs w-12 shrink-0">cy {String(imp.cycle)}</span>
              <span className="text-white font-medium shrink-0">{imp.nodeName}</span>
              <span className="text-gray-400 text-xs font-mono">
                v{imp.fromVersion} → v{imp.toVersion}
              </span>
              <span className="text-gray-600 text-xs ml-auto">{imp.triggeredBy}</span>
            </div>
          ))}
          {improvements.length === 0 && (
            <p className="text-center text-gray-600 py-8 text-sm">No improvements yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
