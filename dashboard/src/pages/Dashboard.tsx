import { useEffect, useState } from "react";
import { client } from "../client";
import PipelineCycle from "../components/PipelineCycle";
import { useProject } from "../context/ProjectContext";
import type { SystemHealth, Node, ActivityEntry } from "../gen/omega/v1/types_pb";

// Maps raw action_type strings to human-readable labels and colors.
function formatAction(actionType: string): { label: string; color: string } {
  const t = actionType.toUpperCase();
  if (!t || t === "0") return { label: "event", color: "text-gray-500" };
  const map: Record<string, { label: string; color: string }> = {
    NODE_STARTED: { label: "Node started", color: "text-green-400" },
    NODE_STOPPED: { label: "Node stopped", color: "text-yellow-400" },
    NODE_ERROR: { label: "Node error", color: "text-red-400" },
    NODE_REGISTERED: { label: "Node registered", color: "text-indigo-400" },
    NODE_DEREGISTERED: { label: "Node deregistered", color: "text-gray-400" },
    CYCLE_STARTED: { label: "Cycle started", color: "text-indigo-400" },
    CYCLE_COMPLETED: { label: "Cycle completed", color: "text-green-400" },
    CYCLE_FAILED: { label: "Cycle failed", color: "text-red-400" },
    IMPROVEMENT_APPLIED: { label: "Improvement applied", color: "text-teal-400" },
    ISSUE_OPENED: { label: "Issue opened", color: "text-orange-400" },
    ISSUE_CLOSED: { label: "Issue closed", color: "text-green-400" },
    ALIGNMENT_CHECK: { label: "Alignment check", color: "text-purple-400" },
    MEMORY_UPDATED: { label: "Memory updated", color: "text-cyan-400" },
  };
  // Exact match
  if (map[t]) return map[t];
  // Partial match fallback
  for (const [key, val] of Object.entries(map)) {
    if (t.includes(key) || key.includes(t)) return val;
  }
  // Generic formatting: replace underscores with spaces, title-case
  const label = t
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, color: "text-gray-400" };
}

function ActivityRow({ evt }: { evt: ActivityEntry }) {
  const time = evt.recordedAt
    ? new Date(Number(evt.recordedAt.seconds) * 1000).toLocaleTimeString()
    : "—";
  const { label, color } = formatAction(evt.actionType);
  const entity = [evt.entityType, evt.entityId].filter(Boolean).join(" · ");
  const cycleTag = evt.cycle && evt.cycle > 0n ? `#${String(evt.cycle)}` : null;

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
      <span className="text-gray-500 text-xs shrink-0 font-mono w-20">{time}</span>
      <span className={`text-xs font-semibold shrink-0 ${color}`}>{label}</span>
      {entity && <span className="text-gray-400 text-xs font-mono truncate">{entity}</span>}
      {cycleTag && (
        <span className="ml-auto text-xs text-gray-600 font-mono shrink-0">{cycleTag}</span>
      )}
    </div>
  );
}

interface DashboardProps {
  health: SystemHealth | null;
}

export default function Dashboard({ health }: DashboardProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const { selectedProject } = useProject();

  useEffect(() => {
    client
      .listNodes({})
      .then((r) => setNodes(r.nodes))
      .catch(console.error);
    client
      .listActivity({ limit: 20 })
      .then((r) => setActivity(r.entries))
      .catch(console.error);
  }, []);

  const statusColor: Record<string, string> = {
    healthy: "text-green-400",
    degraded: "text-yellow-400",
    critical: "text-red-400",
  };

  return (
    <div className="space-y-6">
      {/* Compact system facts strip */}
      <div className="flex items-center gap-0 bg-gray-900 rounded-xl border border-gray-700 divide-x divide-gray-700 overflow-hidden text-sm">
        {[
          {
            label: "Status",
            value: health?.status ?? "—",
            cls: statusColor[health?.status ?? ""] ?? "text-white",
          },
          {
            label: "Health",
            value: health ? `${(health.compositeScore * 100).toFixed(1)}%` : "—",
            cls: "text-white",
          },
          {
            label: "Cycles",
            value: String(health?.totalCycles ?? "—"),
            cls: "text-white",
          },
          {
            label: "Open Issues",
            value: String(health?.openIssues ?? "—"),
            cls: Number(health?.openIssues ?? 0) > 0 ? "text-red-400" : "text-white",
          },
        ].map(({ label, value, cls }) => (
          <div key={label} className="flex items-center gap-2 px-5 py-3">
            <span className="text-xs text-gray-500">{label}</span>
            <span className={`font-semibold ${cls}`}>{value}</span>
          </div>
        ))}
      </div>

      {/* Project pipeline cycle — dynamic from selected project's pipeline_config */}
      <PipelineCycle
        nodes={nodes}
        totalCycles={health?.totalCycles ? Number(health.totalCycles) : undefined}
        projectName={selectedProject?.name}
        pipelineSteps={selectedProject?.pipelineConfig}
      />

      {/* Activity feed */}
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Recent Activity
        </h2>
        <div className="bg-gray-800 rounded-xl border border-gray-700 divide-y divide-gray-700">
          {activity.map((evt) => (
            <ActivityRow key={evt.logId} evt={evt} />
          ))}
          {activity.length === 0 && (
            <p className="text-center text-gray-600 py-8 text-sm">No activity yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
