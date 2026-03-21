import { useCallback } from "react";
import { Sword } from "lucide-react";
import { client } from "../client";
import { usePolling } from "../hooks/usePolling";
import type { Challenge } from "../gen/omega/v1/types_pb";

const STATUS_COLS: Array<{
  key: string;
  label: string;
  borderColor: string;
}> = [
  { key: "open",         label: "Open",         borderColor: "border-t-red-700" },
  { key: "acknowledged", label: "Acknowledged",  borderColor: "border-t-yellow-600" },
  { key: "resolved",     label: "Resolved",      borderColor: "border-t-green-700" },
];

const severityBadge: Record<string, string> = {
  critical: "bg-red-900 text-red-400",
  high:     "bg-orange-900 text-orange-400",
  medium:   "bg-yellow-900 text-yellow-400",
  low:      "bg-blue-900 text-blue-400",
};

function ChallengeCard({ c }: { c: Challenge }) {
  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-3 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            severityBadge[c.severity] ?? "bg-gray-700 text-gray-400"
          }`}
        >
          {c.severity}
        </span>
        {c.targetSubsystem && (
          <span className="text-xs text-gray-500 truncate max-w-[100px]">
            {c.targetSubsystem}
          </span>
        )}
      </div>
      <p className="text-xs text-gray-300 leading-relaxed">
        {c.description || "No description"}
      </p>
      <p className="text-xs text-gray-600">
        {c.createdAt
          ? new Date(Number(c.createdAt.seconds) * 1000).toLocaleDateString()
          : "—"}
      </p>
    </div>
  );
}

export default function Challenges() {
  const fetchFn = useCallback(
    () => client.getChallenges({ statusFilter: "" }),
    [],
  );
  const { data, error, loading } = usePolling(fetchFn);
  const challenges = data?.challenges ?? [];

  const byStatus = (status: string) =>
    challenges.filter((c) => c.status === status);

  if (loading)
    return <div className="text-gray-500 text-sm">Loading challenges…</div>;
  if (error) return <div className="text-red-400 text-sm">Error: {error}</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Sword size={18} className="text-yellow-400" />
        <h1 className="text-lg font-semibold text-white">
          Devil's Advocate Challenges
        </h1>
        <span className="text-xs text-gray-500 ml-1">
          {challenges.length} total
        </span>
      </div>

      {challenges.length === 0 ? (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-8 text-center">
          <p className="text-gray-600 text-sm">No challenges in registry yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {STATUS_COLS.map(({ key, label, borderColor }) => {
            const col = byStatus(key);
            return (
              <div
                key={key}
                className={`bg-gray-900 rounded-xl border-t-2 ${borderColor} border-x border-b border-gray-700 flex flex-col`}
              >
                <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-300 uppercase">
                    {label}
                  </span>
                  <span className="text-xs bg-gray-800 text-gray-400 rounded-full px-2 py-0.5">
                    {col.length}
                  </span>
                </div>
                <div className="p-3 space-y-2 flex-1">
                  {col.length === 0 ? (
                    <p className="text-gray-700 text-xs text-center py-4">
                      Empty
                    </p>
                  ) : (
                    col.map((c) => (
                      <ChallengeCard key={c.challengeId} c={c} />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
