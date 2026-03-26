import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, ReferenceLine,
} from 'recharts'
import { ArrowLeft, ChevronRight } from 'lucide-react'

// ─── Mock data ────────────────────────────────────────────────────────────────

const SIGNAL_SNAPSHOT = [
  { name: 'market_data',    value:  0.82 },
  { name: 'momentum_1d',    value:  0.65 },
  { name: 'volume_trend',   value:  0.51 },
  { name: 'funding_rate',   value:  0.43 },
  { name: 'on_chain_flow',  value:  0.38 },
  { name: 'sentiment',      value:  0.29 },
  { name: 'technical_rsi',  value:  0.22 },
  { name: 'volatility',     value:  0.15 },
  { name: 'mean_reversion', value: -0.12 },
  { name: 'macro_regime',   value: -0.18 },
  { name: 'exchange_flow',  value: -0.25 },
  { name: 'whale_activity', value: -0.31 },
  { name: 'social_volume',  value: -0.38 },
  { name: 'fear_greed',     value: -0.44 },
  { name: 'order_book',     value: -0.52 },
  { name: 'dominance',      value: -0.61 },
]

const PRICE_DATA = [
  { cycle: -5, price: 87.82 },
  { cycle: -4, price: 88.14 },
  { cycle: -3, price: 88.71 },
  { cycle: -2, price: 88.95 },
  { cycle: -1, price: 89.12 },
  { cycle:  0, price: 89.43 },
  { cycle:  1, price: 89.87 },
  { cycle:  2, price: 90.42 },
  { cycle:  3, price: 90.91 },
  { cycle:  4, price: 91.23 },
  { cycle:  5, price: 91.12 },
]

const MEMORIES = [
  {
    id: 'mem_001',
    content: 'SOLUSDT showed strong upward momentum in previous 3 cycles with funding rate consistently positive',
    age: '12 cycles ago',
    weight: 0.85,
  },
  {
    id: 'mem_002',
    content: 'Whale accumulation detected: 2.3M SOL transferred to exchanges with net positive inflow signal',
    age: '8 cycles ago',
    weight: 0.72,
  },
  {
    id: 'mem_003',
    content: 'RSI divergence resolved bullishly in similar market conditions — 73% historical accuracy rate',
    age: '5 cycles ago',
    weight: 0.61,
  },
]

// ─── TradeDetail ──────────────────────────────────────────────────────────────

