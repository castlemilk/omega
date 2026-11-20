import React, { useRef, useState } from 'react'
import { NavLink, useParams, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Server, RefreshCw, Shield, TrendingUp, Activity,
  ChevronLeft, ChevronRight, Settings, GitBranch, BarChart2,
  Briefcase, Building2, Menu, Zap, CloudRain, Cloud, Layers, Brain, Radio,
} from 'lucide-react'
import { ProjectSwitcher } from './ProjectSwitcher'

// ─── Nav config ──────────────────────────────────────────────────────────────

const studioCommand: string | null = import.meta.env.BUSINESS_STUDIO_COMMAND
const globalNav = [
  { to: '/',               label: 'Overview',       icon: LayoutDashboard, end: true },
  ...(studioCommand ? [{ to: studioCommand, label: 'Business Studio', icon: Building2 }] : []),
  { to: '/nodes/registry', label: 'Node Registry',  icon: Server },
  { to: '/training',       label: 'Training',       icon: Brain, pulse: true },
  { to: '/coordination',   label: 'Coordination',   icon: GitBranch },
  { to: '/control-plane',  label: 'Control Plane',  icon: Radio },
  { to: '/settings',       label: 'Settings',       icon: Settings },
]

/** Per-project nav registry. Keys are normalised project IDs (strip "proj_"). */
const PROJECT_NAV: Record<string, Array<{ segment: string; label: string; icon: React.ElementType; end?: boolean }>> = {
  victoria: [
    { segment: '',            label: 'Overview',    icon: LayoutDashboard, end: true },
    { segment: 'trading',     label: 'Trading',     icon: Briefcase },
    { segment: 'signals',     label: 'Signals',     icon: Zap },
    { segment: 'positions',   label: 'Positions',   icon: BarChart2 },
    { segment: 'nodes',       label: 'Nodes',       icon: Server },
    { segment: 'cycles',      label: 'Cycles',      icon: RefreshCw },
    { segment: 'adversarial', label: 'Adversarial', icon: Shield },
    { segment: 'health',      label: 'Health',      icon: Activity },
    { segment: 'improvement', label: 'Improvement', icon: TrendingUp },
  ],
  polymarket: [
    { segment: '',        label: 'Overview', icon: LayoutDashboard, end: true },
    { segment: 'markets', label: 'Markets',  icon: Layers },
    { segment: 'edges',   label: 'Edges',    icon: TrendingUp },
    { segment: 'weather', label: 'Weather',  icon: CloudRain },
    { segment: 'bets',    label: 'Bets',     icon: Cloud },
  ],
}

/** Default nav for any unknown project. */
const DEFAULT_NAV = [
  { segment: '', label: 'Overview', icon: LayoutDashboard, end: true },
]

function getProjectNav(projectId: string) {
  const normalised = projectId.replace(/^proj_/i, '').toLowerCase()
  const items = PROJECT_NAV[normalised] ?? DEFAULT_NAV
  const base = `/projects/${projectId}`
  return items.map(({ segment, label, icon, end }) => ({
    to: segment ? `${base}/${segment}` : base,
    label,
    icon,
    end,
  }))
}

// ─── NavItem ─────────────────────────────────────────────────────────────────

function NavItem({
  to, label, icon: Icon, collapsed, end, pulse,
}: { to: string; label: string; icon: React.ElementType; collapsed: boolean; end?: boolean; pulse?: boolean }) {
  return (
    <NavLink
      to={to}
      reloadDocument={to === studioCommand}
      referrerPolicy={to === studioCommand ? 'no-referrer' : undefined}
      end={end}
      className={({ isActive }) =>
        `w-full ${to === studioCommand ? 'hidden sm:flex' : 'flex'} items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? 'bg-emerald-500/15 text-emerald-300'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
        } ${collapsed ? 'justify-center' : ''}`
      }
      title={collapsed ? label : undefined}
    >
      <Icon className="w-4 h-4 shrink-0" />
      {!collapsed && (
        <span className="flex-1 flex items-center justify-between">
          {label}
          {pulse && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
          )}
        </span>
      )}
    </NavLink>
  )
}

