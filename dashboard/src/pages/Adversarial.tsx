import { useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";
import { Swords } from "lucide-react";
import { client } from "../client";
import { usePolling } from "../hooks/usePolling";

const severityColor: Record<string, string> = {
  critical: "bg-red-900 text-red-400",
  high: "bg-orange-900 text-orange-400",
  medium: "bg-yellow-900 text-yellow-400",
  low: "bg-blue-900 text-blue-400",
};

export default function Adversarial() {
  const fetchFn = useCallback(
    () => client.getAdversarialResults({ limit: 100 }),
    [],
  );
  const { data, error, loading } = usePolling(fetchFn);
  const results = data?.results ?? [];

  // Flags per ring
  const ringCounts: Record<number, number> = {};
  const severityCounts: Record<string, number> = {};
  for (const r of results) {
    ringCounts[r.ring] = (ringCounts[r.ring] ?? 0) + r.flags.length;
    severityCounts[r.severity] = (severityCounts[r.severity] ?? 0) + 1;
  }
  const ringData = Object.entries(ringCounts).map(([ring, flags]) => ({
    ring: `Ring ${ring}`,
    flags,
  }));
  const severityData = Object.entries(severityCounts).map(([sev, count]) => ({
    sev,
    count,
  }));

  // Flags per cycle for timeline
  const cycleMap = new Map<bigint, number>();
  for (const r of results) {
    cycleMap.set(r.cycle, (cycleMap.get(r.cycle) ?? 0) + r.flags.length);
  }
  const timelineData = [...cycleMap.entries()]
    .sort((a, b) => Number(a[0] - b[0]))
    .map(([cycle, flags]) => ({ cycle: Number(cycle), flags }));

  if (loading)
    return <div className="text-gray-500 text-sm">Loading adversarial data…</div>;
  if (error) return <div className="text-red-400 text-sm">Error: {error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Swords size={18} className="text-orange-400" />
        <h1 className="text-lg font-semibold text-white">Adversarial Pressure</h1>
        <span className="text-xs text-gray-500 ml-1">{results.length} results</span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Flags by ring */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-400 uppercase font-medium mb-3">
            Flags by Ring
          </p>
          {ringData.length === 0 ? (
            <p className="text-gray-600 text-sm text-center py-4">No data</p>
          ) : (
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={ringData}>
                <XAxis dataKey="ring" tick={{ fill: "#9ca3af", fontSize: 11 }} />
                <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    background: "#1f2937",
                    border: "none",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="flags" fill="#f97316" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Severity distribution */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-400 uppercase font-medium mb-3">
            Severity Distribution
          </p>
          <div className="space-y-2 mt-2">
            {severityData.length === 0 ? (
              <p className="text-gray-600 text-sm text-center py-4">No data</p>
            ) : (
              severityData.map(({ sev, count }) => (
                <div key={sev} className="flex items-center justify-between">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      severityColor[sev] ?? "bg-gray-700 text-gray-400"
                    }`}
                  >
                    {sev}
                  </span>
                  <span className="text-sm font-mono text-gray-300">{count}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {timelineData.length > 1 && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-400 uppercase font-medium mb-3">
            Flags Over Cycles
          </p>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={timelineData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="cycle" tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: "#1f2937",
                  border: "none",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="flags"
                stroke="#f97316"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent results table */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-700">
          <p className="text-xs text-gray-400 uppercase font-medium">Recent Results</p>
        </div>
        {results.length === 0 ? (
          <p className="text-center text-gray-600 py-8 text-sm">
            No adversarial results recorded yet
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-400 uppercase bg-gray-900">
              <tr>
                {["Cycle", "Ring", "Severity", "Flags"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {results.slice(0, 50).map((r) => (
                <tr key={r.resultId}>
                  <td className="px-4 py-3 font-mono text-xs text-gray-400">
                    {Number(r.cycle)}
                  </td>
                  <td className="px-4 py-3 text-gray-300">{r.ring}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        severityColor[r.severity] ?? "bg-gray-700 text-gray-400"
                      }`}
                    >
                      {r.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs max-w-xs truncate">
                    {r.flags.join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
