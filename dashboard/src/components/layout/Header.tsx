import { useState } from "react";
import { client } from "../../client";
import { Play, Square, Zap } from "lucide-react";

interface HeaderProps {
  systemStatus?: string;
  connected?: boolean;
}

export default function Header({ systemStatus, connected }: HeaderProps) {
  const [loading, setLoading] = useState<string | null>(null);

  const statusColor =
    {
      healthy: "bg-green-500",
      degraded: "bg-yellow-500",
      critical: "bg-red-500",
      no_nodes: "bg-gray-500",
    }[systemStatus ?? "no_nodes"] ?? "bg-gray-500";

  async function action(name: "start" | "stop" | "trigger") {
    setLoading(name);
    try {
      if (name === "start") await client.startOrchestrator({ heartbeatSecs: 120 });
      else if (name === "stop") await client.stopOrchestrator({});
      else await client.triggerHeartbeat({});
    } finally {
      setLoading(null);
    }
  }

  return (
    <header className="h-14 bg-surface-800 border-b border-surface-600 flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-3">
        <span className={`w-2.5 h-2.5 rounded-full ${statusColor}`} />
        <span className="text-sm font-medium text-gray-300 capitalize">
          {systemStatus ?? "unknown"}
        </span>
        {connected !== undefined && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full border ${
              connected ? "border-green-600 text-green-400" : "border-gray-600 text-gray-500"
            }`}
          >
            {connected ? "streaming" : "offline"}
          </span>
        )}
      </div>
      <div className="flex gap-2">
        {(["start", "trigger", "stop"] as const).map((name) => (
          <button
            key={name}
            onClick={() => action(name)}
            disabled={!!loading}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors disabled:opacity-50 ${
              name === "start"
                ? "bg-green-700 hover:bg-green-600"
                : name === "trigger"
                  ? "bg-indigo-700 hover:bg-indigo-600"
                  : "bg-red-800 hover:bg-red-700"
            } text-white`}
          >
            {name === "start" ? (
              <Play size={13} />
            ) : name === "stop" ? (
              <Square size={13} />
            ) : (
              <Zap size={13} />
            )}
            {name.charAt(0).toUpperCase() + name.slice(1)}
          </button>
        ))}
      </div>
    </header>
  );
}
