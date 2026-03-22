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
  PieChart,
  Zap,
  List,
  FlaskConical,
} from "lucide-react";

const OMEGA_NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
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

const VICTORIA_NAV = [
  { to: "/victoria", icon: Terminal, label: "Terminal" },
  { to: "/victoria/portfolio", icon: PieChart, label: "Portfolio" },
  { to: "/victoria/signals", icon: Zap, label: "Signals" },
  { to: "/victoria/trades", icon: List, label: "Trades" },
  { to: "/victoria/backtest", icon: FlaskConical, label: "Backtest" },
];

export default function Sidebar() {
  return (
    <aside className="w-56 min-h-screen bg-surface-800 border-r border-surface-600 flex flex-col py-6 px-3 gap-1 shrink-0 overflow-y-auto">
      <div className="px-3 mb-6">
        <span className="text-xl font-bold tracking-tight text-white">Ω Omega</span>
        <p className="text-xs text-gray-500 mt-0.5">Agent Dashboard</p>
      </div>

      {/* Omega section */}
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

      {/* Victoria section */}
      <div className="px-3 mb-2">
        <span
          className="text-xs uppercase tracking-widest font-semibold"
          style={{ color: "#009900" }}
        >
          Victoria
        </span>
      </div>
      {VICTORIA_NAV.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/victoria"}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              isActive ? "text-black" : "hover:bg-surface-700"
            }`
          }
          style={({ isActive }) =>
            isActive
              ? { backgroundColor: "#00ff00", color: "#000", textShadow: "none" }
              : { color: "#009900" }
          }
        >
          <Icon size={17} />
          {label}
        </NavLink>
      ))}
    </aside>
  );
}
