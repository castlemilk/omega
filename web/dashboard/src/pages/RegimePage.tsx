import React, { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from 'lucide-react'

// ─── Mock data ────────────────────────────────────────────────────────────────

type Regime = 'bull' | 'bear' | 'sideways'

interface RegimePoint {
  t: string
  bull: number
  bear: number
  sideways: number
  price: number
  dominant: Regime
}

function buildRegimeData(): RegimePoint[] {
  const pts: RegimePoint[] = []
  let price = 42000
  const now = Date.now()

  // Regime sequence: sideways → bull → bear → bull
  const phases: Array<{ regime: Regime; len: number }> = [
    { regime: 'sideways', len: 20 },
    { regime: 'bull',     len: 35 },
    { regime: 'bear',     len: 22 },
    { regime: 'bull',     len: 23 },
  ]

  let idx = 0
  for (const { regime, len } of phases) {
    for (let i = 0; i < len; i++) {
      // Smooth probability curves
      const progress = i / len
      const base = {
        bull:     regime === 'bull'     ? 0.6 + 0.2 * progress : regime === 'bear' ? 0.05 : 0.2,
        bear:     regime === 'bear'     ? 0.6 + 0.2 * progress : regime === 'bull' ? 0.05 : 0.15,
        sideways: regime === 'sideways' ? 0.6 + 0.15 * progress : 0.2 - 0.1 * progress,
      }

      // Add noise
      const noise = () => (Math.random() - 0.5) * 0.08
      let b = Math.max(0, base.bull + noise())
      let r = Math.max(0, base.bear + noise())
      let s = Math.max(0, base.sideways + noise())
      const sum = b + r + s
      b /= sum; r /= sum; s /= sum

      // Price
      const drift = regime === 'bull' ? 0.004 : regime === 'bear' ? -0.003 : 0
      price *= 1 + drift + (Math.random() - 0.5) * 0.01

      pts.push({
        t: new Date(now - (100 - idx) * 4 * 3600000).toISOString().slice(5, 13).replace('T', ' '),
        bull: parseFloat(b.toFixed(3)),
        bear: parseFloat(r.toFixed(3)),
        sideways: parseFloat(s.toFixed(3)),
        price: Math.round(price),
        dominant: b > r && b > s ? 'bull' : r > b && r > s ? 'bear' : 'sideways',
      })
      idx++
    }
  }

  return pts
}

const DATA = buildRegimeData()

// ─── Current regime badge ─────────────────────────────────────────────────────

function RegimeBadge({ regime, prob }: { regime: Regime; prob: number }) {
  const cfg = {
    bull:     { label: 'BULL',     color: 'text-emerald-300', bg: 'bg-emerald-500/15 border-emerald-500/40', Icon: TrendingUp  },
    bear:     { label: 'BEAR',     color: 'text-rose-300',    bg: 'bg-rose-500/15    border-rose-500/40',    Icon: TrendingDown },
    sideways: { label: 'SIDEWAYS', color: 'text-amber-300',   bg: 'bg-amber-500/15  border-amber-500/40',   Icon: Minus       },
  }[regime]

  return (
    <div className={`inline-flex items-center gap-3 px-6 py-4 rounded-2xl border ${cfg.bg}`}>
      <cfg.Icon className={`w-8 h-8 ${cfg.color}`} />
      <div>
        <p className={`text-3xl font-black tracking-wide ${cfg.color}`}>
          {cfg.label}
        </p>
        <p className={`text-lg font-bold tabular-nums ${cfg.color}`}>
          {(prob * 100).toFixed(0)}% confidence
        </p>
      </div>
    </div>
  )
}

// ─── Custom tooltip ───────────────────────────────────────────────────────────

function RegimeTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as RegimePoint
  if (!d) return null
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs space-y-1">
      <p className="text-slate-400 mb-1">{label}</p>
      <p className="text-emerald-400">Bull: {(d.bull * 100).toFixed(1)}%</p>
      <p className="text-rose-400">Bear: {(d.bear * 100).toFixed(1)}%</p>
      <p className="text-amber-400">Sideways: {(d.sideways * 100).toFixed(1)}%</p>
    </div>
  )
}

// ─── Transition events ────────────────────────────────────────────────────────

