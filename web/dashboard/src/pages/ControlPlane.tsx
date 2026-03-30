import React from 'react'
import {
  Activity, AlertTriangle, CheckCircle, Clock, Radio,
  TrendingUp, XCircle, Cpu, ArrowUpRight, ArrowDownRight,
} from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api, type ControlPlaneNode, type ControlPlaneDiagnostics, type ControlPlaneBlocker } from '../lib/api'

// ─── Style helpers ────────────────────────────────────────────────────────────

const HEALTH_COLOR: Record<string, string> = {
  healthy:  'text-emerald-400',
  degraded: 'text-amber-400',
  stale:    'text-orange-400',
  dead:     'text-rose-400',
  unknown:  'text-slate-500',
}

const HEALTH_BG: Record<string, string> = {
  healthy:  'bg-emerald-900/20 border-emerald-700/50',
  degraded: 'bg-amber-900/20 border-amber-700/50',
  stale:    'bg-orange-900/20 border-orange-700/50',
  dead:     'bg-rose-900/20 border-rose-700/50',
  unknown:  'bg-slate-800 border-slate-700',
}

const HEALTH_DOT: Record<string, string> = {
  healthy:  'bg-emerald-400 animate-pulse',
  degraded: 'bg-amber-400 animate-pulse',
  stale:    'bg-orange-400',
  dead:     'bg-rose-600',
  unknown:  'bg-slate-500',
}

function HealthIcon({ health }: { health: string }) {
  if (health === 'healthy')  return <CheckCircle   className="w-4 h-4 text-emerald-400 shrink-0" />
  if (health === 'dead')     return <XCircle       className="w-4 h-4 text-rose-400 shrink-0" />
  if (health === 'stale')    return <Clock         className="w-4 h-4 text-orange-400 shrink-0" />
  if (health === 'degraded') return <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
  return <Activity className="w-4 h-4 text-slate-500 shrink-0" />
}

function formatRelTime(iso: string): string {
  if (!iso) return '—'
  try {
    const diffS = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
    if (diffS < 60) return `${diffS}s ago`
    if (diffS < 3600) return `${Math.floor(diffS / 60)}m ago`
    return new Date(iso).toLocaleTimeString()
  } catch { return '—' }
}

// ─── BlockersBanner ───────────────────────────────────────────────────────────

