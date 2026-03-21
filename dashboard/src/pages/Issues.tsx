import { useEffect, useState } from "react";
import { client } from "../client";
import type { Issue } from "../gen/omega/v1/types_pb";

const severityColor: Record<string, string> = {
  error: "bg-red-900 text-red-400",
  warning: "bg-yellow-900 text-yellow-400",
  info: "bg-blue-900 text-blue-400",
};

export default function Issues() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [filter, setFilter] = useState("open");

  useEffect(() => {
    client
      .listIssues({ stateFilter: filter })
      .then((r) => setIssues(r.issues))
      .catch(console.error);
  }, [filter]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {["open", "resolved", "all"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${filter === f ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs text-gray-400 uppercase bg-gray-900">
            <tr>
              {["Severity", "Detector", "Description", "State", "Opened"].map((h) => (
                <th key={h} className="px-4 py-3 text-left font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {issues.map((issue) => (
              <tr key={issue.issueId} className="hover:bg-gray-750">
                <td className="px-4 py-3">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${severityColor[issue.severity] ?? "bg-gray-700 text-gray-400"}`}
                  >
                    {issue.severity}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{issue.detector}</td>
                <td className="px-4 py-3 text-gray-200 max-w-xs truncate">{issue.description}</td>
                <td className="px-4 py-3 text-gray-400">{issue.state}</td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {issue.openedAt
                    ? new Date(Number(issue.openedAt.seconds) * 1000).toLocaleString()
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {issues.length === 0 && (
          <p className="text-center text-gray-600 py-8 text-sm">No issues — system clean</p>
        )}
      </div>
    </div>
  );
}
