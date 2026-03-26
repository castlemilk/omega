import { useEffect, useState } from "react";
import { client } from "../client";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { ConvergencePoint, ImprovementRecord } from "../gen/omega/v1/types_pb";

function statusFromScore(score: number): { label: string; cls: string } {
  if (score >= 0.75) return { label: "healthy", cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" };
  if (score >= 0.5) return { label: "degraded", cls: "text-amber-400 bg-amber-500/10 border-amber-500/30" };
  return { label: "critical", cls: "text-red-400 bg-red-500/10 border-red-500/30" };
}

function formatTs(ts?: { seconds: bigint; nanos: number }): string {
  if (!ts) return "—";
  const d = new Date(Number(ts.seconds) * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function Convergence() {
  const [points, setPoints] = useState<ConvergencePoint[]>([]);
  const [improvements, setImprovements] = useState<ImprovementRecord[]>([]);
  const [cyclePage, setCyclePage] = useState(0);
  const CYCLE_PAGE_SIZE = 15;

  useEffect(() => {
    client
      .getConvergence({ limit: 200 })
      .then((r) => setPoints(r.points))
      .catch(console.error);
    client
      .listImprovements({ nodeId: "", limit: 50 })
      .then((r) => setImprovements(r.improvements))
      .catch(console.error);
  }, []);

  const chartData = points.map((p) => ({
    cycle: Number(p.cycle),
    score: p.score,
    ms: p.pipelineMs,
  }));

  // Build cycle rows from convergence points (newest first)
  const cycleRows = [...points].reverse();
  const totalCyclePages = Math.ceil(cycleRows.length / CYCLE_PAGE_SIZE);
  const pagedCycles = cycleRows.slice(cyclePage * CYCLE_PAGE_SIZE, (cyclePage + 1) * CYCLE_PAGE_SIZE);

  // Map improvements by cycle for trades-executed column
  const tradesByCycle = new Map<number, number>();
  for (const imp of improvements) {
    const c = Number(imp.cycle);
    tradesByCycle.set(c, (tradesByCycle.get(c) ?? 0) + 1);
  }

  return (
    <div className="space-y-6">
      {/* Convergence score chart */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Convergence Score
        </h3>
        {chartData.length > 1 ? (
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="cycle"
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  label={{ value: "Cycle", position: "insideBottom", fill: "#64748b" }}
                />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#64748b" }} />
                <Tooltip
                  contentStyle={{
                    background: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: 8,
                  }}
                  formatter={(v: number) => [v.toFixed(4), "Score"]}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#6366f1"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-slate-600 text-sm text-center py-8">
            Run the orchestrator to generate convergence data
          </p>
        )}
      </div>

      {/* Cycles table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700 flex items-center justify-between">
          <div>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Cycle Log
            </h3>
            <p className="text-xs text-slate-600 mt-0.5">{cycleRows.length} cycles recorded</p>
          </div>
          {totalCyclePages > 1 && (
            <div className="flex items-center gap-2">
              <button
                disabled={cyclePage === 0}
                onClick={() => setCyclePage((p) => p - 1)}
                className="text-[10px] font-mono text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed px-2 py-1 rounded hover:bg-slate-700 transition-colors"
              >
                ← prev
              </button>
              <span className="text-[10px] text-slate-500 font-mono">
                {cyclePage + 1} / {totalCyclePages}
              </span>
              <button
                disabled={cyclePage >= totalCyclePages - 1}
                onClick={() => setCyclePage((p) => p + 1)}
                className="text-[10px] font-mono text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed px-2 py-1 rounded hover:bg-slate-700 transition-colors"
              >
                next →
              </button>
            </div>
          )}
        </div>

        {pagedCycles.length === 0 ? (
          <p className="text-center text-slate-600 py-10 text-sm">No cycles yet — start the orchestrator</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700">
                {["Cycle #", "Time", "Duration", "Health Score", "Status", "Improvements"].map((h) => (
                  <th
                    key={h}
                    className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/60">
              {pagedCycles.map((p) => {
                const { label, cls } = statusFromScore(p.score);
                const cycleNum = Number(p.cycle);
                const tradesEx = tradesByCycle.get(cycleNum) ?? 0;
                return (
                  <tr key={cycleNum} className="hover:bg-slate-700/30 transition-colors">
                    <td className="px-4 py-3 font-mono text-indigo-400 font-semibold">
                      #{cycleNum}
                    </td>
                    <td className="px-4 py-3 text-slate-400 font-mono">
                      {formatTs(p.timestamp)}
                    </td>
                    <td className="px-4 py-3 text-slate-300 font-mono">
                      {p.pipelineMs < 1000
                        ? `${p.pipelineMs.toFixed(0)}ms`
                        : `${(p.pipelineMs / 1000).toFixed(2)}s`}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-16 bg-slate-700 rounded-full h-1.5">
                          <div
                            className={`h-1.5 rounded-full ${
                              p.score >= 0.75
                                ? "bg-emerald-500"
                                : p.score >= 0.5
                                  ? "bg-amber-500"
                                  : "bg-red-500"
                            }`}
                            style={{ width: `${p.score * 100}%` }}
                          />
                        </div>
                        <span className="text-slate-300 font-mono">{p.score.toFixed(3)}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${cls}`}>
                        {label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400 font-mono">
                      {tradesEx > 0 ? (
                        <span className="text-emerald-400">{tradesEx}</span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Improvement Log */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-3 border-b border-slate-700 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Improvement Log ({improvements.length})
        </div>
        <div className="divide-y divide-slate-700 max-h-64 overflow-auto">
          {improvements.map((imp) => (
            <div key={imp.improveId} className="px-4 py-3 flex items-center gap-3 text-sm">
              <span className="text-slate-500 text-xs w-12 shrink-0 font-mono">cy {String(imp.cycle)}</span>
              <span className="text-slate-100 font-medium shrink-0">{imp.nodeName}</span>
              <span className="text-slate-400 text-xs font-mono">
                v{imp.fromVersion} → v{imp.toVersion}
              </span>
              <span className="text-slate-600 text-xs ml-auto">{imp.triggeredBy}</span>
            </div>
          ))}
          {improvements.length === 0 && (
            <p className="text-center text-slate-600 py-8 text-sm">No improvements yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
