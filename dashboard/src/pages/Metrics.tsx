import { useEffect, useState } from "react";
import { client } from "../client";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import type { Node } from "../gen/omega/v1/types_pb";

export default function Metrics() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [histories, setHistories] = useState<Record<string, { ms: number }[]>>({});

  useEffect(() => {
    client.listNodes({}).then(async (r) => {
      setNodes(r.nodes);
      // Fetch latency history for each node
      const histMap: Record<string, { ms: number }[]> = {};
      await Promise.all(
        r.nodes.map(async (n) => {
          const nr = await client.getNode({ nodeId: n.nodeId }).catch(() => null);
          if (nr) {
            histMap[n.nodeId] = nr.latencyHistory.map((p) => ({ ms: p.durationMs }));
          }
        })
      );
      setHistories(histMap);
    }).catch(console.error);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-white">Metrics</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {nodes.map((n) => {
          const hist = histories[n.nodeId] ?? [];
          return (
            <div key={n.nodeId} className="bg-gray-800 rounded-xl border border-gray-700 p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-sm font-medium text-white">{n.name}</p>
                <span className="text-xs text-gray-500">p95: {n.p95LatencyMs.toFixed(0)}ms</span>
              </div>
              {hist.length > 1 ? (
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={hist}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis hide />
                      <YAxis width={35} tick={{ fontSize: 10, fill: "#6b7280" }} />
                      <Tooltip
                        contentStyle={{ background: "#1f2937", border: "1px solid #374151", borderRadius: 6 }}
                        formatter={(v: number) => [`${v.toFixed(0)}ms`]}
                      />
                      <Legend />
                      <Line type="monotone" dataKey="ms" name="latency" stroke="#6366f1" dot={false} strokeWidth={1.5} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-gray-600 text-xs text-center py-4">No history</p>
              )}
              <div className="flex gap-4 mt-3 text-xs text-gray-500">
                <span>err: {(n.errorRate * 100).toFixed(1)}%</span>
                <span>avg: {n.avgLatencyMs.toFixed(0)}ms</span>
                <span>total: {String(n.executionsTotal)} execs</span>
              </div>
            </div>
          );
        })}
        {nodes.length === 0 && (
          <p className="col-span-2 text-center text-gray-600 py-12">No node metrics yet</p>
        )}
      </div>
    </div>
  );
}
