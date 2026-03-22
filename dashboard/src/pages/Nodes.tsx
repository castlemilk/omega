import { useEffect, useState } from "react";
import { client } from "../client";
import BrainConfigPanel from "../components/BrainConfigPanel";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import type { Node, ExecutionRecord, CircuitBreakerState } from "../gen/omega/v1/types_pb";
import { ErrorClassification } from "../gen/omega/v1/types_pb";
import type { LatencyPoint } from "../gen/omega/v1/omega_service_pb";

const ERROR_CLASS_LABELS: Record<number, string> = {
  [ErrorClassification.UNSPECIFIED]: "",
  [ErrorClassification.TIMEOUT]: "TIMEOUT",
  [ErrorClassification.DATA_QUALITY]: "DATA_QUALITY",
  [ErrorClassification.DEPENDENCY_FAILURE]: "DEPENDENCY",
  [ErrorClassification.RESOURCE_EXHAUSTION]: "RESOURCE",
  [ErrorClassification.VALIDATION_ERROR]: "VALIDATION",
  [ErrorClassification.LLM_ERROR]: "LLM_ERROR",
  [ErrorClassification.UNKNOWN]: "UNKNOWN",
};

const ERROR_CLASS_COLORS: Record<number, string> = {
  [ErrorClassification.TIMEOUT]: "bg-yellow-900 text-yellow-400",
  [ErrorClassification.DATA_QUALITY]: "bg-orange-900 text-orange-400",
  [ErrorClassification.DEPENDENCY_FAILURE]: "bg-red-900 text-red-400",
  [ErrorClassification.RESOURCE_EXHAUSTION]: "bg-purple-900 text-purple-400",
  [ErrorClassification.VALIDATION_ERROR]: "bg-orange-900 text-orange-400",
  [ErrorClassification.LLM_ERROR]: "bg-indigo-900 text-indigo-400",
  [ErrorClassification.UNKNOWN]: "bg-gray-700 text-gray-400",
};

function ErrorClassBadge({ errorClass }: { errorClass: number }) {
  const label = ERROR_CLASS_LABELS[errorClass];
  if (!label) return null;
  const color = ERROR_CLASS_COLORS[errorClass] ?? "bg-gray-700 text-gray-400";
  return <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${color}`}>{label}</span>;
}

function formatTs(ts?: { seconds: bigint }): string {
  if (!ts) return "—";
  return new Date(Number(ts.seconds) * 1000).toLocaleTimeString();
}

function circuitBreakerBadge(cb?: CircuitBreakerState) {
  if (!cb) return null;
  const state = cb.state || "CLOSED";
  const colorClass =
    state === "OPEN"
      ? "bg-red-900 text-red-400"
      : state === "HALF_OPEN"
        ? "bg-yellow-900 text-yellow-400"
        : "bg-green-900 text-green-400";
  const label = state === "HALF_OPEN" ? "HALF-OPEN" : state;
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${colorClass}`}>{label}</span>
  );
}

export default function Nodes() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Node | null>(null);
  const [history, setHistory] = useState<LatencyPoint[]>([]);
  const [recentExecutions, setRecentExecutions] = useState<ExecutionRecord[]>([]);
  const [errorFilter, setErrorFilter] = useState<number | null>(null);

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
              {[
                "Node",
                "Version",
                "Health",
                "p95 ms",
                "Err Rate",
                "Cycles",
                "Status",
                "Circuit Breaker",
              ].map((h) => (
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
                <td className="px-4 py-3">
                  {n.circuitBreaker ? (
                    <div className="flex flex-col gap-1">
                      {circuitBreakerBadge(n.circuitBreaker)}
                      {n.circuitBreaker.failureCount > 0 && (
                        <span className="text-xs text-gray-500 font-mono">
                          {n.circuitBreaker.failureCount} fail
                          {n.circuitBreaker.failureCount !== 1 ? "s" : ""}
                        </span>
                      )}
                      {n.circuitBreaker.lastFailureTime && (
                        <span className="text-xs text-gray-600 font-mono">
                          last: {formatTs(n.circuitBreaker.lastFailureTime)}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-xs text-gray-600">—</span>
                  )}
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
            <div className="px-4 py-3 bg-gray-900 border-b border-gray-700 flex items-center justify-between gap-2 flex-wrap">
              <h3 className="text-xs font-semibold text-gray-400 uppercase">Recent Executions</h3>
              <div className="flex gap-1 flex-wrap">
                <button
                  onClick={() => setErrorFilter(null)}
                  className={`text-xs px-2 py-0.5 rounded-full transition-colors ${errorFilter === null ? "bg-indigo-600 text-white" : "bg-gray-700 text-gray-400 hover:bg-gray-600"}`}
                >
                  All
                </button>
                {Object.entries(ERROR_CLASS_LABELS)
                  .filter(([, label]) => label !== "")
                  .map(([cls, label]) => (
                    <button
                      key={cls}
                      onClick={() =>
                        setErrorFilter(errorFilter === Number(cls) ? null : Number(cls))
                      }
                      className={`text-xs px-2 py-0.5 rounded-full font-mono transition-colors ${
                        errorFilter === Number(cls)
                          ? "bg-indigo-600 text-white"
                          : `${ERROR_CLASS_COLORS[Number(cls)] ?? "bg-gray-700 text-gray-400"} hover:opacity-80`
                      }`}
                    >
                      {label}
                    </button>
                  ))}
              </div>
            </div>
            {recentExecutions.length > 0 ? (
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-400 uppercase bg-gray-900">
                  <tr>
                    {["Time", "Action", "Duration", "Status", "Class", "Error"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {recentExecutions
                    .filter((e) => errorFilter === null || e.errorClass === errorFilter)
                    .map((e) => (
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
                        <td className="px-4 py-3">
                          <ErrorClassBadge errorClass={e.errorClass} />
                        </td>
                        <td
                          className="px-4 py-3 text-red-400 text-xs font-mono max-w-xs truncate"
                          title={e.errorText}
                        >
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
