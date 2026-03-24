import React from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { MetricCard } from '../components/MetricCard'
import { StatusBadge } from '../components/StatusBadge'
import { EventTimeline } from '../components/EventTimeline'
import { useFetch } from '../hooks/useFetch'
import { useSSE } from '../hooks/useSSE'
import { api } from '../lib/api'

// Mock chart data for cycle duration + improvement rate trends
const cycleTrend = Array.from({ length: 12 }, (_, i) => ({
  t: `${i}m`,
  ms: 800 + Math.sin(i * 0.8) * 200 + Math.random() * 100,
}))

const improvementTrend = Array.from({ length: 12 }, (_, i) => ({
  t: `${i}m`,
  rate: Math.max(0, 60 + i * 2 + Math.random() * 10 - 5),
}))

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

export function OverviewPage() {
  const { data: status, loading } = useFetch(api.getStatus)
  const { events, connected } = useSSE('/api/v1/dashboard/events/stream')

  const totalAutonomy = status
    ? Object.values(status.autonomy_distribution).reduce((a, b) => a + b, 0)
    : 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">System Overview</h1>
          <p className="text-slate-400 text-sm mt-1">Real-time operational status</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
            {connected ? 'Live' : 'Disconnected'}
          </div>
          {status && <StatusBadge status={status.status} pulse={status.status === 'healthy'} />}
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Total Nodes"
          value={status?.total_nodes ?? 0}
          sub="registered"
          accent="sky"
          loading={loading}
        />
        <MetricCard
          label="Active Cycles"
          value={status?.active_cycles ?? 0}
          sub="running"
          accent="emerald"
          trend="flat"
          loading={loading}
        />
        <MetricCard
          label="Uptime"
          value={status ? formatUptime(status.uptime_seconds) : '—'}
          sub="continuous"
          accent="amber"
          loading={loading}
        />
        <MetricCard
          label="Autonomous Nodes"
          value={totalAutonomy > 0 ? `${Math.round(((status?.autonomy_distribution?.AUTONOMOUS ?? 0) / totalAutonomy) * 100)}%` : '—'}
          sub="of fleet"
          accent="emerald"
          trend="up"
          loading={loading}
        />
      </div>

      {/* Autonomy distribution */}
      {status && (
        <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Autonomy Distribution</h3>
          <div className="flex gap-3">
            {Object.entries(status.autonomy_distribution).map(([level, count]) => {
              const pct = totalAutonomy > 0 ? Math.round((count / totalAutonomy) * 100) : 0
              const colors: Record<string, string> = {
                AUTONOMOUS: 'bg-emerald-500',
                SUPERVISED: 'bg-amber-500',
                PICO: 'bg-slate-500',
              }
              return (
                <div key={level} className="flex-1">
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-slate-400">{level}</span>
                    <span className="text-slate-300 font-mono">{count}</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${colors[level] ?? 'bg-slate-500'} rounded-full transition-all duration-700`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <p className="text-slate-500 text-xs mt-1 text-right">{pct}%</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Cycle Duration Trend</h3>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={cycleTrend} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <defs>
                <linearGradient id="durGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
                itemStyle={{ color: '#38bdf8' }}
              />
              <Area type="monotone" dataKey="ms" stroke="#38bdf8" strokeWidth={2} fill="url(#durGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Improvement Rate</h3>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={improvementTrend} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <defs>
                <linearGradient id="impGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} unit="%" />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
                itemStyle={{ color: '#34d399' }}
              />
              <Area type="monotone" dataKey="rate" stroke="#34d399" strokeWidth={2} fill="url(#impGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Event timeline */}
      <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-300">Recent Events</h3>
          <span className="text-xs text-slate-500">{events.length} events</span>
        </div>
        <EventTimeline events={events} />
      </div>
    </div>
  )
}
