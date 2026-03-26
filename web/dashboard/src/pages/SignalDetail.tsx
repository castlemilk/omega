import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell,
} from 'recharts'
import { ArrowLeft, ChevronRight } from 'lucide-react'

// ─── Mock data (deterministic via seeded-like generation) ─────────────────────

function makeSignalHistory(): { cycle: number; value: number }[] {
  let val = 0.2
  return Array.from({ length: 200 }, (_, i) => {
    val += Math.sin(i * 0.31) * 0.08 + Math.cos(i * 0.17) * 0.05
    val = Math.max(-0.95, Math.min(0.95, val))
    return { cycle: i + 1, value: parseFloat(val.toFixed(4)) }
  })
}

function makeIcTrend(): { cycle: number; ic: number }[] {
  return Array.from({ length: 50 }, (_, i) => ({
    cycle: i + 1,
    ic: parseFloat((0.50 + Math.sin(i * 0.22) * 0.10 + Math.cos(i * 0.41) * 0.04).toFixed(4)),
  }))
}

const SIGNAL_HISTORY = makeSignalHistory()
const IC_TREND = makeIcTrend()

const WIN_ATTRIBUTION = [
  { label: 'Signal > +0.5',    winRate: 0.68, trades: 34 },
  { label: '+0.1 to +0.5',     winRate: 0.56, trades: 58 },
  { label: '-0.1 to +0.1',     winRate: 0.49, trades: 41 },
  { label: '-0.5 to -0.1',     winRate: 0.44, trades: 63 },
  { label: 'Signal < -0.5',    winRate: 0.41, trades: 22 },
]

const CORRELATIONS = [
  { name: 'momentum_1d',    corr:  0.72 },
  { name: 'volume_trend',   corr:  0.54 },
  { name: 'technical_rsi',  corr:  0.38 },
  { name: 'sentiment',      corr:  0.21 },
  { name: 'funding_rate',   corr: -0.15 },
  { name: 'mean_reversion', corr: -0.43 },
  { name: 'on_chain_flow',  corr: -0.58 },
]

// ─── SignalDetail ─────────────────────────────────────────────────────────────

export function SignalDetail() {
  const { projectId = '', signalName = '' } = useParams<{ projectId: string; signalName: string }>()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 400)
    return () => clearTimeout(t)
  }, [])

  const displayName = decodeURIComponent(signalName)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())

  return (
    <div className="space-y-6" data-testid="signal-detail">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 flex-wrap">
        <Link
          to={`/projects/${projectId}/signals`}
          className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 transition-colors text-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <span className="text-slate-400 text-sm capitalize">{projectId}</span>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <Link
          to={`/projects/${projectId}/signals`}
          className="text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          Signals
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <span className="text-slate-200 text-sm font-medium font-mono">{signalName}</span>
      </div>

      {/* Header */}
      {loading ? (
        <div>
          <div className="skeleton h-9 w-72 rounded-xl mb-4" />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-20 rounded-xl" />
            ))}
          </div>
        </div>
      ) : (
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{displayName} Signal</h1>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
            {[
              { label: 'Avg IC',      value: '0.558', positive: true  },
              { label: 'Weight',      value: '18.2%', positive: undefined },
              { label: 'Current',     value: '+0.42', positive: true  },
              { label: 'Brier Score', value: '0.221', positive: undefined },
            ].map(({ label, value, positive }) => (
              <div key={label} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
                <p className="text-slate-500 text-xs uppercase tracking-wider mb-2">{label}</p>
                <p className={`text-xl font-bold tabular-nums ${
                  positive === true  ? 'text-emerald-400' :
                  positive === false ? 'text-rose-400' :
                  'text-slate-100'
                }`}>{value}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Signal history — full width */}
      {loading ? (
        <div className="skeleton h-56 rounded-xl" />
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Signal Value — 200 Cycles</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={SIGNAL_HISTORY} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
              <XAxis
                dataKey="cycle"
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                interval={39}
              />
              <YAxis
                domain={[-1, 1]}
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                formatter={(v: number) => [v.toFixed(4), 'Value']}
                labelFormatter={(v: number) => `Cycle ${v}`}
              />
              <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 2" />
              <Line type="monotone" dataKey="value" stroke="#34d399" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* IC Trend + Win Attribution */}
      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="skeleton h-60 rounded-xl" />
          <div className="skeleton h-60 rounded-xl" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* IC Trend */}
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-4">IC Trend (Rolling)</h3>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={IC_TREND} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
                <XAxis
                  dataKey="cycle"
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  interval={9}
                />
                <YAxis
                  domain={[0.25, 0.75]}
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number) => [v.toFixed(4), 'IC']}
                />
                <ReferenceLine
                  y={0.5}
                  stroke="#475569"
                  strokeDasharray="4 2"
                  label={{ value: '0.5 avg', fill: '#64748b', fontSize: 10 }}
                />
                <Line type="monotone" dataKey="ic" stroke="#38bdf8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Win Attribution table */}
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-4">Win Attribution</h3>
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left text-xs text-slate-500 uppercase tracking-wider pb-2.5">
                    Condition
                  </th>
                  <th className="text-right text-xs text-slate-500 uppercase tracking-wider pb-2.5">
                    Win Rate
                  </th>
                  <th className="text-right text-xs text-slate-500 uppercase tracking-wider pb-2.5">
                    Trades
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {WIN_ATTRIBUTION.map((row) => (
                  <tr key={row.label}>
                    <td className="py-2.5 text-sm text-slate-300 font-mono">{row.label}</td>
                    <td className="py-2.5 text-right">
                      <span className={`text-sm font-bold tabular-nums ${
                        row.winRate >= 0.55 ? 'text-emerald-400' :
                        row.winRate >= 0.50 ? 'text-slate-300' :
                        'text-rose-400'
                      }`}>
                        {(row.winRate * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-sm text-slate-500 tabular-nums">
                      {row.trades}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Correlations */}
      {loading ? (
        <div className="skeleton h-48 rounded-xl" />
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Signal Correlations</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart
              data={CORRELATIONS}
              layout="vertical"
              margin={{ top: 0, right: 16, bottom: 0, left: 120 }}
            >
              <XAxis
                type="number"
                domain={[-1, 1]}
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={116}
              />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                formatter={(v: number) => [v.toFixed(3), 'Correlation']}
              />
              <ReferenceLine x={0} stroke="#475569" strokeDasharray="4 2" />
              <Bar dataKey="corr" radius={[0, 3, 3, 0]}>
                {CORRELATIONS.map((entry, index) => (
                  <Cell key={index} fill={entry.corr >= 0 ? '#34d399' : '#f43f5e'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
