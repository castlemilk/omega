import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  GitBranch,
  BarChart2,
  AlertTriangle,
  Brain,
  TrendingUp,
  ShieldCheck,
  Swords,
  Target,
  Sword,
  History,
  Terminal,
  Activity,
  XCircle,
  PieChart,
  Zap,
  List,
  FlaskConical,
  Layers,
  ChevronDown,
  Cloud,
  TrendingDown,
  Droplets,
  DollarSign,
  BookOpen,
} from "lucide-react";
import { useState } from "react";
import { useProject, projectDisplayName } from "../../context/ProjectContext";
import type { Project } from "../../gen/omega/v1/types_pb";

const OMEGA_NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/projects", icon: Layers, label: "Projects" },
  { to: "/nodes", icon: Server, label: "Nodes" },
  { to: "/traces", icon: GitBranch, label: "Traces" },
  { to: "/metrics", icon: BarChart2, label: "Metrics" },
  { to: "/issues", icon: AlertTriangle, label: "Issues" },
  { to: "/memory", icon: Brain, label: "Memory" },
  { to: "/convergence", icon: TrendingUp, label: "Convergence" },
  { to: "/alignment", icon: ShieldCheck, label: "Alignment" },
  { to: "/adversarial", icon: Swords, label: "Adversarial" },
  { to: "/goals", icon: Target, label: "Goals" },
  { to: "/challenges", icon: Sword, label: "Challenges" },
  { to: "/improvements", icon: History, label: "Improvements" },
];

const OBS_NAV = [
  { to: "/health", icon: Activity, label: "Health" },
  { to: "/perf", icon: BarChart2, label: "Performance" },
  { to: "/errors", icon: XCircle, label: "Errors" },
];

// Victoria's project-specific views.
const VICTORIA_NAV = [
  { to: "/victoria", icon: Terminal, label: "Terminal" },
  { to: "/victoria/portfolio", icon: PieChart, label: "Portfolio" },
  { to: "/victoria/signals", icon: Zap, label: "Signals" },
  { to: "/victoria/trades", icon: List, label: "Trades" },
  { to: "/victoria/backtest", icon: FlaskConical, label: "Backtest" },
  { to: "/projects/victoria/pipeline", icon: GitBranch, label: "Pipeline" },
];

// Polymarket project-specific views.
const POLYMARKET_NAV = [
  { to: "/polymarket", icon: LayoutDashboard, label: "Overview" },
  { to: "/polymarket/markets", icon: Cloud, label: "Markets" },
  { to: "/polymarket/edges", icon: TrendingDown, label: "Edges" },
  { to: "/polymarket/weather", icon: Droplets, label: "Weather" },
  { to: "/polymarket/bets", icon: DollarSign, label: "Bets" },
  { to: "/polymarket/positions", icon: BookOpen, label: "Positions" },
];

function projectNavItems(project: Project) {
  const name = projectDisplayName(project);
  if (name === "Victoria") return VICTORIA_NAV;
  if (name === "Polymarket") return POLYMARKET_NAV;
  return [];
}

function ProjectSelector() {
  const { projects, selectedProject, setSelectedProject } = useProject();
  const [open, setOpen] = useState(false);

  if (projects.length === 0) {
    return <div className="px-3 py-2 text-xs text-gray-600 italic">No projects</div>;
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-surface-700 text-white hover:bg-surface-600 transition-colors"
      >
        <span className="truncate">{selectedProject ? projectDisplayName(selectedProject) : "Select project"}</span>
        <ChevronDown
          size={14}
          className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 bg-surface-700 border border-surface-500 rounded-lg shadow-lg overflow-hidden">
          {projects.map((p) => (
            <button
              key={p.projectId}
              onClick={() => {
                setSelectedProject(p);
                setOpen(false);
              }}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-surface-600 transition-colors ${
                selectedProject?.projectId === p.projectId
                  ? "text-white font-semibold"
                  : "text-gray-300"
              }`}
            >
              <span className="flex items-center gap-2">
                {p.metadata?.color && (
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: p.metadata.color }}
                  />
                )}
                {projectDisplayName(p)}
              </span>
              {p.domain && <span className="text-xs text-gray-500 ml-4">{p.domain}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const { selectedProject } = useProject();
  const projectNav = selectedProject ? projectNavItems(selectedProject) : [];
  const accentColor = selectedProject?.metadata?.color ?? "#00ff00";
  const accentDim = accentColor === "#00ff00" ? "#009900" : accentColor;

  return (
    <aside className="w-56 min-h-screen bg-surface-800 border-r border-surface-600 flex flex-col py-6 px-3 gap-1 shrink-0 overflow-y-auto">
      {/* Logo */}
      <div className="px-3 mb-6">
        <span className="text-xl font-bold tracking-tight text-white">Ω Omega</span>
        <p className="text-xs text-gray-500 mt-0.5">Platform</p>
      </div>

      {/* OMEGA — global platform section */}
      <div className="px-3 mb-2">
        <span className="text-xs text-gray-600 uppercase tracking-widest font-semibold">
          Omega
        </span>
      </div>
      {OMEGA_NAV.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-surface-700"
            }`
          }
        >
          <Icon size={17} />
          {label}
        </NavLink>
      ))}

      {/* Divider */}
      <div className="border-t border-surface-600 my-3" />

      {/* Observability section */}
      <div className="px-3 mb-2">
        <span className="text-xs text-gray-600 uppercase tracking-widest font-semibold">
          Observability
        </span>
      </div>
      {OBS_NAV.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-surface-700"
            }`
          }
        >
          <Icon size={17} />
          {label}
        </NavLink>
      ))}

      {/* Divider */}
      <div className="border-t border-surface-600 my-3" />

      {/* Project selector */}
      <div className="px-3 mb-2">
        <span className="text-xs text-gray-600 uppercase tracking-widest font-semibold">
          Project
        </span>
      </div>
      <div className="mb-2">
        <ProjectSelector />
      </div>

      {/* Selected project nav */}
      {projectNav.length > 0 && selectedProject && (
        <>
          <div className="px-3 mb-1 mt-1">
            <span
              className="text-xs uppercase tracking-widest font-semibold"
              style={{ color: accentDim }}
            >
              {projectDisplayName(selectedProject)}
            </span>
          </div>
          {projectNav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/victoria" || to === "/polymarket"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? "text-black" : "hover:bg-surface-700"
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? { backgroundColor: accentColor, color: "#000", textShadow: "none" }
                  : { color: accentDim }
              }
            >
              <Icon size={17} />
              {label}
            </NavLink>
          ))}
        </>
      )}
    </aside>
  );
}