export function TradeDetail() {
  const { projectId = '', tradeId = '' } = useParams<{ projectId: string; tradeId: string }>()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 400)
    return () => clearTimeout(t)
  }, [])

  return (
    <div className="space-y-6" data-testid="trade-detail">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 flex-wrap">
        <Link
          to={`/projects/${projectId}/trading`}
          className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 transition-colors text-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <span className="text-slate-400 text-sm capitalize">{projectId}</span>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <Link
          to={`/projects/${projectId}/trading`}
          className="text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          Trading
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <span className="text-slate-200 text-sm font-medium">Trade #{tradeId}</span>
      </div>

      {/* Summary row */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton h-20 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          {[
            { label: 'Symbol',   value: 'SOLUSDT',   special: 'mono' },
            { label: 'Side',     value: 'LONG',      special: 'long' },
            { label: 'Size',     value: '0.15 BTC',  special: 'mono' },
            { label: 'Entry',    value: '$89.43',    special: 'mono' },
            { label: 'Exit',     value: '$91.12',    special: 'mono' },
            { label: 'PnL',      value: '+$253.50',  special: 'positive' },
            { label: 'Duration', value: '5 cycles',  special: 'mono' },
          ].map(({ label, value, special }) => (
            <div key={label} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
              <p className="text-slate-500 text-xs uppercase tracking-wider mb-2">{label}</p>
              <p className={`text-lg font-bold tabular-nums ${
                special === 'long'     ? 'text-emerald-400' :
                special === 'short'    ? 'text-rose-400' :
                special === 'positive' ? 'text-emerald-400' :
                special === 'negative' ? 'text-rose-400' :
                'text-slate-100'
              }`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Charts */}
      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="skeleton h-80 rounded-xl" />
          <div className="skeleton h-80 rounded-xl" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Signal Snapshot */}
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-1">Signal Snapshot at Entry</h3>
            <p className="text-slate-500 text-xs mb-4">Green = supported long · Red = opposed it</p>
            <ResponsiveContainer width="100%" height={340}>
              <BarChart
                data={SIGNAL_SNAPSHOT}
                layout="vertical"
                margin={{ top: 0, right: 16, bottom: 0, left: 104 }}
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
                  width={100}
                />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number) => [v.toFixed(3), 'Signal']}
                />
                <ReferenceLine x={0} stroke="#475569" strokeDasharray="4 2" />
                <Bar dataKey="value" radius={[0, 3, 3, 0]}>
                  {SIGNAL_SNAPSHOT.map((entry, index) => (
                    <Cell key={index} fill={entry.value >= 0 ? '#34d399' : '#f43f5e'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Price Action */}
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-4">Price Action</h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={PRICE_DATA} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
                <XAxis
                  dataKey="cycle"
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) => v === 0 ? 'Entry' : v > 0 ? `+${v}` : `${v}`}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number) => [`$${v.toFixed(2)}`, 'Price']}
                  labelFormatter={(v: number) => `Cycle ${v >= 0 ? '+' : ''}${v}`}
                />
                <ReferenceLine
                  x={0}
                  stroke="#34d399"
                  strokeDasharray="4 2"
                  label={{ value: 'Entry $89.43', fill: '#34d399', fontSize: 10, position: 'insideTopRight' }}
                />
                <ReferenceLine
                  x={5}
                  stroke="#f43f5e"
                  strokeDasharray="4 2"
                  label={{ value: 'Exit $91.12', fill: '#f43f5e', fontSize: 10, position: 'insideTopLeft' }}
                />
                <Line type="monotone" dataKey="price" stroke="#38bdf8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5 bg-sky-400 inline-block" /> Price
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-px border-t-2 border-dashed border-emerald-400 inline-block" /> Entry
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-px border-t-2 border-dashed border-rose-400 inline-block" /> Exit
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Meta badges */}
      {loading ? (
        <div className="skeleton h-16 rounded-xl" />
      ) : (
        <div className="flex items-center gap-3 flex-wrap">
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 px-5 py-3 flex items-center gap-3">
            <span className="text-slate-500 text-xs uppercase tracking-wider">Regime</span>
            <span className="bg-emerald-900/40 text-emerald-400 text-sm font-bold px-2.5 py-1 rounded-lg">BULL</span>
            <span className="text-slate-300 text-sm tabular-nums font-medium">78%</span>
          </div>
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 px-5 py-3 flex items-center gap-3">
            <span className="text-slate-500 text-xs uppercase tracking-wider">Gate Score</span>
            <span className="text-slate-100 text-sm font-bold tabular-nums">0.42</span>
            <span className="bg-emerald-900/40 text-emerald-400 text-xs font-semibold px-2 py-0.5 rounded">PASS</span>
          </div>
          <div className="bg-slate-800 rounded-xl border border-slate-700/50 px-5 py-3 flex items-center gap-3">
            <span className="text-slate-500 text-xs uppercase tracking-wider">Kelly Fraction</span>
            <span className="text-sky-400 text-sm font-bold tabular-nums">12%</span>
          </div>
        </div>
      )}

      {/* Memory Context */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => <div key={i} className="skeleton h-24 rounded-xl" />)}
        </div>
      ) : (
        <div>
          <h3 className="text-sm font-semibold text-slate-300 mb-3">Memory Context</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {MEMORIES.map((m) => (
              <div key={m.id} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <span className="text-slate-500 text-xs font-mono">{m.id}</span>
                  <span className="text-slate-600 text-xs shrink-0">{m.age}</span>
                </div>
                <p className="text-slate-300 text-sm leading-relaxed">{m.content}</p>
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                    <span>Relevance</span>
                    <span className="text-emerald-400 tabular-nums">{m.weight.toFixed(2)}</span>
                  </div>
                  <div className="h-1 bg-slate-700 rounded-full">
                    <div
                      className="h-full bg-emerald-500 rounded-full"
                      style={{ width: `${m.weight * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
