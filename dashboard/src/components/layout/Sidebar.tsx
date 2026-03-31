import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  TrendingUp,
  History,
  Swords,
  Terminal,
  Activity,
  PieChart,
  Zap,
  List,
  FlaskConical,
  Radio,
  Cpu,
} from "lucide-react";

const NAV_SECTIONS = [
  {
    label: "Overview",
    items: [
      { to: "/", icon: LayoutDashboard, label: "Dashboard" },
    ],
  },
  {
    label: "Trading",
    items: [
      { to: "/victoria", icon: Terminal, label: "Victoria" },
      { to: "/victoria/portfolio", icon: PieChart, label: "Portfolio" },
      { to: "/victoria/trades", icon: List, label: "Trades" },
      { to: "/victoria/signals", icon: Zap, label: "Signals" },
      { to: "/victoria/backtest", icon: FlaskConical, label: "Backtest" },
    ],
  },
  {
    label: "Training",
    items: [
      { to: "/training", icon: Radio, label: "Training" },
      { to: "/convergence", icon: TrendingUp, label: "Cycles" },
    ],
  },
  {
    label: "Platform",
    items: [
      { to: "/nodes", icon: Server, label: "Nodes" },
      { to: "/control-plane", icon: Cpu, label: "Control Plane" },
      { to: "/health", icon: Activity, label: "System Health" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/improvements", icon: History, label: "Improvements" },
      { to: "/adversarial", icon: Swords, label: "Adversarial" },
      { to: "/convergence", icon: TrendingUp, label: "Convergence" },
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
              end={to === "/" || to === "/victoria" || to === "/convergence"}
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
