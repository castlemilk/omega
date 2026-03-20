import { useEffect, useState } from "react";
import { client } from "../client";
import NodeCard from "../components/NodeCard";
import type { SystemHealth, Node, ActivityEntry } from "../gen/omega/v1/types_pb";

interface DashboardProps { health: SystemHealth | null }

export default function Dashboard({ health }: DashboardProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);

  useEffect(() => {
    client.listNodes({}).then((r) => setNodes(r.nodes)).catch(console.error);
    client.listActivity({ limit: 20 }).then((r) => setActivity(r.entries)).catch(console.error);
  }, []);

  const statusColor: Record<string, string> = {
    healthy: "text-green-400",
    degraded: "text-yellow-400",
    critical: "text-red-400",
  };

  return (
    <div className="space-y-6">
      {/* System stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Status", value: health?.status ?? "—", cls: statusColor[health?.status ?? ""] ?? "text-white" },
          { label: "Health Score", value: health ? `${(health.compositeScore * 100).toFixed(1)}%` : "—", cls: "text-white" },
          { label: "Total Cycles", value: String(health?.totalCycles ?? "—"), cls: "text-white" },
          { label: "Open Issues", value: String(health?.openIssues ?? "—"), cls: Number(health?.openIssues ?? 0) > 0 ? "text-red-400" : "text-white" },
        ].map(({ label, value, cls }) => (
          <div key={label} className="bg-gray-800 rounded-xl p-4 border border-gray-700">
            <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${cls}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Node grid */}
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Nodes ({nodes.length})
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {nodes.map((n) => <NodeCard key={n.nodeId} node={n} />)}
        </div>
        {nodes.length === 0 && (
          <p className="text-gray-600 text-sm py-8 text-center">
            No nodes registered — run the orchestrator first.
          </p>
        )}
      </div>

      {/* Activity feed */}
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Recent Activity
        </h2>
        <div className="bg-gray-800 rounded-xl border border-gray-700 divide-y divide-gray-700">
          {activity.map((evt) => (
            <div key={evt.logId} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <span className="text-gray-500 text-xs shrink-0">
                {evt.recordedAt
                  ? new Date(Number(evt.recordedAt.seconds) * 1000).toLocaleTimeString()
                  : "—"}
              </span>
              <span className="text-indigo-400 text-xs font-mono">{evt.actionType}</span>
              <span className="text-gray-300 truncate">{evt.entityId}</span>
            </div>
          ))}
          {activity.length === 0 && (
            <p className="text-center text-gray-600 py-8 text-sm">No activity yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
