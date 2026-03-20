import { LineChart, Line, ResponsiveContainer } from "recharts";
import type { Node } from "../gen/omega/v1/types_pb";

function healthColor(h: number) {
  if (h >= 0.8) return "border-green-600 bg-green-900/20";
  if (h >= 0.6) return "border-yellow-600 bg-yellow-900/20";
  return "border-red-600 bg-red-900/20";
}

function healthText(h: number) {
  if (h >= 0.8) return "text-green-400";
  if (h >= 0.6) return "text-yellow-400";
  return "text-red-400";
}

interface NodeCardProps { node: Node }

export default function NodeCard({ node }: NodeCardProps) {
  const lastExecAgo = node.lastExecution?.startedAt
    ? Math.round((Date.now() / 1000 - Number(node.lastExecution.startedAt.seconds)) / 60)
    : null;

  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-3 ${healthColor(node.health)}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-white truncate">{node.name}</p>
          <p className="text-xs text-gray-500">v{node.version}</p>
        </div>
        <span className={`text-xs font-bold ${healthText(node.health)}`}>
          {(node.health * 100).toFixed(0)}%
        </span>
      </div>
      <div className="h-8">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={[{ v: node.avgLatencyMs }, { v: node.p95LatencyMs }]}>
            <Line
              type="monotone"
              dataKey="v"
              stroke={node.health >= 0.8 ? "#4ade80" : node.health >= 0.6 ? "#facc15" : "#f87171"}
              dot={false}
              strokeWidth={1.5}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex justify-between text-xs text-gray-500">
        <span>err: {(node.errorRate * 100).toFixed(1)}%</span>
        <span>{lastExecAgo !== null ? `${lastExecAgo}m ago` : "never"}</span>
      </div>
    </div>
  );
}
