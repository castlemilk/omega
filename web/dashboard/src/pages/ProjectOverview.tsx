import React from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  TrendingUp, TrendingDown, DollarSign, Activity, Zap, Briefcase, ArrowRight,
} from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api } from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pct(v: number) {
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}

function usd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
}

// ─── KPI card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, positive, loading,
}: { label: string; value: string; sub?: string; positive?: boolean; loading: boolean }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
      <p className="text-slate-500 text-xs uppercase tracking-wider mb-2">{label}</p>
      {loading ? (
        <div className="skeleton h-7 w-28 mb-1" />
      ) : (
        <p className={`text-xl font-bold tabular-nums ${
          positive === undefined ? 'text-slate-100' :
          positive ? 'text-emerald-400' : 'text-rose-400'
        }`}>
          {value}
        </p>
      )}
      {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
    </div>
  )
}

// ─── Signal heatmap ───────────────────────────────────────────────────────────

function SignalHeatmap({ projectId }: { projectId: string }) {
  const { data, loading } = useFetch(() => api.victoria.getSignals())

  if (!['victoria'].includes(projectId)) return null

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-400" />
          Signal Health
        </h3>
        <Link
          to={`/projects/${projectId}/signals`}
          className="text-xs text-slate-500 hover:text-emerald-400 flex items-center gap-1 transition-colors"
        >
          View all <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
      {loading ? (
        <div className="grid grid-cols-3 gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-14 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2" data-testid="signal-heatmap">
          {(data?.signals ?? []).slice(0, 8).map((s) => {
            const icPct = Math.min(100, Math.max(0, Math.abs(s.avg_ic) * 1000))
            const bg = s.avg_ic > 0.02 ? 'bg-emerald-900/40 border-emerald-700/40' :
                       s.avg_ic > 0 ? 'bg-slate-700/40 border-slate-600/40' :
                       'bg-rose-900/30 border-rose-700/30'
            const textColor = s.avg_ic > 0.02 ? 'text-emerald-300' :
                              s.avg_ic > 0 ? 'text-slate-300' : 'text-rose-300'
            return (
              <div key={s.name} className={`rounded-lg border p-2.5 ${bg}`}>
                <p className="text-xs text-slate-400 truncate mb-1" title={s.name}>{s.name}</p>
                <p className={`text-sm font-bold tabular-nums ${textColor}`}>
                  {s.avg_ic.toFixed(3)}
                </p>
                <p className="text-slate-600 text-xs">IC</p>
              </div>
            )
          })}
        </div>
      )}
      {data && (
        <div className="mt-3 pt-3 border-t border-slate-700/40 flex items-center justify-between text-xs text-slate-500">
          <span>Composite score: <span className="text-slate-300 font-medium">{data.composite_score.toFixed(3)}</span></span>
          <span className={`font-medium ${data.composite_direction === 'LONG' ? 'text-emerald-400' : data.composite_direction === 'SHORT' ? 'text-rose-400' : 'text-slate-400'}`}>
            {data.composite_direction}
          </span>
        </div>
      )}
    </div>
  )
}

// ─── Open Positions summary ───────────────────────────────────────────────────

function PositionsSummary({ projectId }: { projectId: string }) {
  const { data, loading } = useFetch(() => api.victoria.getPositions())

  if (!['victoria'].includes(projectId)) return null
  const positions = data?.positions ?? []

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Briefcase className="w-4 h-4 text-sky-400" />
          Open Positions
        </h3>
        <Link
          to={`/projects/${projectId}/positions`}
          className="text-xs text-slate-500 hover:text-emerald-400 flex items-center gap-1 transition-colors"
        >
          View all <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="skeleton h-10 rounded-lg" />)}
        </div>
      ) : positions.length === 0 ? (
        <p className="text-slate-500 text-sm text-center py-6">No open positions</p>
      ) : (
        <div className="space-y-2" data-testid="positions-summary">
          {positions.slice(0, 5).map((p) => (
            <div key={p.sym} className="flex items-center gap-3 text-sm py-1.5 border-b border-slate-700/30 last:border-0">
              <span className={`w-2 h-2 rounded-full shrink-0 ${p.side === 'LONG' ? 'bg-emerald-400' : 'bg-rose-400'}`} />
              <span className="font-mono text-slate-200 w-24 shrink-0">{p.sym}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${p.side === 'LONG' ? 'bg-emerald-900/40 text-emerald-400' : 'bg-rose-900/40 text-rose-400'}`}>
                {p.side}
              </span>
              <span className="text-slate-400 flex-1 text-right tabular-nums">
                {p.size.toFixed(3)}
              </span>
              <span className={`tabular-nums font-medium w-20 text-right ${p.upnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {p.upnl >= 0 ? '+' : ''}{usd(p.upnl)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── ProjectOverview ──────────────────────────────────────────────────────────

export function ProjectOverview() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const isVictoria = projectId === 'victoria'

  const { data: portfolio, loading: pLoading } = useFetch(
    () => isVictoria ? api.victoria.getPortfolio() : Promise.resolve(null)
  )

  return (
    <div className="space-y-6" data-testid="project-overview">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100 capitalize">{projectId} Overview</h1>
        <p className="text-slate-400 text-sm mt-1">Project dashboard</p>
      </div>

      {/* Victoria-specific KPIs */}
      {isVictoria && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="pnl-cards">
            <KpiCard
              label="Portfolio Value"
              value={portfolio ? usd(portfolio.portfolio_value) : '—'}
              sub="AUM"
              loading={pLoading}
            />
            <KpiCard
              label="Total PnL"
              value={portfolio ? usd(portfolio.total_pnl) : '—'}
              sub={portfolio ? pct(portfolio.total_return) + ' total return' : undefined}
              positive={portfolio ? portfolio.total_pnl >= 0 : undefined}
              loading={pLoading}
            />
            <KpiCard
              label="Sharpe Ratio"
              value={portfolio ? portfolio.sharpe.toFixed(2) : '—'}
              sub="annualised"
              positive={portfolio ? portfolio.sharpe > 0 : undefined}
              loading={pLoading}
            />
            <KpiCard
              label="Win Rate"
              value={portfolio ? `${(portfolio.win_rate * 100).toFixed(1)}%` : '—'}
              sub={portfolio ? `PF ${portfolio.profit_factor.toFixed(2)}` : undefined}
              positive={portfolio ? portfolio.win_rate >= 0.5 : undefined}
              loading={pLoading}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <SignalHeatmap projectId={projectId} />
            <PositionsSummary projectId={projectId} />
          </div>
        </>
      )}

      {!isVictoria && (
        <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
          <Activity className="w-10 h-10 text-slate-600" />
          <p className="text-sm">Project overview for <span className="text-slate-300">{projectId}</span></p>
          <p className="text-xs">Connect the backend to populate project-specific metrics.</p>
        </div>
      )}
    </div>
  )
}
