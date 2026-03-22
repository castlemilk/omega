import { GitBranch, Layers, Server } from "lucide-react";
import { useProject } from "../context/ProjectContext";
import type { Project } from "../gen/omega/v1/types_pb";

const DOMAIN_LABELS: Record<string, string> = {
  crypto_quant: "Crypto Quant",
  macro_research: "Macro Research",
  options_arb: "Options Arb",
  custom: "Custom",
};

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500/20 text-green-400 border-green-500/30",
  paused: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  archived: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

function ProjectCard({
  project,
  selected,
  onSelect,
}: {
  project: Project;
  selected: boolean;
  onSelect: () => void;
}) {
  const accentColor = project.metadata?.color;
  const statusCls = STATUS_COLORS[project.status] ?? STATUS_COLORS.archived;
  const visibleSteps = project.pipelineConfig.slice(0, 5);
  const remainingSteps = project.pipelineConfig.length - visibleSteps.length;

  return (
    <div
      onClick={onSelect}
      className={`bg-gray-800 rounded-xl border p-5 cursor-pointer transition-all hover:border-indigo-500/50 ${
        selected ? "border-indigo-500 ring-1 ring-indigo-500/30" : "border-gray-700"
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          {accentColor && (
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: accentColor }}
            />
          )}
          <h3 className="text-white font-semibold text-base">{project.name}</h3>
        </div>
        <span
          className={`text-xs px-2 py-0.5 rounded-full border font-medium shrink-0 ${statusCls}`}
        >
          {project.status}
        </span>
      </div>

      {/* Description */}
      {project.description && (
        <p className="text-sm text-gray-400 mb-4 line-clamp-2">{project.description}</p>
      )}

      {/* Stats row */}
      <div className="flex items-center gap-4 text-xs text-gray-500 mb-4">
        <span className="flex items-center gap-1.5">
          <Server size={12} />
          {project.nodeIds.length} node{project.nodeIds.length !== 1 ? "s" : ""}
        </span>
        <span className="flex items-center gap-1.5">
          <GitBranch size={12} />
          {project.pipelineConfig.length} step{project.pipelineConfig.length !== 1 ? "s" : ""}
        </span>
        {project.domain && (
          <span className="bg-gray-700 text-gray-400 px-2 py-0.5 rounded text-xs">
            {DOMAIN_LABELS[project.domain] ?? project.domain}
          </span>
        )}
        {project.autonomyLevel && (
          <span className="text-gray-600 font-mono">{project.autonomyLevel}</span>
        )}
      </div>

      {/* Pipeline steps preview */}
      {visibleSteps.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {visibleSteps
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((step) => (
              <span
                key={step.stepId}
                className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded font-mono"
              >
                {step.order}. {step.name}
              </span>
            ))}
          {remainingSteps > 0 && (
            <span className="text-xs text-gray-600 px-1">+{remainingSteps} more</span>
          )}
        </div>
      )}

      {/* Eval metrics */}
      {project.evalConfig && project.evalConfig.primaryMetrics.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700 flex flex-wrap gap-2">
          {project.evalConfig.primaryMetrics.map((metric) => {
            const target = project.evalConfig?.metricTargets?.[metric];
            return (
              <span key={metric} className="text-xs text-indigo-400 font-mono">
                {metric}
                {target !== undefined ? `: ${target}` : ""}
              </span>
            );
          })}
        </div>
      )}

      {/* Select indicator */}
      <div className="mt-4 text-xs text-center">
        {selected ? (
          <span className="text-indigo-400 font-medium">● Currently selected</span>
        ) : (
          <span className="text-gray-600 hover:text-gray-400 transition-colors">
            Click to select
          </span>
        )}
      </div>
    </div>
  );
}

export default function Projects() {
  const { projects, selectedProject, setSelectedProject, loading } = useProject();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
        Loading projects…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Projects</h1>
        <p className="text-sm text-gray-400 mt-1">
          Configured instances driven by the Omega platform. Omega owns orchestration, eval, and
          self-improvement — projects declare what runs.
        </p>
      </div>

      {projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-gray-500 border border-dashed border-gray-700 rounded-xl">
          <Layers size={40} className="mb-3 opacity-30" />
          <p className="text-sm">No projects configured</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {projects.map((project) => (
            <ProjectCard
              key={project.projectId}
              project={project}
              selected={selectedProject?.projectId === project.projectId}
              onSelect={() => setSelectedProject(project)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
