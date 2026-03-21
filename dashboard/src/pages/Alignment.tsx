import { useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { ShieldCheck, ShieldX } from "lucide-react";
import { client } from "../client";
import { usePolling } from "../hooks/usePolling";

export default function Alignment() {
  const fetchFn = useCallback(
    () => client.getAlignmentDecisions({ limit: 100 }),
    [],
  );
  const { data, error, loading } = usePolling(fetchFn);

  const decisions = data?.decisions ?? [];
  const approved = decisions.filter((d) => d.approved).length;
  const rejected = decisions.length - approved;
  const rate =
    decisions.length > 0
      ? Math.round((approved / decisions.length) * 100)
      : null;

  const chartData = [
    { name: "Approved", value: approved, color: "#22c55e" },
    { name: "Rejected", value: rejected, color: "#ef4444" },
  ];

  if (loading) return <div className="text-gray-500 text-sm">Loading alignment data…</div>;
  if (error) return <div className="text-red-400 text-sm">Error: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">Alignment Layer</h1>
        {rate !== null && (
          <div
            className={`flex items-center gap-2 text-sm font-medium ${
              rate >= 80 ? "text-green-400" : "text-yellow-400"
            }`}
          >
            <ShieldCheck size={16} />
            {rate}% approval rate
          </div>
        )}
      </div>

      {decisions.length > 0 && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-400 uppercase font-medium mb-3">
            Decision Breakdown
          </p>
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 16 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fill: "#9ca3af", fontSize: 12 }}
                width={60}
              />
              <Tooltip
                contentStyle={{
                  background: "#1f2937",
                  border: "none",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                cursor={{ fill: "#374151" }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {chartData.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-700">
          <p className="text-xs text-gray-400 uppercase font-medium">
            Recent Decisions
          </p>
        </div>
        {decisions.length === 0 ? (
          <p className="text-center text-gray-600 py-8 text-sm">
            No alignment decisions recorded yet
          </p>
        ) : (
          <div className="divide-y divide-gray-700">
            {decisions.map((d) => (
              <div
                key={d.decisionId}
                className="px-4 py-3 flex items-start gap-3"
              >
                {d.approved ? (
                  <ShieldCheck size={16} className="text-green-400 mt-0.5 shrink-0" />
                ) : (
                  <ShieldX size={16} className="text-red-400 mt-0.5 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`text-xs font-medium ${
                        d.approved ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {d.approved ? "Approved" : "Rejected"}
                    </span>
                    <span className="text-xs text-gray-500">cycle {d.cycle}</span>
                    {d.targetSubsystem && (
                      <span className="text-xs text-indigo-400">
                        {d.targetSubsystem}
                      </span>
                    )}
                  </div>
                  {d.reasons.length > 0 && (
                    <p className="text-xs text-gray-400 mt-0.5 truncate">
                      {d.reasons.join(" · ")}
                    </p>
                  )}
                </div>
                <span className="text-xs text-gray-600 shrink-0">
                  {d.recordedAt
                    ? new Date(
                        Number(d.recordedAt.seconds) * 1000,
                      ).toLocaleTimeString()
                    : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
