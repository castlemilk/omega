import { useCallback } from "react";
import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { CheckCircle2, XCircle, Target } from "lucide-react";
import { client } from "../client";
import { usePolling } from "../hooks/usePolling";

export default function Goals() {
  const fetchFn = useCallback(() => client.getGoalTracking({}), []);
  const { data, error, loading } = usePolling(fetchFn);
  const state = data?.state ?? null;

  const constitutionalEntries = state ? Object.entries(state.constitutionalChecks) : [];

  const scorecardData = state
    ? Object.entries(state.scorecardValues).map(([key, value]) => ({
        subject: key,
        value: Math.min(100, Math.max(0, value * 100)),
        fullMark: 100,
      }))
    : [];

  if (loading) return <div className="text-gray-500 text-sm">Loading goal state…</div>;
  if (error) return <div className="text-red-400 text-sm">Error: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Target size={18} className="text-indigo-400" />
        <h1 className="text-lg font-semibold text-white">Goal Tracking</h1>
        {state && <span className="text-xs text-gray-500 ml-2">cycle {Number(state.cycle)}</span>}
      </div>

      {!state ? (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-8 text-center">
          <p className="text-gray-600 text-sm">No goal state recorded yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {/* Constitutional checks */}
          <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
            <p className="text-xs text-gray-400 uppercase font-medium mb-3">
              Constitutional Constraints
            </p>
            {constitutionalEntries.length === 0 ? (
              <p className="text-gray-600 text-sm text-center py-4">None recorded</p>
            ) : (
              <div className="space-y-2">
                {constitutionalEntries.map(([constraint, passed]) => (
                  <div key={constraint} className="flex items-center justify-between">
                    <span className="text-sm text-gray-300 truncate max-w-[200px]">
                      {constraint}
                    </span>
                    {passed ? (
                      <CheckCircle2 size={16} className="text-green-400 shrink-0" />
                    ) : (
                      <XCircle size={16} className="text-red-400 shrink-0" />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Balanced scorecard radar */}
          <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
            <p className="text-xs text-gray-400 uppercase font-medium mb-3">Balanced Scorecard</p>
            {scorecardData.length < 3 ? (
              <p className="text-gray-600 text-sm text-center py-4">Insufficient scorecard data</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <RadarChart data={scorecardData}>
                  <PolarGrid stroke="#374151" />
                  <PolarAngleAxis dataKey="subject" tick={{ fill: "#9ca3af", fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      background: "#1f2937",
                      border: "none",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(v: number) => [`${v.toFixed(0)}%`]}
                  />
                  <Radar dataKey="value" stroke="#818cf8" fill="#818cf8" fillOpacity={0.25} />
                </RadarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}

      {/* Active HTN tasks */}
      {state && state.activeTasks.length > 0 && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-400 uppercase font-medium mb-3">Active HTN Tasks</p>
          <ul className="space-y-1">
            {state.activeTasks.map((task, i) => (
              <li key={i} className="text-sm text-gray-300 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 shrink-0" />
                {task}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
