import { useEffect, useState } from "react";
import { client } from "../client";
import BrainConfigPanel from "../components/BrainConfigPanel";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import type { Node, ExecutionRecord } from "../gen/omega/v1/types_pb";
import type { LatencyPoint } from "../gen/omega/v1/omega_service_pb";

function formatTs(ts?: { seconds: bigint }): string {
  if (!ts) return "—";
  return new Date(Number(ts.seconds) * 1000).toLocaleTimeString();
}

export default function Nodes() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Node | null>(null);
  const [history, setHistory] = useState<LatencyPoint[]>([]);
  const [recentExecutions, setRecentExecutions] = useState<ExecutionRecord[]>([]);

  useEffect(() => {
    client
      .listNodes({})
      .then((r) => setNodes(r.nodes))
      .catch(console.error);
  }, []);

  async function selectNode(nodeId: string) {
    setSelectedId(nodeId);
    const r = await client.getNode({ nodeId }).catch(() => null);
    if (r) {
      setDetail(r.node ?? null);
      setHistory(r.latencyHistory);
      setRecentExecutions(r.recentExecutions);
    }
  }

  const sparkData = history.map((p) => ({
    ts: Number(p.ts?.seconds ?? 0),
    ms: p.durationMs,
    ok: p.success,
  }));

  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs text-gray-400 uppercase bg-gray-900">
            <tr>
              {["Node", "Version", "Health", "p95 ms", "Err Rate", "Cycles", "Status"].map((h) => (
                <th key={h} className="px-4 py-3 text-left font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {nodes.map((n) => (
              <tr
                key={n.nodeId}
                onClick={() => selectNode(n.nodeId)}
                className={`cursor-pointer hover:bg-gray-700 transition-colors ${selectedId === n.nodeId ? "bg-gray-700" : ""}`}
              >
                <td className="px-4 py-3 font-medium text-white">{n.name}</td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">v{n.version}</td>
                <td className="px-4 py-3">
                  <span
                    className={
                      n.health >= 0.8
                        ? "text-green-400"
                        : n.health >= 0.6
                          ? "text-yellow-400"
                          : "text-red-400"
                    }
                  >
                    {(n.health * 100).toFixed(0)}%
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-300">{n.p95LatencyMs.toFixed(0)}</td>
                <td className="px-4 py-3 text-gray-300">{(n.errorRate * 100).toFixed(1)}%</td>
                <td className="px-4 py-3 text-gray-300">{String(n.executionsTotal)}</td>
                <td className="px-4 py-3">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${n.status === "active" ? "bg-green-900 text-green-400" : "bg-gray-700 text-gray-400"}`}
                  >
                    {n.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {nodes.length === 0 && (
          <p className="text-center text-gray-600 py-8 text-sm">No nodes yet</p>
        )}
      </div>

      {detail && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="space-y-4">
              <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
                <h3 className="text-sm font-semibold text-gray-400 mb-3 uppercase">
                  Latency History
                </h3>
                {sparkData.length > 0 ? (
                  <div className="h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={sparkData}>
                        <XAxis dataKey="ts" hide />
                        <YAxis width={40} tick={{ fontSize: 11, fill: "#9ca3af" }} />
                        <Tooltip
                          contentStyle={{
                            background: "#1f2937",
                            border: "1px solid #374151",
                            borderRadius: 8,
                          }}
                          labelStyle={{ color: "#9ca3af" }}
                          formatter={(v: number) => [`${v.toFixed(0)}ms`, "Latency"]}
                        />
                        <Line
                          type="monotone"
                          dataKey="ms"
                          stroke="#6366f1"
                          dot={false}
                          strokeWidth={2}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-gray-600 text-sm">No history yet</p>
                )}
              </div>
            </div>
            <BrainConfigPanel nodeId={detail.nodeId} />
          </div>

          <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
            <div className="px-4 py-3 bg-gray-900 border-b border-gray-700">
              <h3 className="text-xs font-semibold text-gray-400 uppercase">Recent Executions</h3>
            </div>
            {recentExecutions.length > 0 ? (
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-400 uppercase bg-gray-900">
                  <tr>
                    {["Time", "Action", "Duration", "Status", "Error"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {recentExecutions.map((e) => (
                    <tr key={e.execId} className="hover:bg-gray-700/50 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">
                        {formatTs(e.startedAt)}
                      </td>
                      <td className="px-4 py-3 text-gray-300 font-mono text-xs">
                        {e.action || "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-300">{e.durationMs.toFixed(0)}ms</td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full ${
                            e.success ? "bg-green-900 text-green-400" : "bg-red-900 text-red-400"
                          }`}
                        >
                          {e.success ? "success" : "error"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-red-400 text-xs font-mono max-w-xs truncate">
                        {e.errorText || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-center text-gray-600 py-8 text-sm">No executions recorded</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