// ─── AppShell ─────────────────────────────────────────────────────────────────

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const { projectId } = useParams<{ projectId: string }>()
  const location = useLocation()

  // Determine if we're in a project context
  const isProjectRoute = location.pathname.startsWith('/projects/')
  const activeProjectId = projectId ?? (isProjectRoute ? location.pathname.split('/')[2] : null)

  return (
    <div className="flex h-dvh flex-col sm:flex-row bg-slate-900 overflow-hidden">
      {/* ── Sidebar ── */}
      <aside
        className={`w-full flex flex-col bg-slate-950 sm:border-r border-slate-800 motion-safe:transition-all motion-safe:duration-200 shrink-0 ${
          collapsed ? 'sm:w-16' : 'sm:w-60'
        }`}
        data-testid="sidebar"
        onKeyDown={event => {
          if (event.key === 'Escape' && menuOpen) {
            setMenuOpen(false)
            menuButton.current?.focus()
          }
        }}
      >
        {/* Logo */}
        <div
          className={`flex items-center gap-3 px-3 py-1 sm:px-4 sm:py-4 border-b border-slate-800 ${
            collapsed ? 'justify-center' : ''
          }`}
        >
          <div className="w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center shrink-0">
            <span className="text-slate-900 font-black text-xs">Ω</span>
          </div>
          <div className={collapsed ? 'sm:hidden' : ''}>
            <p className="text-slate-100 font-bold text-sm leading-tight">Omega</p>
            <p className="hidden sm:block text-slate-500 text-xs">Platform</p>
          </div>
          {studioCommand && (
            <a href={studioCommand} referrerPolicy="no-referrer"
              className="ml-auto sm:hidden inline-flex min-h-11 items-center gap-2 rounded-md px-2 text-sm font-medium text-slate-100">
              <Building2 className="size-4" aria-hidden="true" />Business Studio
            </a>
          )}
          <button type="button" ref={menuButton} aria-label="Navigation menu"
            aria-controls="platform-navigation" aria-expanded={menuOpen}
            onClick={() => {
              setMenuOpen(!menuOpen)
              setCollapsed(false)
            }}
            className={`${studioCommand ? '' : 'ml-auto'} sm:hidden inline-flex size-11 items-center justify-center rounded-md text-slate-300 hover:bg-slate-800`}>
            <Menu className="size-5" aria-hidden="true" />
          </button>
        </div>
        <div id="platform-navigation" className={`${menuOpen ? 'flex' : 'hidden'} max-h-[55dvh] overflow-y-auto sm:flex sm:max-h-none sm:overflow-visible sm:min-h-0 sm:flex-1 flex-col`}
          onClick={event => {
            if (event.target instanceof Element && event.target.closest('a, [role="option"]')) setMenuOpen(false)
          }}>
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

          {/* Per-project nav — keyed by activeProjectId so it re-renders on switch */}
          {activeProjectId && (
            <nav className="flex-1 px-2 py-1 space-y-0.5 overflow-y-auto" key={activeProjectId}>
              {getProjectNav(activeProjectId).map(({ to, label, icon, end }) => (
                <NavItem key={to} to={to} label={label} icon={icon} collapsed={collapsed} end={end} />
              ))}
            </nav>
          )}

          {!activeProjectId && <div className="flex-1" />}

          {/* Collapse toggle */}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className={`hidden sm:flex items-center gap-2 px-4 py-3 text-slate-500 hover:text-slate-300 border-t border-slate-800 transition-colors text-xs ${
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
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="min-w-0 flex-1 overflow-auto" data-testid="main-content">
        <div className="max-w-7xl mx-auto px-4 py-5 sm:px-6 sm:py-8">
          {children}
        </div>
      </main>
    </div>
  )
}
