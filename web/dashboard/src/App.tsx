import React, { useState } from 'react'
import { LayoutDashboard, Server, RefreshCw, Shield, TrendingUp, Activity, ChevronLeft, ChevronRight } from 'lucide-react'
import { OverviewPage } from './pages/OverviewPage'
import { NodesPage } from './pages/NodesPage'
import { CyclesPage } from './pages/CyclesPage'
import { AdversarialPage } from './pages/AdversarialPage'
import { ImprovementPage } from './pages/ImprovementPage'
import { HealthPage } from './pages/HealthPage'

type Page = 'overview' | 'nodes' | 'cycles' | 'adversarial' | 'improvement' | 'health'

const nav: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: 'overview',    label: 'Overview',    icon: LayoutDashboard },
  { id: 'nodes',       label: 'Nodes',       icon: Server },
  { id: 'cycles',      label: 'Cycles',      icon: RefreshCw },
  { id: 'adversarial', label: 'Adversarial', icon: Shield },
  { id: 'improvement', label: 'Improvement', icon: TrendingUp },
  { id: 'health',      label: 'Health',      icon: Activity },
]

const pages: Record<Page, React.ComponentType> = {
  overview:    OverviewPage,
  nodes:       NodesPage,
  cycles:      CyclesPage,
  adversarial: AdversarialPage,
  improvement: ImprovementPage,
  health:      HealthPage,
}

export default function App() {
  const [page, setPage] = useState<Page>('overview')
  const [collapsed, setCollapsed] = useState(false)
  const Page = pages[page]

  return (
    <div className="flex h-screen bg-slate-900 overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`flex flex-col bg-slate-950 border-r border-slate-800 transition-all duration-200 shrink-0 ${
          collapsed ? 'w-16' : 'w-56'
        }`}
      >
        {/* Logo */}
        <div className={`flex items-center gap-3 px-4 py-5 border-b border-slate-800 ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center shrink-0">
            <span className="text-slate-900 font-black text-xs">Ω</span>
          </div>
          {!collapsed && (
            <div>
              <p className="text-slate-100 font-bold text-sm leading-tight">Omega</p>
              <p className="text-slate-500 text-xs">Dashboard</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {nav.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setPage(id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                page === id
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              } ${collapsed ? 'justify-center' : ''}`}
              title={collapsed ? label : undefined}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && label}
            </button>
          ))}
        </nav>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className={`flex items-center gap-2 px-4 py-3 text-slate-500 hover:text-slate-300 border-t border-slate-800 transition-colors text-xs ${
            collapsed ? 'justify-center' : ''
          }`}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <><ChevronLeft className="w-4 h-4" /><span>Collapse</span></>}
        </button>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-6 py-8">
          <Page />
        </div>
      </main>
    </div>
  )
}
