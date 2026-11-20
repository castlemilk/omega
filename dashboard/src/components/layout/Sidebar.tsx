import { useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Building2,
  Menu,
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

const studioCommand: string | null = import.meta.env.BUSINESS_STUDIO_COMMAND;
const NAV_SECTIONS = [
  {
    label: "Overview",
    items: [
      { to: "/", icon: LayoutDashboard, label: "Home" },
      ...(studioCommand ? [{ to: studioCommand, icon: Building2, label: "Business Studio" }] : []),
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
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  return (
    <aside
      className="w-full sm:w-56 sm:min-h-screen bg-surface-800 border-b sm:border-b-0 sm:border-r border-surface-600 flex flex-col px-3 sm:py-6 gap-1 shrink-0 sm:overflow-y-auto"
      onKeyDown={(event) => {
        if (event.key === "Escape" && menuOpen) {
          setMenuOpen(false);
          menuButton.current?.focus();
        }
      }}
    >
      {/* Logo */}
      <div className="flex sm:block items-center gap-3 py-1 sm:py-0 sm:px-3 sm:mb-6">
        <span className="mr-auto text-xl font-bold tracking-tight text-white">Ω Omega</span>
        <p className="hidden sm:block text-xs text-gray-500 mt-0.5">Platform</p>
        {studioCommand && (
          <a
            href={studioCommand}
            referrerPolicy="no-referrer"
            className="sm:hidden inline-flex min-h-11 items-center gap-2 rounded-md px-2 text-sm font-medium text-gray-100"
          >
            <Building2 size={17} aria-hidden="true" />
            Business Studio
          </a>
        )}
        <button
          type="button"
          ref={menuButton}
          aria-label="Navigation menu"
          aria-controls="platform-navigation"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(!menuOpen)}
          className="sm:hidden inline-flex size-11 items-center justify-center rounded-md text-gray-300 hover:bg-surface-700"
        >
          <Menu size={20} aria-hidden="true" />
        </button>
      </div>
      <nav
        id="platform-navigation"
        aria-label="Platform navigation"
        className={`${menuOpen ? "block" : "hidden"} max-h-[55dvh] overflow-y-auto sm:block sm:max-h-none sm:overflow-visible`}
      >
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
                reloadDocument={to === studioCommand}
                referrerPolicy={to === studioCommand ? "no-referrer" : undefined}
                onClick={() => setMenuOpen(false)}
                end={to === "/" || to === "/victoria"}
                className={({ isActive }) =>
                  `${to === studioCommand ? "hidden sm:flex" : "flex"} items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
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
      </nav>
    </aside>
  );
}