function findTransitions(data: RegimePoint[]) {
  const transitions: Array<{ idx: number; from: Regime; to: Regime; label: string }> = []
  for (let i = 1; i < data.length; i++) {
    if (data[i].dominant !== data[i - 1].dominant) {
      transitions.push({
        idx: i,
        from: data[i - 1].dominant,
        to: data[i].dominant,
        label: data[i].t,
      })
    }
  }
  return transitions
}

// ─── RegimePage ───────────────────────────────────────────────────────────────

export function RegimePage() {
  const { projectId = '' } = useParams<{ projectId: string }>()

  const latest = DATA[DATA.length - 1]
  const currentRegime = latest.dominant
  const currentProb = latest[currentRegime]
  const transitions = useMemo(() => findTransitions(DATA), [])

  const thinData = DATA.filter((_, i) => i % 2 === 0)

  return (
    <div className="space-y-6" data-testid="regime-page">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Regime Detector</h1>
          <p className="text-slate-400 text-sm mt-1">
            Market regime probabilities — project <span className="text-slate-300">{projectId}</span>
          </p>
        </div>
        <RegimeBadge regime={currentRegime} prob={currentProb} />
      </div>

      {/* Current probabilities */}
      <div className="grid grid-cols-3 gap-4">
        {(['bull', 'bear', 'sideways'] as Regime[]).map(r => {
          const prob = latest[r]
          const colors: Record<Regime, string> = {
            bull: 'text-emerald-400',
            bear: 'text-rose-400',
            sideways: 'text-amber-400',
          }
          const bars: Record<Regime, string> = {
            bull: 'bg-emerald-500',
            bear: 'bg-rose-500',
            sideways: 'bg-amber-500',
          }
          return (
            <div key={r} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-slate-400 text-sm capitalize">{r}</p>
                <span className={`text-xl font-bold tabular-nums ${colors[r]}`}>
                  {(prob * 100).toFixed(1)}%
                </span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${bars[r]}`}
                  style={{ width: `${prob * 100}%` }}
                />
              </div>
              {r === currentRegime && (
                <p className="text-xs text-slate-500">← current regime</p>
              )}
            </div>
          )
        })}
      </div>

      {/* Stacked area chart */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
        <p className="text-slate-400 text-sm font-medium mb-4">Regime Probabilities Over Time</p>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={thinData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <XAxis
              dataKey="t"
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              interval={9}
            />
            <YAxis
              tickFormatter={v => `${Math.round(v * 100)}%`}
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              domain={[0, 1]}
            />
            <Tooltip content={<RegimeTooltip />} />
            <Area type="monotone" dataKey="bull"     stackId="1" stroke="#34d399" fill="#34d399" fillOpacity={0.6} strokeWidth={0} />
            <Area type="monotone" dataKey="sideways" stackId="1" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.6} strokeWidth={0} />
            <Area type="monotone" dataKey="bear"     stackId="1" stroke="#f87171" fill="#f87171" fillOpacity={0.6} strokeWidth={0} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Price overlay */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
        <p className="text-slate-400 text-sm font-medium mb-4">Price with Regime Transitions</p>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={thinData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} interval={9} />
            <YAxis
              tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#94a3b8' }}
              itemStyle={{ color: '#e2e8f0' }}
              formatter={(v: number) => [`$${v.toLocaleString()}`, 'Price']}
            />
            {transitions.map((tr, i) => (
              <ReferenceLine
                key={i}
                x={tr.label}
                stroke={tr.to === 'bull' ? '#34d399' : tr.to === 'bear' ? '#f87171' : '#fbbf24'}
                strokeDasharray="4 2"
                strokeWidth={1.5}
              />
            ))}
            <Line type="monotone" dataKey="price" stroke="#94a3b8" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Transitions log */}
      {transitions.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Regime Transitions
          </h2>
          <div className="space-y-2">
            {[...transitions].reverse().slice(0, 5).map((tr, i) => (
              <div key={i} className="flex items-center gap-3 bg-slate-800 rounded-xl border border-slate-700/50 px-4 py-3 text-sm">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                <span className="text-slate-500 text-xs w-28 shrink-0">{tr.label}</span>
                <span className="text-slate-300 capitalize">{tr.from}</span>
                <span className="text-slate-600">→</span>
                <span className={`font-medium capitalize ${
                  tr.to === 'bull' ? 'text-emerald-400' : tr.to === 'bear' ? 'text-rose-400' : 'text-amber-400'
                }`}>{tr.to}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
