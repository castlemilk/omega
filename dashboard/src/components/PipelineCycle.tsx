// PipelineCycle — horizontal stepper showing the Victoria 9-step execution pipeline.
// Status is derived by matching step names against registered node data.
import type { Node } from "../gen/omega/v1/types_pb";

const STEPS = [
  { key: "data_ingestion", label: "DataIngestion", short: "INGEST" },
  { key: "signal_research", label: "SignalResearch", short: "SIGNALS" },
  { key: "ic_scoring", label: "IC Scoring", short: "IC" },
  { key: "dynamic_weights", label: "DynamicWeights", short: "WEIGHTS" },
  { key: "debate_gate", label: "DebateGate", short: "GATE" },
  { key: "walk_forward", label: "WalkForward", short: "WALK" },
  { key: "memory", label: "Memory", short: "MEM" },
  { key: "improvement_engine", label: "ImprovementEngine", short: "IMPROVE" },
  { key: "ring3_adversarial", label: "Ring3Adversarial", short: "ADVERSARIAL" },
] as const;

type StepStatus = "idle" | "running" | "completed" | "error";

function resolveStatus(stepKey: string, nodes: Node[]): StepStatus {
  const node = nodes.find(
    (n) =>
      n.nodeId.toLowerCase().includes(stepKey.replace(/_/g, "")) ||
      n.name
        .toLowerCase()
        .replace(/[\s_-]/g, "")
        .includes(stepKey.replace(/_/g, ""))
  );
  if (!node) return "idle";
  if (node.status === "error" || node.errorRate > 0.5) return "error";
  if (node.status === "running") return "running";
  if (node.status === "healthy" || node.executionsTotal > 0) return "completed";
  return "idle";
}

const STATUS_COLORS: Record<
  StepStatus,
  { bg: string; border: string; text: string; dot: string }
> = {
  idle: {
    bg: "bg-gray-800",
    border: "border-gray-700",
    text: "text-gray-500",
    dot: "bg-gray-600",
  },
  running: {
    bg: "bg-indigo-900/40",
    border: "border-indigo-500",
    text: "text-indigo-300",
    dot: "bg-indigo-400",
  },
  completed: {
    bg: "bg-green-900/30",
    border: "border-green-600",
    text: "text-green-400",
    dot: "bg-green-500",
  },
  error: {
    bg: "bg-red-900/30",
    border: "border-red-600",
    text: "text-red-400",
    dot: "bg-red-500",
  },
};

const STATUS_LABELS: Record<StepStatus, string> = {
  idle: "IDLE",
  running: "RUNNING",
  completed: "OK",
  error: "ERR",
};

interface PipelineCycleProps {
  nodes: Node[];
  totalCycles?: number;
}

export default function PipelineCycle({ nodes, totalCycles }: PipelineCycleProps) {
  const steps = STEPS.map((s) => ({
    ...s,
    status: resolveStatus(s.key, nodes) as StepStatus,
  }));

  const runningCount = steps.filter((s) => s.status === "running").length;
  const completedCount = steps.filter((s) => s.status === "completed").length;
  const errorCount = steps.filter((s) => s.status === "error").length;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">
          Victoria Pipeline
        </h2>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {totalCycles !== undefined && totalCycles > 0 && (
            <span className="font-mono">cycle #{totalCycles}</span>
          )}
          {runningCount > 0 && <span className="text-indigo-400">{runningCount} running</span>}
          {errorCount > 0 && <span className="text-red-400">{errorCount} errors</span>}
          {completedCount === STEPS.length && <span className="text-green-400">all healthy</span>}
        </div>
      </div>

      {/* Stepper row */}
      <div className="bg-gray-900 rounded-xl border border-gray-700 p-4 overflow-x-auto">
        <div className="flex items-start min-w-max gap-0">
          {steps.map((step, idx) => {
            const colors = STATUS_COLORS[step.status];
            return (
              <div key={step.key} className="flex items-start">
                {/* Step card */}
                <div
                  className={`flex flex-col items-center gap-1.5 px-3 py-2 rounded-lg border ${colors.bg} ${colors.border} min-w-[90px] relative`}
                >
                  {/* Status dot — pulse animation when running */}
                  <span
                    className={`w-2 h-2 rounded-full ${colors.dot} ${step.status === "running" ? "animate-pulse" : ""}`}
                  />

                  {/* Step number */}
                  <span className="text-xs text-gray-600 font-mono leading-none">
                    {String(idx + 1).padStart(2, "0")}
                  </span>

                  {/* Step short label */}
                  <span
                    className={`text-xs font-mono font-semibold tracking-tight leading-none text-center ${colors.text}`}
                  >
                    {step.short}
                  </span>

                  {/* Status badge */}
                  <span
                    className={`text-[9px] font-mono uppercase tracking-wider ${colors.text} opacity-70`}
                  >
                    {STATUS_LABELS[step.status]}
                  </span>
                </div>

                {/* Connector arrow between steps */}
                {idx < steps.length - 1 && (
                  <div className="flex items-center self-center mx-1">
                    <div className="w-4 h-px bg-gray-700" />
                    <svg
                      width="6"
                      height="8"
                      viewBox="0 0 6 8"
                      className="text-gray-600"
                      fill="currentColor"
                    >
                      <path d="M0 0 L6 4 L0 8 Z" />
                    </svg>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
