import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FolderOpen,
  Radio,
  TrendingUp,
  Zap,
  Activity,
  BarChart2,
  Terminal,
  PieChart,
  List,
  FlaskConical,
  Server,
  Cpu,
  HeartPulse,
  GitBranch,
  History,
  Swords,
  Brain,
  Target,
  Shield,
  AlertTriangle,
  Settings,
  Network,
  BarChart3,
  GitMerge,
} from "lucide-react";

const NAV_SECTIONS = [
  {
    label: "Overview",
    items: [
      { to: "/", icon: LayoutDashboard, label: "Home" },
      { to: "/projects", icon: FolderOpen, label: "Projects" },
    ],
  },
  {
    label: "Training",
    items: [
      { to: "/training", icon: Radio, label: "Live Feed" },
      { to: "/training/analysis", icon: BarChart2, label: "Analysis" },
      { to: "/convergence", icon: TrendingUp, label: "Cycles" },
      { to: "/metrics", icon: BarChart2, label: "Metrics" },
    ],
  },
  {
    label: "Signals",
    items: [
      { to: "/signals", icon: Activity, label: "Signal Health" },
      { to: "/victoria/signals", icon: Zap, label: "Victoria Signals" },
    ],
  },
  {
    label: "Strategy",
    items: [
      { to: "/victoria", icon: Terminal, label: "Overview" },
      { to: "/victoria/portfolio", icon: PieChart, label: "Portfolio" },
      { to: "/victoria/trades", icon: List, label: "Trades" },
      { to: "/victoria/backtest", icon: FlaskConical, label: "Backtest" },
      { to: "/victoria/geometry", icon: GitMerge, label: "Geometry" },
    ],
  },
  {
    label: "Control Plane",
    items: [
      { to: "/nodes", icon: Server, label: "Nodes" },
      { to: "/control-plane", icon: Cpu, label: "Control Plane" },
      { to: "/health", icon: HeartPulse, label: "System Health" },
      { to: "/traces", icon: GitBranch, label: "Traces" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/improvements", icon: History, label: "Self-Improvement" },
      { to: "/memory", icon: Brain, label: "Memory" },
      { to: "/adversarial", icon: Swords, label: "Adversarial" },
      { to: "/alignment", icon: Shield, label: "Alignment" },
      { to: "/goals", icon: Target, label: "Goals" },
      { to: "/challenges", icon: AlertTriangle, label: "Challenges" },
    ],
  },
  {
    label: "Observability",
    items: [
      { to: "/decisions", icon: Network, label: "Decision Trace" },
      { to: "/node-health", icon: HeartPulse, label: "Node Health" },
      { to: "/trade-analysis", icon: BarChart3, label: "Trade Analysis" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/issues", icon: AlertTriangle, label: "Issues" },
      { to: "/settings", icon: Settings, label: "Settings" },
    ],
  },
];

export default function Sidebar() {
  return (
    <aside className="w-56 min-h-screen bg-surface-800 border-r border-surface-600 flex flex-col py-6 px-3 gap-1 shrink-0 overflow-y-auto">
      {/* Logo */}
      <div className="px-3 mb-6">
        <span className="text-xl font-bold tracking-tight text-white">Ω Omega</span>
        <p className="text-xs text-gray-500 mt-0.5">Platform</p>
      </div>

      {NAV_SECTIONS.map((section, sectionIdx) => (
        <div key={section.label}>
          {sectionIdx > 0 && <div className="border-t border-surface-600 my-3" />}
          <div className="px-3 mb-2">
            <span className="text-xs text-gray-600 uppercase tracking-widest font-semibold">
              {section.label}
            </span>
          </div>
          {section.items.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={`${section.label}-${to}`}
              to={to}
              end={to === "/" || to === "/victoria"}
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
        </div>
      ))}
    </aside>
  );
}
