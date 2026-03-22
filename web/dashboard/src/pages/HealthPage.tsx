import React from 'react'
import { Activity, CheckCircle, AlertTriangle, XCircle } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useFetch } from '../hooks/useFetch'
import { api, type ComponentHealth } from '../lib/api'

const statusConfig: Record<string, { icon: React.ElementType; color: string; bg: string; border: string }> = {
  healthy:   { icon: CheckCircle,   color: 'text-emerald-400', bg: 'bg-emerald-900/20', border: 'border-emerald-700/50' },
  degraded:  { icon: AlertTriangle, color: 'text-amber-400',   bg: 'bg-amber-900/20',   border: 'border-amber-700/50' },
  unhealthy: { icon: XCircle,       color: 'text-rose-400',    bg: 'bg-rose-900/20',     border: 'border-rose-700/50' },
}

// Fake latency history per component
function makeLatencyHistory() {
  return Array.from({ length: 20 }, (_, i) => ({
    t: i,
    ms: 5 + Math.random() * 20,
  }))
}

function HealthCard({ component }: { component: ComponentHealth }) {
  const cfg = statusConfig[component.status] ?? statusConfig.healthy
  const Icon = cfg.icon
  const history = makeLatencyHistory()

  return (
    <div className={`bg-slate-800 rounded-xl border ${cfg.border} p-5 ${cfg.bg}`}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-slate-200 font-medium">{component.name}</p>
          <p className="text-slate-500 text-xs mt-0.5">
            Last checked {new Date(component.last_check).toLocaleTimeString()}
          </p>
        </div>
        <Icon className={`w-5 h-5 ${cfg.color}`} />
      </div>

      <div className="flex items-end gap-4 mb-3">
        <div>
          <p className="text-slate-500 text-xs mb-1">Latency</p>
          <p className={`text-2xl font-bold tabular-nums ${cfg.color}`}>
            {component.latency_ms}
            <span className="text-slate-500 text-xs ml-1 font-normal">ms</span>
          </p>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={60}>
        <LineChart data={history} margin={{ top: 2, right: 2, bottom: 0, left: -30 }}>
          <Line
            type="monotone"
            dataKey="ms"
            stroke={component.status === 'healthy' ? '#34d399' : component.status === 'degraded' ? '#fbbf24' : '#f87171'}
            strokeWidth={1.5}
            dot={false}
          />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
            formatter={(v: number) => [`${v.toFixed(1)}ms`, 'Latency']}
            labelStyle={{ display: 'none' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function HealthPage() {
  const { data: health, loading } = useFetch(api.getHealth)

  const counts = { healthy: 0, degraded: 0, unhealthy: 0 }
  for (const c of health ?? []) {
    counts[c.status] = (counts[c.status] ?? 0) + 1
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">System Health</h1>
        <p className="text-slate-400 text-sm mt-1">{health?.length ?? 0} components monitored</p>
      </div>

      {/* Status summary */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Healthy', count: counts.healthy, color: 'text-emerald-400', bg: 'bg-emerald-900/20 border-emerald-700/50' },
          { label: 'Degraded', count: counts.degraded, color: 'text-amber-400', bg: 'bg-amber-900/20 border-amber-700/50' },
          { label: 'Unhealthy', count: counts.unhealthy, color: 'text-rose-400', bg: 'bg-rose-900/20 border-rose-700/50' },
        ].map(({ label, count, color, bg }) => (
          <div key={label} className={`rounded-xl border p-5 ${bg}`}>
            <div className="flex items-center gap-2 mb-2">
              <Activity className={`w-4 h-4 ${color}`} />
              <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
            </div>
            <p className={`text-3xl font-bold tabular-nums ${color}`}>{count}</p>
          </div>
        ))}
      </div>

      {/* Component grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading
          ? Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-40 rounded-xl" />)
          : (health ?? []).map((c) => <HealthCard key={c.name} component={c} />)}
        {!loading && (!health || health.length === 0) && (
          <div className="col-span-3 text-center py-16 text-slate-500 text-sm">No components registered</div>
        )}
      </div>
    </div>
  )
}
