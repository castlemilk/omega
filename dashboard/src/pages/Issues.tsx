import { useEffect, useMemo, useState } from "react";
import { client } from "../client";
import type { Issue } from "../gen/omega/v1/types_pb";

const severityColor: Record<string, string> = {
  error: "bg-red-900 text-red-400",
  warning: "bg-yellow-900 text-yellow-400",
  info: "bg-blue-900 text-blue-400",
};

const severityOrder: Record<string, number> = {
  error: 0,
  warning: 1,
  info: 2,
};

interface GroupedIssue {
  representative: Issue;
  count: number;
  lastSeenSeconds: number;
}

function formatTs(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
}

export default function Issues() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [filter, setFilter] = useState("open");

  useEffect(() => {
    client
      .listIssues({ stateFilter: filter })
      .then((r) => setIssues(r.issues))
      .catch(console.error);
  }, [filter]);

  // Deduplicate: group by severity + detector + description
  const grouped = useMemo<GroupedIssue[]>(() => {
    const map = new Map<string, GroupedIssue>();
    for (const issue of issues) {
      const key = `${issue.severity}::${issue.detector}::${issue.description}`;
      const existing = map.get(key);
      const issueSecs = issue.openedAt ? Number(issue.openedAt.seconds) : 0;
      if (!existing) {
        map.set(key, { representative: issue, count: 1, lastSeenSeconds: issueSecs });
      } else {
        existing.count++;
        if (issueSecs > existing.lastSeenSeconds) {
          existing.lastSeenSeconds = issueSecs;
        }
      }
    }
    // Sort: severity order first, then by lastSeen descending
    return Array.from(map.values()).sort((a, b) => {
      const sa = severityOrder[a.representative.severity] ?? 99;
      const sb = severityOrder[b.representative.severity] ?? 99;
      if (sa !== sb) return sa - sb;
      return b.lastSeenSeconds - a.lastSeenSeconds;
    });
  }, [issues]);

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
        {grouped.length < issues.length && (
          <span className="ml-auto text-xs text-gray-500">
            {issues.length} occurrences → {grouped.length} unique
          </span>
        )}
      </div>
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs text-gray-400 uppercase bg-gray-900">
            <tr>
              {["Severity", "Detector", "Description", "Occurrences", "Last Seen", "State"].map(
                (h) => (
                  <th key={h} className="px-4 py-3 text-left font-medium">
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {grouped.map(({ representative: issue, count, lastSeenSeconds }) => (
              <tr
                key={`${issue.severity}::${issue.detector}::${issue.description}`}
                className="hover:bg-gray-750"
              >
                <td className="px-4 py-3">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${severityColor[issue.severity] ?? "bg-gray-700 text-gray-400"}`}
                  >
                    {issue.severity}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{issue.detector}</td>
                <td className="px-4 py-3 text-gray-200 max-w-sm">{issue.description}</td>
                <td className="px-4 py-3">
                  {count > 1 ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-300 font-mono">
                      ×{count}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-600">1</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {lastSeenSeconds > 0 ? formatTs(lastSeenSeconds) : "—"}
                </td>
                <td className="px-4 py-3 text-gray-400">{issue.state}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {grouped.length === 0 && (
          <p className="text-center text-gray-600 py-8 text-sm">No issues — system clean</p>
        )}
      </div>
    </div>
  );
}
