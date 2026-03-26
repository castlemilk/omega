import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { Zap, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api, type Signal } from '../lib/api'

// ─── Signal row ───────────────────────────────────────────────────────────────

function SignalRow({ signal, projectId }: { signal: Signal; projectId: string }) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  const { data: history } = useFetch(
    () => expanded ? api.victoria.getSignals() : Promise.resolve(null),
    60000
  )

  const icColor = signal.avg_ic > 0.02 ? 'text-emerald-400' :
                  signal.avg_ic > 0 ? 'text-slate-300' : 'text-rose-400'

  const TrendIcon = signal.trend === 'up' ? TrendingUp :
                    signal.trend === 'down' ? TrendingDown : Minus
  const trendColor = signal.trend === 'up' ? 'text-emerald-400' :
                     signal.trend === 'down' ? 'text-rose-400' : 'text-slate-400'

  // Simulate sparkline from conviction value (real data comes from GetSignalHistory RPC)
  const sparkData = Array.from({ length: 12 }, (_, i) => ({
    v: signal.conviction * (0.8 + Math.sin(i * 0.5 + signal.avg_ic * 10) * 0.2),
  }))

  return (
    <div
      className="bg-slate-800 rounded-xl border border-slate-700/50 hover:border-slate-600 transition-colors cursor-pointer"
      onClick={() => navigate(`/projects/${projectId}/signals/${encodeURIComponent(signal.name)}`)}
      data-testid={`signal-row-${signal.name}`}
    >
      <div className="flex items-center gap-4 p-4">
        {/* Name */}
        <div className="w-36 shrink-0">
          <p className="text-slate-200 text-sm font-medium truncate">{signal.name}</p>
          <p className="text-slate-500 text-xs mt-0.5">half-life: {signal.half_life}d</p>
        </div>

        {/* IC */}
        <div className="w-20 shrink-0">
          <p className="text-slate-500 text-xs mb-0.5">Avg IC</p>
          <p className={`text-sm font-bold tabular-nums ${icColor}`}>{signal.avg_ic.toFixed(4)}</p>
        </div>

        {/* Weight */}
        <div className="w-16 shrink-0">
          <p className="text-slate-500 text-xs mb-0.5">Weight</p>
          <p className="text-slate-300 text-sm tabular-nums">{(signal.weight * 100).toFixed(1)}%</p>
        </div>

        {/* Brier */}
        <div className="w-16 shrink-0">
          <p className="text-slate-500 text-xs mb-0.5">Brier</p>
          <p className="text-slate-300 text-sm tabular-nums">{signal.brier_score.toFixed(3)}</p>
        </div>

        {/* Conviction */}
        <div className="w-16 shrink-0">
          <p className="text-slate-500 text-xs mb-0.5">Conviction</p>
          <p className="text-slate-300 text-sm tabular-nums">{signal.conviction.toFixed(3)}</p>
        </div>

        {/* Trend */}
        <div className="w-10 shrink-0 flex items-center">
          <TrendIcon className={`w-4 h-4 ${trendColor}`} />
        </div>

        {/* Sparkline */}
        <div className="flex-1 min-w-0">
          <ResponsiveContainer width="100%" height={40}>
            <LineChart data={sparkData}>
              <Line type="monotone" dataKey="v" stroke={signal.color || '#34d399'} strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Current value */}
        <div className="w-20 shrink-0 text-right">
          <p className="text-slate-500 text-xs mb-0.5">Current</p>
          <p className={`text-sm font-bold tabular-nums ${signal.current_value > 0 ? 'text-emerald-400' : signal.current_value < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
            {signal.current_value > 0 ? '+' : ''}{signal.current_value.toFixed(3)}
          </p>
        </div>
      </div>

      {/* Weight bar */}
      <div className="px-4 pb-3">
        <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${signal.weight * 100}%`, backgroundColor: signal.color || '#34d399' }}
          />
        </div>
      </div>
    </div>
  )
}

// ─── SignalsPage ──────────────────────────────────────────────────────────────

export function SignalsPage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const { data, loading } = useFetch(() => api.victoria.getSignals())

  const signals = data?.signals ?? []
  const sorted = [...signals].sort((a, b) => Math.abs(b.avg_ic) - Math.abs(a.avg_ic))

  return (
    <div className="space-y-6" data-testid="signals-page">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Signals</h1>
          <p className="text-slate-400 text-sm mt-1">{signals.length} active signals</p>
        </div>
        {data && (
          <div className="text-right">
            <p className="text-slate-500 text-xs mb-1">Composite Score</p>
            <p className="text-2xl font-bold text-slate-100 tabular-nums">
              {data.composite_score.toFixed(3)}
            </p>
            <p className={`text-sm font-medium ${
              data.composite_direction === 'LONG' ? 'text-emerald-400' :
              data.composite_direction === 'SHORT' ? 'text-rose-400' : 'text-slate-400'
            }`}>
              {data.composite_direction}
              {data.oos_sharpe > 0 && (
                <span className="text-slate-500 text-xs ml-2">OOS Sharpe {data.oos_sharpe.toFixed(2)}</span>
              )}
            </p>
          </div>
        )}
      </div>

      {/* Column headers */}
      <div className="hidden md:flex items-center gap-4 px-4 text-xs text-slate-500 uppercase tracking-wider">
        <span className="w-36 shrink-0">Signal</span>
        <span className="w-20 shrink-0">Avg IC</span>
        <span className="w-16 shrink-0">Weight</span>
        <span className="w-16 shrink-0">Brier</span>
        <span className="w-16 shrink-0">Conviction</span>
        <span className="w-10 shrink-0">Trend</span>
        <span className="flex-1">History</span>
        <span className="w-20 shrink-0 text-right">Current</span>
      </div>

      {/* Signal rows */}
      <div className="space-y-2">
        {loading
          ? Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton h-16 rounded-xl" />
            ))
          : sorted.length === 0
          ? (
            <div className="text-center py-16 text-slate-500 text-sm flex flex-col items-center gap-2">
              <Zap className="w-8 h-8 text-slate-600" />
              No signals data — check backend connection
            </div>
          )
          : sorted.map((s) => <SignalRow key={s.name} signal={s} projectId={projectId} />)}
      </div>
    </div>
  )
}
