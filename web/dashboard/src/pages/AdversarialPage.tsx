import React from 'react'
import { Shield, AlertTriangle, AlertCircle, Info } from 'lucide-react'
import { StatusBadge } from '../components/StatusBadge'
import { useFetch } from '../hooks/useFetch'
import { api, type AdversarialAlert } from '../lib/api'

const ringColors: Record<number, { border: string; bg: string; label: string; icon: string }> = {
  1: { border: 'border-rose-700/60', bg: 'bg-rose-900/20', label: 'text-rose-300', icon: 'text-rose-400' },
  2: { border: 'border-amber-700/60', bg: 'bg-amber-900/20', label: 'text-amber-300', icon: 'text-amber-400' },
  3: { border: 'border-sky-700/60', bg: 'bg-sky-900/20', label: 'text-sky-300', icon: 'text-sky-400' },
}

const severityIcon: Record<string, React.ElementType> = {
  critical: AlertCircle,
  high: AlertTriangle,
  medium: AlertTriangle,
  low: Info,
}

function AlertRow({ alert }: { alert: AdversarialAlert }) {
  const ring = ringColors[alert.ring] ?? ringColors[3]
  const Icon = severityIcon[alert.severity] ?? Info
  const ts = new Date(alert.timestamp)

  return (
    <div className={`flex items-start gap-4 p-4 rounded-xl border ${ring.border} ${ring.bg}`}>
      <div className={`mt-0.5 ${ring.icon}`}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <StatusBadge status={alert.severity} size="sm" />
          <span className={`text-xs font-semibold ${ring.label}`}>Ring {alert.ring}</span>
          <span className="text-slate-500 text-xs font-mono">{alert.node_id}</span>
        </div>
        <p className="text-slate-200 text-sm">{alert.message}</p>
      </div>
      <span className="text-slate-500 text-xs shrink-0 tabular-nums">{ts.toLocaleTimeString()}</span>
    </div>
  )
}

export function AdversarialPage() {
  const { data: alerts, loading } = useFetch(api.getAdversarialAlerts)

  const byRing: Record<number, AdversarialAlert[]> = { 1: [], 2: [], 3: [] }
  for (const a of alerts ?? []) {
    byRing[a.ring]?.push(a)
  }

  // Node vulnerability heatmap (aggregate by node)
  const nodeCounts: Record<string, number> = {}
  for (const a of alerts ?? []) {
    nodeCounts[a.node_id] = (nodeCounts[a.node_id] ?? 0) + 1
  }
  const heatmapEntries = Object.entries(nodeCounts).sort(([, a], [, b]) => b - a)
  const maxCount = heatmapEntries[0]?.[1] ?? 1

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Adversarial Monitoring</h1>
        <p className="text-slate-400 text-sm mt-1">{alerts?.length ?? 0} active alerts</p>
      </div>

      {/* Ring summary */}
      <div className="grid grid-cols-3 gap-4">
        {([1, 2, 3] as const).map((ring) => {
          const r = ringColors[ring]
          const count = byRing[ring].length
          return (
            <div key={ring} className={`rounded-xl border p-5 ${r.border} ${r.bg}`}>
              <div className="flex items-center gap-2 mb-2">
                <Shield className={`w-4 h-4 ${r.icon}`} />
                <p className={`text-xs font-semibold uppercase tracking-wider ${r.label}`}>Ring {ring}</p>
              </div>
              <p className={`text-3xl font-bold tabular-nums ${r.label}`}>{count}</p>
              <p className="text-slate-500 text-xs mt-1">alerts</p>
            </div>
          )
        })}
      </div>

      {/* Heatmap */}
      {heatmapEntries.length > 0 && (
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Node Vulnerability Heatmap</h3>
          <div className="space-y-2.5">
            {heatmapEntries.map(([nodeId, count]) => {
              const pct = (count / maxCount) * 100
              const color = pct > 66 ? 'bg-rose-500' : pct > 33 ? 'bg-amber-500' : 'bg-sky-500'
              return (
                <div key={nodeId} className="flex items-center gap-3">
                  <span className="text-slate-400 text-xs font-mono w-36 truncate">{nodeId}</span>
                  <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-slate-400 text-xs tabular-nums w-8 text-right">{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Alert feed */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
        <h3 className="text-sm font-semibold text-slate-300 mb-4">Alert Feed</h3>
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton h-16 rounded-xl" />)}
          </div>
        ) : (alerts ?? []).length === 0 ? (
          <div className="text-center py-12 text-slate-500 text-sm flex flex-col items-center gap-2">
            <Shield className="w-8 h-8 text-emerald-400/40" />
            No active alerts
          </div>
        ) : (
          <div className="space-y-3">
            {(alerts ?? [])
              .sort((a, b) => {
                const sev = { critical: 4, high: 3, medium: 2, low: 1 }
                return (sev[b.severity] ?? 0) - (sev[a.severity] ?? 0)
              })
              .map((alert) => <AlertRow key={alert.id} alert={alert} />)}
          </div>
        )}
      </div>
    </div>
  )
}
