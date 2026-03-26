import React, { useState } from 'react'
import { NavLink, useParams, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Server, RefreshCw, Shield, TrendingUp, Activity,
  ChevronLeft, ChevronRight, Settings, GitBranch, BarChart2,
  Briefcase, Zap, BookOpen, Brain, Grid3X3, Dumbbell,
} from 'lucide-react'
import { ProjectSwitcher } from './ProjectSwitcher'

// ─── Nav config ──────────────────────────────────────────────────────────────

const globalNav = [
  { to: '/',            label: 'Overview',      icon: LayoutDashboard, end: true },
  { to: '/coordination', label: 'Coordination', icon: GitBranch },
  { to: '/training',    label: 'Training',      icon: Dumbbell, pulse: true },
  { to: '/settings',    label: 'Settings',      icon: Settings },
]

function projectNav(projectId: string) {
  const base = `/projects/${projectId}`
  return [
    { to: base,               label: 'Overview',    icon: LayoutDashboard, end: true },
    { to: `${base}/trading`,  label: 'Trading',     icon: Briefcase },
    { to: `${base}/signals`,  label: 'Signals',     icon: Zap },
    { to: `${base}/positions`,label: 'Positions',   icon: BarChart2 },
    { to: `${base}/nodes`,    label: 'Nodes',       icon: Server },
    { to: `${base}/cycles`,   label: 'Cycles',      icon: RefreshCw },
    { to: `${base}/adversarial`, label: 'Adversarial', icon: Shield },
    { to: `${base}/health`,   label: 'Health',      icon: Activity },
    { to: `${base}/improvement`,   label: 'Improvement',  icon: TrendingUp },
    { to: `${base}/memory`,        label: 'Memory',       icon: Brain },
    { to: `${base}/correlations`,  label: 'Correlations', icon: Grid3X3 },
    { to: `${base}/regime`,        label: 'Regime',       icon: BarChart2 },
  ]
}

// ─── NavItem ─────────────────────────────────────────────────────────────────

function NavItem({
  to, label, icon: Icon, collapsed, end, pulse,
}: { to: string; label: string; icon: React.ElementType; collapsed: boolean; end?: boolean; pulse?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? 'bg-emerald-500/15 text-emerald-300'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
        } ${collapsed ? 'justify-center' : ''}`
      }
      title={collapsed ? label : undefined}
    >
      <div className="relative shrink-0">
        <Icon className="w-4 h-4" />
        {pulse && (
          <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        )}
      </div>
      {!collapsed && label}
    </NavLink>
  )
}

// ─── AppShell ─────────────────────────────────────────────────────────────────

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const { projectId } = useParams<{ projectId: string }>()
  const location = useLocation()

  // Determine if we're in a project context
  const isProjectRoute = location.pathname.startsWith('/projects/')
  const activeProjectId = projectId ?? (isProjectRoute ? location.pathname.split('/')[2] : null)

  return (
    <div className="flex h-screen bg-slate-900 overflow-hidden">
      {/* ── Sidebar ── */}
      <aside
        className={`flex flex-col bg-slate-950 border-r border-slate-800 transition-all duration-200 shrink-0 ${
          collapsed ? 'w-16' : 'w-60'
        }`}
        data-testid="sidebar"
      >
        {/* Logo */}
        <div
          className={`flex items-center gap-3 px-4 py-4 border-b border-slate-800 ${
            collapsed ? 'justify-center' : ''
          }`}
        >
          <div className="w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center shrink-0">
            <span className="text-slate-900 font-black text-xs">Ω</span>
          </div>
          {!collapsed && (
            <div>
              <p className="text-slate-100 font-bold text-sm leading-tight">Omega</p>
              <p className="text-slate-500 text-xs">Platform</p>
            </div>
          )}
        </div>

        {/* Global nav */}
        <nav className="px-2 pt-3 pb-2 space-y-0.5">
          {!collapsed && (
            <p className="px-3 pb-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wider">
              Platform
            </p>
          )}
          {globalNav.map(({ to, label, icon, end, pulse }) => (
            <NavItem key={to} to={to} label={label} icon={icon} collapsed={collapsed} end={end} pulse={pulse} />
          ))}
        </nav>

        {/* Divider */}
        <div className="mx-3 border-t border-slate-800/60 my-1" />

        {/* Project switcher */}
        <div className="px-0 py-2">
          {!collapsed && (
            <p className="px-5 pb-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wider">
              Project
            </p>
          )}
          <ProjectSwitcher collapsed={collapsed} />
        </div>

        {/* Per-project nav */}
        {activeProjectId && (
          <nav className="flex-1 px-2 py-1 space-y-0.5 overflow-y-auto">
            {projectNav(activeProjectId).map(({ to, label, icon, end }) => (
              <NavItem key={to} to={to} label={label} icon={icon} collapsed={collapsed} end={end} />
            ))}
          </nav>
        )}

        {!activeProjectId && <div className="flex-1" />}

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className={`flex items-center gap-2 px-4 py-3 text-slate-500 hover:text-slate-300 border-t border-slate-800 transition-colors text-xs ${
            collapsed ? 'justify-center' : ''
          }`}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          data-testid="sidebar-collapse-btn"
        >
          {collapsed
            ? <ChevronRight className="w-4 h-4" />
            : <><ChevronLeft className="w-4 h-4" /><span>Collapse</span></>
          }
        </button>
      </aside>

      {/* ── Main ── */}
      <main className="flex-1 overflow-y-auto" data-testid="main-content">
        <div className="max-w-7xl mx-auto px-6 py-8">
          {children}
        </div>
      </main>
    </div>
  )
}
