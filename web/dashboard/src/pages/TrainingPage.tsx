import React, { useState, useCallback } from 'react'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ReferenceLine,
} from 'recharts'
import {
  Brain, TrendingUp, TrendingDown, Activity, Clock,
  Target, Database, Zap, Camera, CheckCircle, Play,
  RefreshCw, ChevronDown, ChevronUp,
} from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api, TrainingProgress, TrainingMetrics, TrainingSnapshot } from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function usd(v: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', maximumFractionDigits: 0,
  }).format(v)
}

function pct(v: number, decimals = 1) {
  return `${(v * 100).toFixed(decimals)}%`
}

function elapsed(startedAt: string): string {
  if (!startedAt) return '—'
  const ms = Date.now() - new Date(startedAt).getTime()
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  if (h > 24) return `${Math.floor(h / 24)}d ${h % 24}h`
  return `${h}h ${m}m`
}

function eta(startedAt: string, current: number, total: number): string {
  if (!startedAt || current <= 0 || total <= 0) return '—'
  const elapsedMs = Date.now() - new Date(startedAt).getTime()
  const msPerCycle = elapsedMs / current
  const remainingMs = msPerCycle * (total - current)
  const h = Math.floor(remainingMs / 3_600_000)
  const m = Math.floor((remainingMs % 3_600_000) / 60_000)
  if (h > 24) return `~${Math.floor(h / 24)}d ${h % 24}h`
  return `~${h}h ${m}m`
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    running:   'bg-emerald-500/20 text-emerald-300 border-emerald-700/40',
    idle:      'bg-slate-500/20 text-slate-400 border-slate-600/40',
    completed: 'bg-sky-500/20 text-sky-300 border-sky-700/40',
    failed:    'bg-rose-500/20 text-rose-300 border-rose-700/40',
  }
  const style = styles[status] ?? styles.idle
  const isRunning = status === 'running'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${style}`}>
      {isRunning && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
        </span>
      )}
      {status.toUpperCase()}
    </span>
  )
}

// ─── MetricCard ───────────────────────────────────────────────────────────────

function MetricCard({
  label, value, sub, icon: Icon, accent = 'emerald',
}: {
  label: string
  value: React.ReactNode
  sub?: string
  icon: React.ElementType
  accent?: 'emerald' | 'sky' | 'amber' | 'rose' | 'violet'
}) {
  const colors: Record<string, string> = {
    emerald: 'text-emerald-400 bg-emerald-500/10',
    sky:     'text-sky-400 bg-sky-500/10',
    amber:   'text-amber-400 bg-amber-500/10',
    rose:    'text-rose-400 bg-rose-500/10',
    violet:  'text-violet-400 bg-violet-500/10',
  }
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-slate-400 text-sm">{label}</p>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${colors[accent]}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <p className="text-slate-100 text-2xl font-bold tabular-nums">{value}</p>
      {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
    </div>
  )
}

// ─── Progress bar ─────────────────────────────────────────────────────────────

function ProgressBar({ current, total }: { current: number; total: number }) {
  const pctVal = total > 0 ? Math.min((current / total) * 100, 100) : 0
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-slate-400 text-sm">Progress</p>
        <p className="text-slate-100 font-bold tabular-nums text-lg">
          {current.toLocaleString()} / {total.toLocaleString()}
        </p>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-2.5 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-600 to-emerald-400 transition-all duration-500"
          style={{ width: `${pctVal}%` }}
        />
      </div>
      <p className="text-slate-500 text-xs mt-2">{pctVal.toFixed(1)}% complete</p>
    </div>
  )
}

// ─── PnL Chart ────────────────────────────────────────────────────────────────

function PnLChart({ data }: { data: Array<{ cycle: number; pnl: number }> }) {
  const color = data.length > 0 && data[data.length - 1].pnl >= 0 ? '#34d399' : '#f87171'
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Cumulative PnL</h3>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v: number) => [`$${v.toFixed(2)}`, 'PnL']}
          />
          <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 2" />
          <Area type="monotone" dataKey="pnl" stroke={color} strokeWidth={2} fill="url(#pnlGrad)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Win Rate Chart ───────────────────────────────────────────────────────────

function WinRateChart({ data }: { data: Array<{ cycle: number; win_rate: number }> }) {
  const pctData = data.map(d => ({ ...d, win_rate: +(d.win_rate * 100).toFixed(1) }))
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Win Rate Over Time</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={pctData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis domain={[40, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v: number) => [`${v}%`, 'Win Rate']}
          />
          <ReferenceLine y={50} stroke="#475569" strokeDasharray="4 2" label={{ value: '50%', fill: '#475569', fontSize: 10 }} />
          <Line type="monotone" dataKey="win_rate" stroke="#60a5fa" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Signal Conviction Chart ──────────────────────────────────────────────────

function SignalConvictionChart({ data }: { data: Array<{ name: string; value: number }> }) {
  const chartData = data.map(d => ({ ...d, value: +(d.value * 100).toFixed(1) }))
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Signal Conviction (last cycle)</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v: number) => [`${v}%`, 'Conviction']}
          />
          <Bar dataKey="value" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Memory Growth Chart ──────────────────────────────────────────────────────

function MemoryGrowthChart({ data }: { data: Array<{ cycle: number; episodic: number; semantic: number }> }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Memory Accumulation</h3>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
          <defs>
            <linearGradient id="episodicGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="semanticGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#818cf8" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#818cf8" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Area type="stepAfter" dataKey="episodic" stroke="#34d399" strokeWidth={2} fill="url(#episodicGrad)" dot={false} name="Episodic" />
          <Area type="stepAfter" dataKey="semantic" stroke="#818cf8" strokeWidth={2} fill="url(#semanticGrad)" dot={false} name="Semantic" />
        </AreaChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-emerald-400 inline-block" /> Episodic</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-indigo-400 inline-block" /> Semantic</span>
      </div>
    </div>
  )
}

// ─── Activity Feed ────────────────────────────────────────────────────────────

const activityIcons = {
  trade:  { icon: TrendingUp, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  signal: { icon: Zap,        color: 'text-amber-400',   bg: 'bg-amber-500/10'   },
  memory: { icon: Brain,      color: 'text-violet-400',  bg: 'bg-violet-500/10'  },
}

function ActivityFeed({ activities }: { activities: Array<{ cycle: number; type: string; message: string }> }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50">
        <h3 className="text-sm font-semibold text-slate-300">Activity Feed</h3>
        <p className="text-slate-500 text-xs mt-0.5">Live training events: trades, signals, memory extractions</p>
      </div>
      <div className="divide-y divide-slate-700/30 max-h-72 overflow-y-auto">
        {activities.length === 0 && (
          <div className="py-8 text-center text-slate-500 text-sm">No activity yet</div>
        )}
        {activities.map((a, i) => {
          const conf = activityIcons[a.type as keyof typeof activityIcons] ?? activityIcons.signal
          const Icon = conf.icon
          return (
            <div key={i} className="flex items-start gap-3 px-5 py-3 hover:bg-slate-700/20 transition-colors">
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${conf.bg}`}>
                <Icon className={`w-3.5 h-3.5 ${conf.color}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-slate-300 text-sm leading-snug">{a.message}</p>
                <p className="text-slate-600 text-xs mt-0.5">Cycle {a.cycle}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Symbol breakdown ─────────────────────────────────────────────────────────

function SymbolBreakdown({ data }: { data: Array<{ symbol: string; trades: number; win_rate: number; total_pnl: number }> }) {
  if (!data || data.length === 0) return null
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50">
        <h3 className="text-sm font-semibold text-slate-300">Per-Symbol Breakdown</h3>
      </div>
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-700/50">
            {['Symbol', 'Trades', 'Win Rate', 'Total PnL'].map(h => (
              <th key={h} className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((s, i) => (
            <tr key={i} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
              <td className="px-5 py-3 text-slate-200 font-mono text-sm">{s.symbol}</td>
              <td className="px-5 py-3 text-slate-300 tabular-nums text-sm">{s.trades}</td>
              <td className="px-5 py-3 tabular-nums text-sm">
                <span className={s.win_rate >= 0.5 ? 'text-emerald-400' : 'text-rose-400'}>{pct(s.win_rate)}</span>
              </td>
              <td className={`px-5 py-3 tabular-nums text-sm font-medium ${s.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {s.total_pnl >= 0 ? '+' : ''}{usd(s.total_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Recent trades ────────────────────────────────────────────────────────────

function RecentTradesTable({ trades }: { data?: undefined; trades: Array<{ ts: string; sym: string; side: string; size: number; entry: number; exit_price: number; pnl: number }> }) {
  if (!trades || trades.length === 0) return null
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50">
        <h3 className="text-sm font-semibold text-slate-300">Recent Trades</h3>
      </div>
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-700/50">
            {['Time', 'Symbol', 'Side', 'Size', 'Entry', 'Exit', 'PnL'].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.slice(0, 10).map((t, i) => (
            <tr key={i} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
              <td className="px-4 py-3 text-slate-500 text-xs tabular-nums">{t.ts ? new Date(t.ts).toLocaleString() : '—'}</td>
              <td className="px-4 py-3 text-slate-200 font-mono text-sm">{t.sym}</td>
              <td className="px-4 py-3">
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${t.side === 'LONG' ? 'bg-emerald-900/40 text-emerald-400' : 'bg-rose-900/40 text-rose-400'}`}>
                  {t.side}
                </span>
              </td>
              <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{t.size?.toFixed(4) ?? '—'}</td>
              <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{t.entry?.toFixed(2) ?? '—'}</td>
              <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{t.exit_price ? t.exit_price.toFixed(2) : '—'}</td>
              <td className={`px-4 py-3 tabular-nums text-sm font-medium ${t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {t.pnl >= 0 ? '+' : ''}{usd(t.pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Snapshots panel ─────────────────────────────────────────────────────────

function SnapshotsPanel({
  snapshots, onTake, taking,
}: {
  snapshots: TrainingSnapshot[]
  onTake: () => void
  taking: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Snapshots</h3>
          <p className="text-slate-500 text-xs mt-0.5">{snapshots.length} saved · compare metrics across cycles</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onTake}
            disabled={taking}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs rounded-lg transition-colors disabled:opacity-50"
          >
            <Camera className="w-3.5 h-3.5" />
            {taking ? 'Saving…' : 'Take Snapshot'}
          </button>
          {snapshots.length > 0 && (
            <button
              onClick={() => setExpanded(e => !e)}
              className="p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
            >
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>
      {expanded && snapshots.length > 0 && (
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50">
              {['Cycle', 'Created At', 'PnL', 'Win Rate', 'Trades'].map(h => (
                <th key={h} className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {snapshots.map((s, i) => (
              <tr key={i} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                <td className="px-5 py-3 text-slate-200 font-mono text-sm">#{s.cycle}</td>
                <td className="px-5 py-3 text-slate-500 text-xs tabular-nums">{new Date(s.created_at).toLocaleString()}</td>
                <td className={`px-5 py-3 tabular-nums text-sm font-medium ${s.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {s.total_pnl >= 0 ? '+' : ''}{usd(s.total_pnl)}
                </td>
                <td className="px-5 py-3 tabular-nums text-sm">
                  <span className={s.win_rate >= 0.5 ? 'text-emerald-400' : 'text-rose-400'}>{pct(s.win_rate)}</span>
                </td>
                <td className="px-5 py-3 text-slate-300 tabular-nums text-sm">{s.total_trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {expanded && snapshots.length === 0 && (
        <div className="py-6 text-center text-slate-500 text-sm">No snapshots yet</div>
      )}
    </div>
  )
}

// ─── Idle state ───────────────────────────────────────────────────────────────

function IdleState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
      <div className="w-16 h-16 rounded-2xl bg-slate-800 border border-slate-700/50 flex items-center justify-center">
        <Play className="w-7 h-7 text-slate-500" />
      </div>
      <div>
        <p className="text-slate-300 font-semibold text-lg">No active training run</p>
        <p className="text-slate-500 text-sm mt-1 max-w-sm">
          Start a training session to see live progress here. The system will display cycle metrics, memory growth, and trade activity in real-time.
        </p>
      </div>
      <div className="bg-slate-800 rounded-lg border border-slate-700/50 px-4 py-3 text-left max-w-sm">
        <p className="text-slate-500 text-xs font-mono">
          # Run training session<br />
          python train.py --cycles 1000<br />
          <span className="text-slate-600"># Progress written to data/training_progress.json</span>
        </p>
      </div>
    </div>
  )
}

// ─── TrainingPage ─────────────────────────────────────────────────────────────

export function TrainingPage() {
  const [taking, setTaking] = useState(false)
  const [snapFeedback, setSnapFeedback] = useState('')

  // Poll progress and metrics every 5s.
  const { data: progress, loading: progressLoading } = useFetch(
    () => api.training.getProgress(), 5000,
  )
  const { data: metrics, loading: metricsLoading } = useFetch(
    () => api.training.getMetrics(), 5000,
  )
  const { data: snapshots, refetch: refetchSnaps } = useFetch(
    () => api.training.getSnapshots(), 30_000,
  )

  const handleSnapshot = useCallback(async () => {
    setTaking(true)
    try {
      await api.training.takeSnapshot()
      setSnapFeedback('Snapshot saved!')
      refetchSnaps()
      setTimeout(() => setSnapFeedback(''), 3000)
    } catch {
      setSnapFeedback('Failed to save snapshot')
    } finally {
      setTaking(false)
    }
  }, [refetchSnaps])

  const isLoading = progressLoading && metricsLoading
  const isIdle = !progress || progress.status === 'idle' || !progress.run_id

  // Derive cycle + status from metrics (live) or progress (file-based).
  const currentCycle = metrics?.current_cycle ?? progress?.current_cycle ?? 0
  const totalCycles  = metrics?.total_cycles  ?? progress?.total_cycles  ?? 0
  const status       = metrics?.status        ?? progress?.status        ?? 'idle'
  const totalPnL     = metrics?.total_pnl     ?? 0
  const winRate      = metrics?.win_rate       ?? 0
  const totalTrades  = metrics?.total_trades   ?? 0
  const memTotal     = metrics?.memory_count?.total ?? 0

  const pnlHistory      = progress?.pnl_history      ?? []
  const winRateHistory  = progress?.win_rate_history  ?? []
  const memoryGrowth    = progress?.memory_growth     ?? []
  const signalConviction = metrics?.signal_health?.length
    ? metrics.signal_health
    : (progress?.signal_conviction ?? [])
  const activityLog     = progress?.activity_log      ?? []
  const snapList        = snapshots ?? []

  return (
    <div className="space-y-6" data-testid="training-page">
      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
            <Brain className="w-6 h-6 text-emerald-400" />
            Training Progress
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Live feedback loop — watch the system learn in real-time
          </p>
        </div>
        <div className="flex items-center gap-3">
          {!isIdle && progress?.run_id && (
            <span className="text-slate-500 text-xs font-mono bg-slate-800 px-2.5 py-1 rounded border border-slate-700/50">
              {progress.run_id}
            </span>
          )}
          <StatusBadge status={status} />
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <RefreshCw className="w-5 h-5 text-slate-500 animate-spin" />
          <span className="text-slate-500 text-sm ml-2">Loading training data…</span>
        </div>
      )}

      {!isLoading && isIdle && <IdleState />}

      {!isLoading && !isIdle && (
        <>
          {/* ── Top row: key metrics ── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
            <div className="col-span-2 sm:col-span-4 lg:col-span-2">
              <ProgressBar current={currentCycle} total={totalCycles} />
            </div>
            <MetricCard
              label="Elapsed"
              value={elapsed(progress?.started_at ?? '')}
              sub={`ETA ${eta(progress?.started_at ?? '', currentCycle, totalCycles)}`}
              icon={Clock}
              accent="sky"
            />
            <MetricCard
              label="Total PnL"
              value={totalPnL >= 0 ? `+${usd(totalPnL)}` : usd(totalPnL)}
              icon={totalPnL >= 0 ? TrendingUp : TrendingDown}
              accent={totalPnL >= 0 ? 'emerald' : 'rose'}
            />
            <MetricCard
              label="Win Rate"
              value={pct(winRate)}
              sub={winRate >= 0.5 ? '↑ above 50%' : '↓ below 50%'}
              icon={Target}
              accent={winRate >= 0.5 ? 'emerald' : 'amber'}
            />
            <MetricCard
              label="Total Trades"
              value={totalTrades.toLocaleString()}
              icon={Activity}
              accent="sky"
            />
            <MetricCard
              label="Memories"
              value={memTotal.toLocaleString()}
              sub={`${metrics?.memory_count?.episodic ?? 0} episodic · ${metrics?.memory_count?.semantic ?? 0} semantic`}
              icon={Database}
              accent="violet"
            />
          </div>

          {/* ── Regime banner ── */}
          {progress?.current_regime?.name && (
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-3 flex items-center gap-3">
              <Zap className="w-4 h-4 text-amber-400 shrink-0" />
              <p className="text-slate-300 text-sm">
                <span className="font-semibold">Current regime: </span>
                <span className={`font-bold ${
                  progress.current_regime.name === 'BULL' ? 'text-emerald-400' :
                  progress.current_regime.name === 'BEAR' ? 'text-rose-400' : 'text-amber-400'
                }`}>{progress.current_regime.name}</span>
                {' '}({pct(progress.current_regime.confidence)} confidence) — dominant signal: {progress.current_regime.dominant_signal}
              </p>
            </div>
          )}

          {/* ── Middle: live charts ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PnLChart data={pnlHistory} />
            <WinRateChart data={winRateHistory} />
            <SignalConvictionChart data={signalConviction} />
            <MemoryGrowthChart data={memoryGrowth} />
          </div>

          {/* ── Bottom: activity + tables ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ActivityFeed activities={activityLog} />
            <div className="space-y-4">
              {metrics?.symbol_breakdown && metrics.symbol_breakdown.length > 0 && (
                <SymbolBreakdown data={metrics.symbol_breakdown} />
              )}
            </div>
          </div>

          {metrics?.recent_trades && metrics.recent_trades.length > 0 && (
            <RecentTradesTable trades={metrics.recent_trades} />
          )}

          {/* ── Snapshots ── */}
          <SnapshotsPanel
            snapshots={snapList}
            onTake={handleSnapshot}
            taking={taking}
          />
          {snapFeedback && (
            <div className="flex items-center gap-2 text-emerald-400 text-sm">
              <CheckCircle className="w-4 h-4" />
              {snapFeedback}
            </div>
          )}
        </>
      )}
    </div>
  )
}