function BlockersBanner({ blockers }: { blockers: ControlPlaneBlocker[] }) {
  const all = blockers.flatMap(b => b.blockers.map(msg => ({ node: b.node_id, msg })))
  if (all.length === 0) return null
  return (
    <div className="bg-rose-900/30 border border-rose-700/60 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
        <span className="text-sm font-semibold text-rose-300 uppercase tracking-wide">
          {all.length} Active Blocker{all.length !== 1 ? 's' : ''}
        </span>
      </div>
      <ul className="space-y-1">
        {all.map((b, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-rose-300">
            <span className="font-mono text-rose-500 shrink-0">[{b.node}]</span>
            <span>{b.msg}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ─── NodeCard ─────────────────────────────────────────────────────────────────

function NodeCard({ node }: { node: ControlPlaneNode }) {
  const health = node.health in HEALTH_BG ? node.health : 'unknown'
  return (
    <div className={`rounded-xl border p-4 space-y-3 ${HEALTH_BG[health]}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Cpu className="w-4 h-4 text-slate-400 shrink-0" />
          <span className="font-medium text-sm text-slate-200 truncate">{node.node_id}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`w-2 h-2 rounded-full ${HEALTH_DOT[health]}`} />
          <span className={`text-xs font-medium uppercase ${HEALTH_COLOR[health]}`}>
            {node.health}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-slate-500">Type</p>
          <p className="text-slate-300 font-mono">{node.node_type || '—'}</p>
        </div>
        <div>
          <p className="text-slate-500">Last heartbeat</p>
          <p className={`font-mono ${node.stale ? 'text-orange-400' : 'text-slate-300'}`}>
            {formatRelTime(node.last_seen)}
            {node.stale && <span className="ml-1 text-orange-500">(stale)</span>}
          </p>
        </div>
      </div>

      {Object.keys(node.metrics ?? {}).length > 0 && (
        <div className="grid grid-cols-2 gap-1.5 text-xs border-t border-white/5 pt-2">
          {Object.entries(node.metrics).map(([k, v]) => (
            <div key={k}>
              <p className="text-slate-600 truncate">{k}</p>
              <p className="text-slate-400 font-mono truncate">{v}</p>
            </div>
          ))}
        </div>
      )}

      {node.blockers.length > 0 && (
        <div className="border-t border-rose-800/50 pt-2 space-y-1">
          {node.blockers.map((b, i) => (
            <p key={i} className="text-xs text-rose-400 font-mono">⚠ {b}</p>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── DiagnosticsPanel ─────────────────────────────────────────────────────────

function DiagnosticsPanel({ diag, loading }: { diag: ControlPlaneDiagnostics | null; loading: boolean }) {
  if (loading) {
    return <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 animate-pulse h-48" />
  }
  if (!diag || diag.available === false) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 text-center">
        <Radio className="w-6 h-6 text-slate-600 mx-auto mb-2" />
        <p className="text-sm text-slate-500">No training diagnostics received yet</p>
      </div>
    )
  }

  const signalPct = diag.total_signals > 0
    ? Math.round((diag.active_signals / diag.total_signals) * 100)
    : 0
  const totalPos = diag.longs + diag.shorts
  const longPct  = totalPos > 0 ? Math.round((diag.longs / totalPos) * 100) : 50

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-semibold text-slate-200">Training Diagnostics</h3>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {diag.sit_out && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900/40 text-amber-300 border border-amber-700/50">
              SIT-OUT
            </span>
          )}
          <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-900/20 text-emerald-400 font-mono border border-emerald-700/50">
            Cycle #{diag.cycle}
          </span>
          <span className="text-xs text-slate-500 font-mono">{formatRelTime(diag.timestamp)}</span>
        </div>
      </div>

      {diag.sit_out && diag.sit_out_reason && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-3 py-2 text-xs text-amber-300">
          {diag.sit_out_reason}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Regime',   value: <span className="text-slate-100 uppercase">{diag.regime || '—'}</span> },
          { label: 'Signals',  value: <span className="text-slate-100">{diag.active_signals}<span className="text-slate-500 text-xs">/{diag.total_signals}</span> <span className="text-emerald-400 text-xs">({signalPct}%)</span></span> },
          { label: 'PnL',      value: <span className={diag.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{diag.pnl >= 0 ? '+' : ''}{diag.pnl.toFixed(4)}</span> },
          { label: 'Data age', value: <span className={diag.data_freshness_seconds > 300 ? 'text-amber-400' : 'text-slate-300'}>{diag.data_freshness_seconds.toFixed(0)}s</span> },
        ].map(({ label, value }) => (
          <div key={label} className="bg-slate-900/60 rounded-lg p-3">
            <p className="text-xs text-slate-500 mb-1">{label}</p>
            <p className="text-sm font-bold tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs">
        <div className="bg-slate-900/60 rounded-lg p-3 flex items-center justify-between">
          <span className="text-slate-500">Open trades</span>
          <span className="font-mono font-semibold text-slate-200">{diag.open_trades}</span>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-3 flex items-center justify-between">
          <span className="text-slate-500">Closed trades</span>
          <span className="font-mono font-semibold text-slate-200">{diag.closed_trades}</span>
        </div>
        <div className="bg-slate-900/60 rounded-lg p-3">
          <p className="text-slate-500 mb-1.5">Long / Short</p>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-0.5 text-emerald-400 font-mono font-semibold">
              <ArrowUpRight className="w-3 h-3" />{diag.longs}
            </span>
            <span className="text-slate-600">/</span>
            <span className="flex items-center gap-0.5 text-rose-400 font-mono font-semibold">
              <ArrowDownRight className="w-3 h-3" />{diag.shorts}
            </span>
            {totalPos > 0 && (
              <span className="text-slate-600 text-xs ml-auto">{longPct}% L</span>
            )}
          </div>
        </div>
      </div>

      {Object.keys(diag.ticker_convictions ?? {}).length > 0 && (
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">Ticker Convictions</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(diag.ticker_convictions)
              .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
              .slice(0, 10)
              .map(([ticker, conviction]) => (
                <span
                  key={ticker}
                  className={`text-xs px-2 py-1 rounded font-mono border ${
                    conviction > 0
                      ? 'bg-emerald-900/30 border-emerald-700/50 text-emerald-300'
                      : 'bg-rose-900/30 border-rose-700/50 text-rose-300'
                  }`}
                >
                  {ticker} <span className="opacity-60">{conviction > 0 ? '+' : ''}{conviction.toFixed(3)}</span>
                </span>
              ))}
          </div>
        </div>
      )}

      {diag.blockers.length > 0 && (
        <div className="border-t border-slate-700 pt-3 space-y-1">
          <p className="text-xs text-slate-500 uppercase tracking-widest mb-1.5">Blockers</p>
          {diag.blockers.map((b, i) => (
            <p key={i} className="text-xs text-rose-400 font-mono">⚠ {b}</p>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function ControlPlane() {
  const { data: nodes,   loading: nodesLoading,   error: nodesError   } = useFetch(api.controlPlane.getNodes)
  const { data: diag,    loading: diagLoading                          } = useFetch(api.controlPlane.getDiagnostics)
  const { data: blockers                                               } = useFetch(api.controlPlane.getBlockers)

  const nodeList    = nodes    ?? []
  const blockerList = blockers ?? []

  const healthyCount = nodeList.filter(n => n.health === 'healthy').length
  const deadCount    = nodeList.filter(n => n.health === 'dead').length
  const staleCount   = nodeList.filter(n => n.stale).length
  const totalBlockers = blockerList.reduce((s, b) => s + b.blockers.length, 0)

  const overallHealth =
    deadCount    > 0 ? 'dead'    :
    staleCount   > 0 ? 'stale'   :
    nodeList.some(n => n.health === 'degraded') ? 'degraded' :
    nodeList.length > 0 ? 'healthy' : 'unknown'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <Radio className="w-6 h-6 text-emerald-400" />
            Control Plane
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Node heartbeats, training diagnostics, and system blockers
          </p>
        </div>
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold uppercase ${HEALTH_BG[overallHealth] ?? 'bg-slate-800 border-slate-700'} ${HEALTH_COLOR[overallHealth]}`}>
          <HealthIcon health={overallHealth} />
          {overallHealth}
        </div>
      </div>

      {/* API error strip */}
      {nodesError && (
        <div className="bg-rose-900/20 border border-rose-700/50 rounded-xl px-4 py-3 text-xs text-rose-400 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          Control plane unreachable — {nodesError}
        </div>
      )}

      {/* Blockers banner */}
      {!nodesLoading && <BlockersBanner blockers={blockerList} />}

      {/* Summary stats */}
      {!nodesLoading && nodeList.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Total nodes',     value: nodeList.length,                              color: 'text-slate-100'   },
            { label: 'Healthy',         value: healthyCount,                                 color: 'text-emerald-400' },
            { label: 'Dead / stale',    value: deadCount + staleCount,                       color: (deadCount + staleCount) > 0 ? 'text-rose-400' : 'text-slate-400' },
            { label: 'Active blockers', value: totalBlockers,                                color: totalBlockers > 0 ? 'text-rose-400' : 'text-slate-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
              <p className={`text-3xl font-bold tabular-nums ${color}`}>{value}</p>
              <p className="text-xs text-slate-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Training diagnostics */}
      <section>
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
          Training Diagnostics
        </p>
        <DiagnosticsPanel diag={diag} loading={diagLoading} />
      </section>

      {/* Nodes */}
      <section>
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
          Nodes{nodeList.length > 0 ? ` — ${nodeList.length}` : ''}
        </p>
        {nodesLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="skeleton h-36 rounded-xl bg-slate-800 animate-pulse" />
            ))}
          </div>
        ) : nodeList.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {nodeList.map(n => <NodeCard key={n.node_id} node={n} />)}
          </div>
        ) : (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-10 text-center">
            <Cpu className="w-7 h-7 text-slate-600 mx-auto mb-2" />
            <p className="text-sm text-slate-500">No nodes reporting heartbeats yet</p>
            <p className="text-xs text-slate-600 mt-1">
              Nodes push heartbeats via POST /api/v1/heartbeat
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
