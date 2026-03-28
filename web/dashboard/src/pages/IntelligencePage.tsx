import React from 'react'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ReferenceLine,
} from 'recharts'
import {
  Brain, CheckCircle, XCircle, Activity, Database,
  TrendingUp, Zap, Shield, Eye, MessageSquare, GitMerge,
  RefreshCw, BarChart2, Cpu, Star,
} from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import {
  api,
  type IntelligenceHistory,
  type IntelligenceCycleRecord,
  type ReflectionRecord,
  type MemoryQuality,
} from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pct(v: number, d = 1) { return `${(v * 100).toFixed(d)}%` }
function fmt2(v: number) { return v.toFixed(2) }
function usd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
}

function scoreTextClass(s: number) {
  if (s >= 0.875) return 'text-emerald-400'
  if (s >= 0.625) return 'text-sky-400'
  if (s >= 0.375) return 'text-amber-400'
  return 'text-rose-400'
}

function scoreHex(s: number) {
  if (s >= 0.875) return '#34d399'
  if (s >= 0.625) return '#38bdf8'
  if (s >= 0.375) return '#fbbf24'
  return '#f87171'
}

function checkPassBorderClass(passing: boolean) {
  return passing ? 'border-l-emerald-500' : 'border-l-rose-500/50'
}

// ─── Check Definitions ───────────────────────────────────────────────────────

interface CheckDef {
  key: keyof IntelligenceCycleRecord
  label: string
  shortLabel: string
  icon: React.ElementType
  threshold: string
  description: string
}

const CHECKS: CheckDef[] = [
  { key: 'brain_calls',                 label: 'LLM Reasoning',       shortLabel: 'LLM',     icon: Brain,      threshold: '> 0',    description: 'Active brain calls per cycle' },
  { key: 'improve_calls',               label: 'Self-Improvement',     shortLabel: 'Improve', icon: TrendingUp, threshold: '> 0',    description: 'Improvement engine invocations' },
  { key: 'episodes_created',            label: 'Episodic Learning',    shortLabel: 'Episodes',icon: Database,   threshold: '> 0',    description: 'New episodes stored to memory' },
  { key: 'semantic_patterns_extracted', label: 'Pattern Recognition',  shortLabel: 'Patterns',icon: Eye,        threshold: '> 0',    description: 'Semantic patterns extracted' },
  { key: 'shared_memory_reads',         label: 'Cross-Project Memory', shortLabel: 'XProj',   icon: GitMerge,   threshold: '> 0',    description: 'Reads from shared memory bus' },
  { key: 'signals_nonzero',             label: 'Signal Coverage',      shortLabel: 'Signals', icon: Zap,        threshold: '> 10',   description: 'Active non-zero signals in cycle' },
  { key: 'rmt_info_ratio',              label: 'Market Structure',     shortLabel: 'RMT',     icon: Activity,   threshold: '> 0.30', description: 'RMT information ratio' },
  { key: 'debate_gate_invocations',     label: 'Risk Oversight',       shortLabel: 'Risk',    icon: Shield,     threshold: '> 0',    description: 'Adversarial debate gate checks' },
]

function checkPasses(key: string, value: number | null | undefined): boolean {
  if (value == null) return false
  if (key === 'signals_nonzero') return value > 10
  if (key === 'rmt_info_ratio')  return value > 0.3
  return value > 0
}

function getCheckValue(r: IntelligenceCycleRecord, key: string): number | null {
  const v = (r as unknown as Record<string, unknown>)[key]
  return typeof v === 'number' ? v : null
}

function computeChecksPassing(r: IntelligenceCycleRecord): number {
  return CHECKS.filter(d => checkPasses(d.key, getCheckValue(r, d.key))).length
}

// ─── Score Gauge ─────────────────────────────────────────────────────────────
// Half-circle SVG arc gauge. Arc length for radius=40 semicircle ≈ 125.66

function ScoreGauge({ score }: { score: number }) {
  const arcLen = Math.PI * 40           // ≈ 125.66
  const filled = score * arcLen
  const color  = scoreHex(score)
  const cls    = scoreTextClass(score)
  return (
    <div className="flex flex-col items-center">
      <svg width="108" height="64" viewBox="0 0 108 64" aria-label={`Score ${Math.round(score * 100)}%`}>
        {/* Track */}
        <path d="M 14 58 A 40 40 0 0 1 94 58"
          fill="none" stroke="#1e293b" strokeWidth="9" strokeLinecap="round" />
        {/* Fill */}
        <path d="M 14 58 A 40 40 0 0 1 94 58"
          fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${filled} ${arcLen}`}
          style={{ transition: 'stroke-dasharray 0.6s ease' }}
        />
        {/* Tick marks */}
        {[0, 0.25, 0.5, 0.75, 1].map(t => {
          const angle = Math.PI * t               // 0 = left, π = right
          const cx = 54 - 40 * Math.cos(angle)
          const cy = 58 - 40 * Math.sin(angle)
          return <circle key={t} cx={cx} cy={cy} r="2" fill="#334155" />
        })}
      </svg>
      <div className="-mt-6 text-center">
        <span className={`text-3xl font-black tabular-nums ${cls}`}>
          {Math.round(score * 100)}
        </span>
        <span className="text-slate-600 text-sm">%</span>
      </div>
    </div>
  )
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, icon: Icon, accent = 'slate',
}: {
  label: string
  value: React.ReactNode
  sub?: string
  icon: React.ElementType
  accent?: 'emerald' | 'sky' | 'amber' | 'rose' | 'violet' | 'slate'
}) {
  const colors: Record<string, string> = {
    emerald: 'text-emerald-400 bg-emerald-500/10',
    sky:     'text-sky-400 bg-sky-500/10',
    amber:   'text-amber-400 bg-amber-500/10',
    rose:    'text-rose-400 bg-rose-500/10',
    violet:  'text-violet-400 bg-violet-500/10',
    slate:   'text-slate-400 bg-slate-700/40',
  }
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-slate-500 text-xs uppercase tracking-wider">{label}</p>
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${colors[accent]}`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
      </div>
      <p className="text-slate-100 text-xl font-bold tabular-nums">{value}</p>
      {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
    </div>
  )
}

// ─── Intelligence Score Trend ─────────────────────────────────────────────────

function ScoreTrendChart({ records }: { records: IntelligenceCycleRecord[] }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Intelligence Score — Cycle History</h3>
          <p className="text-slate-500 text-xs mt-0.5">Composite score (0–1) across 8 intelligence checks</p>
        </div>
        <span className="text-slate-600 text-xs font-mono">{records.length} cycles</span>
      </div>
      {records.length === 0 ? (
        <div className="h-36 flex items-center justify-center">
          <p className="text-slate-600 text-sm font-mono">── no data ──</p>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart data={records} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <defs>
              <linearGradient id="intScoreGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#34d399" stopOpacity={0.35} />
                <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="cycle"
              tick={{ fill: '#64748b', fontSize: 10, fontFamily: 'monospace' }}
              axisLine={false} tickLine={false}
            />
            <YAxis
              domain={[0, 1]}
              tick={{ fill: '#64748b', fontSize: 10, fontFamily: 'monospace' }}
              axisLine={false} tickLine={false}
              tickFormatter={v => `${Math.round(v * 100)}`}
            />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#94a3b8', fontFamily: 'monospace' }}
              labelFormatter={v => `Cycle ${v}`}
              formatter={(v: number) => [`${(v * 100).toFixed(0)}%`, 'Score']}
            />
            <ReferenceLine y={0.5}  stroke="#475569" strokeDasharray="4 2" label={{ value: '50', position: 'insideTopLeft', fill: '#475569', fontSize: 9 }} />
            <ReferenceLine y={0.75} stroke="#334155" strokeDasharray="2 4" label={{ value: '75', position: 'insideTopLeft', fill: '#334155', fontSize: 9 }} />
            <Area
              type="monotone" dataKey="intelligence_score"
              stroke="#34d399" strokeWidth={2}
              fill="url(#intScoreGrad)" dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─── Check Row ────────────────────────────────────────────────────────────────

function CheckRow({ def, record }: { def: CheckDef; record: IntelligenceCycleRecord | null }) {
  const Icon   = def.icon
  const raw    = record ? getCheckValue(record, def.key) : null
  const passing = checkPasses(def.key, raw)
  const display = raw == null ? '—' : def.key === 'rmt_info_ratio' ? fmt2(raw) : raw.toLocaleString()

  return (
    <tr className={`border-b border-slate-700/30 border-l-2 ${checkPassBorderClass(passing)} hover:bg-slate-800/60 transition-colors`}>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <div className={`w-6 h-6 rounded flex items-center justify-center shrink-0 ${passing ? 'bg-emerald-500/10' : 'bg-slate-700/40'}`}>
            <Icon className={`w-3 h-3 ${passing ? 'text-emerald-400' : 'text-slate-500'}`} />
          </div>
          <div>
            <p className="text-slate-300 text-xs font-medium leading-none">{def.label}</p>
            <p className="text-slate-600 text-xs mt-0.5 leading-none">{def.description}</p>
          </div>
        </div>
      </td>
      <td className="px-3 py-2.5 text-center w-10">
        {passing
          ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400 mx-auto" />
          : <XCircle    className="w-3.5 h-3.5 text-rose-500/70 mx-auto" />
        }
      </td>
      <td className="px-3 py-2.5 text-right w-20">
        <span className={`font-mono text-xs tabular-nums ${passing ? 'text-slate-200' : 'text-slate-500'}`}>
          {display}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right w-16">
        <span className="text-slate-700 text-xs font-mono">{def.threshold}</span>
      </td>
    </tr>
  )
}

// ─── Memory Gauge Bar ─────────────────────────────────────────────────────────

function GaugeBar({ label, value, invert = false }: { label: string; value: number; invert?: boolean }) {
  const display = pct(invert ? 1 - value : value)
  const frac    = Math.min(1, invert ? 1 - value : value)
  const color   = frac >= 0.7 ? '#34d399' : frac >= 0.4 ? '#fbbf24' : '#f87171'
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-slate-400 text-xs">{label}</span>
        <span className={`text-xs font-mono tabular-nums ${frac >= 0.7 ? 'text-emerald-400' : frac >= 0.4 ? 'text-amber-400' : 'text-rose-400'}`}>
          {display}
        </span>
      </div>
      <div className="w-full bg-slate-700/40 rounded-full h-1.5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${frac * 100}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

// ─── Memory Quality Panel ─────────────────────────────────────────────────────

function MemoryQualityPanel({ mq }: { mq: MemoryQuality | null }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-4 py-4 border-b border-slate-700/50">
        <h3 className="text-sm font-semibold text-slate-300">Memory Quality</h3>
        <p className="text-slate-500 text-xs mt-0.5">System health &amp; effectiveness metrics</p>
      </div>
      {!mq ? (
        <div className="px-4 py-12 text-center text-slate-600 text-sm font-mono">── no data ──</div>
      ) : (
        <div className="px-4 py-4 space-y-3">
          <GaugeBar label="Memory Utilization"  value={mq.memory_utilization} />
          <GaugeBar label="Episode Diversity"   value={mq.episode_diversity} />
          <GaugeBar label="Cross-Project Ratio" value={mq.cross_project_ratio} />
          <GaugeBar label="Freshness"           value={mq.stale_memory_pct} invert />
          <GaugeBar label="Avg Episode Rating"  value={mq.avg_episode_rating} />

          <div className="border-t border-slate-700/30 pt-3 mt-2 grid grid-cols-2 gap-x-4 gap-y-2">
            {[
              { label: 'Episodes',          val: mq.episode_count.toLocaleString() },
              { label: 'Semantic',          val: mq.semantic_count.toLocaleString() },
              { label: 'Shared Memories',   val: mq.shared_memory_count.toLocaleString() },
              { label: 'Ratings',           val: mq.memory_ratings_count.toLocaleString() },
              { label: 'Influenced Trades', val: mq.memory_influenced_trades.toLocaleString() },
              { label: 'Mem Win Rate',      val: mq.memory_win_rate > 0 ? pct(mq.memory_win_rate) : 'n/a' },
            ].map(({ label, val }) => (
              <div key={label} className="flex justify-between items-center">
                <span className="text-slate-600 text-xs">{label}</span>
                <span className="text-slate-300 text-xs font-mono">{val}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Reflection Card ──────────────────────────────────────────────────────────

function ReflectionCard({ r }: { r: ReflectionRecord }) {
  const resultStyle: Record<string, string> = {
    win:  'text-emerald-300 bg-emerald-900/40 border border-emerald-700/30',
    loss: 'text-rose-300 bg-rose-900/30 border border-rose-700/30',
    hold: 'text-slate-400 bg-slate-700/40 border border-slate-600/30',
  }
  const rs = resultStyle[r.trade_result] ?? resultStyle.hold
  const stars = Math.max(0, Math.min(5, Math.round(r.rating)))

  return (
    <div className="px-4 py-3 border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-slate-500 font-mono text-xs shrink-0">#{r.cycle}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-medium uppercase shrink-0 ${rs}`}>
          {r.trade_result}
        </span>
        <span className="text-slate-500 text-xs truncate">{r.regime}</span>
        <span className="ml-auto text-amber-400 text-xs tracking-tighter shrink-0" title={`${r.rating}/5`}>
          {'★'.repeat(stars)}{'☆'.repeat(5 - stars)}
        </span>
      </div>
      <p className="text-slate-300 text-xs leading-snug line-clamp-2">{r.lesson || r.signal_summary}</p>
      <p className="text-slate-600 text-xs mt-1 font-mono">conviction {fmt2(r.conviction)}</p>
    </div>
  )
}

// ─── Reflection Feed ──────────────────────────────────────────────────────────

function ReflectionFeed({ reflections }: { reflections: ReflectionRecord[] }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden flex flex-col">
      <div className="px-4 py-4 border-b border-slate-700/50 flex items-center justify-between shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Node Reflections</h3>
          <p className="text-slate-500 text-xs mt-0.5">LLM self-reflection on trading outcomes</p>
        </div>
        <MessageSquare className="w-4 h-4 text-slate-600" />
      </div>
      <div className="overflow-y-auto max-h-80 divide-y divide-slate-700/20">
        {reflections.length === 0 ? (
          <div className="py-12 text-center text-slate-600 text-sm font-mono">── no reflections ──</div>
        ) : (
          reflections.map((r, i) => <ReflectionCard key={r.episode_id || i} r={r} />)
        )}
      </div>
    </div>
  )
}

// ─── Check Sparkline Grid ─────────────────────────────────────────────────────

function CheckSparkline({ records, checkKey }: { records: IntelligenceCycleRecord[]; checkKey: string }) {
  const data = records.slice(-30).map(r => ({
    cycle: r.cycle,
    v: getCheckValue(r, checkKey) ?? 0,
  }))
  return (
    <ResponsiveContainer width="100%" height={32}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <Area type="monotone" dataKey="v" stroke="#38bdf8" strokeWidth={1.5}
          fill="#38bdf8" fillOpacity={0.08} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function CheckSparklineGrid({ records }: { records: IntelligenceCycleRecord[] }) {
  if (records.length < 2) return null
  const latest = records[records.length - 1]

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300">Check Activity — Last 30 Cycles</h3>
        <span className="text-slate-600 text-xs font-mono">sparklines</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-4">
        {CHECKS.map(def => {
          const Icon    = def.icon
          const raw     = getCheckValue(latest, def.key)
          const passing = checkPasses(def.key, raw)
          return (
            <div key={def.key} className="space-y-1">
              <div className="flex items-center gap-1.5">
                <Icon className={`w-3 h-3 shrink-0 ${passing ? 'text-emerald-400' : 'text-slate-600'}`} />
                <span className="text-slate-400 text-xs truncate">{def.shortLabel}</span>
                <span className={`ml-auto text-xs font-mono tabular-nums ${passing ? 'text-slate-300' : 'text-slate-600'}`}>
                  {raw == null ? '—' : def.key === 'rmt_info_ratio' ? fmt2(raw) : raw.toLocaleString()}
                </span>
              </div>
              <CheckSparkline records={records} checkKey={def.key} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Adversarial Ring Breakdown ───────────────────────────────────────────────

function AdversarialPanel({ latest }: { latest: IntelligenceCycleRecord | null }) {
  const rings = [
    { label: 'Ring 1', key: 'adversarial_ring1', desc: 'Boundary checks' },
    { label: 'Ring 2', key: 'adversarial_ring2', desc: 'Logic validation' },
    { label: 'Ring 3', key: 'adversarial_ring3', desc: 'Debate gate adversarial' },
  ]
  const total = latest
    ? ((latest.adversarial_ring1 ?? 0) + (latest.adversarial_ring2 ?? 0) + (latest.adversarial_ring3 ?? 0))
    : 0

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Adversarial Activity</h3>
        <span className={`text-sm font-bold tabular-nums ${total > 0 ? 'text-rose-400' : 'text-slate-500'}`}>
          {total.toLocaleString()}
        </span>
      </div>
      <div className="space-y-2.5">
        {rings.map(({ label, key, desc }) => {
          const val = latest ? ((latest as unknown as Record<string, number>)[key] ?? 0) : 0
          const maxVal = Math.max(total, 1)
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-slate-500 text-xs">{label} <span className="text-slate-700">·</span> <span className="text-slate-700 text-xs">{desc}</span></span>
                <span className={`text-xs font-mono ${val > 0 ? 'text-rose-400' : 'text-slate-600'}`}>{val}</span>
              </div>
              <div className="w-full bg-slate-700/40 rounded-full h-1">
                <div
                  className="h-full rounded-full bg-rose-500/60 transition-all duration-500"
                  style={{ width: `${(val / maxVal) * 100}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Training PnL History ─────────────────────────────────────────────────────

function TrainingHistoryPanel() {
  const { data: progress } = useFetch(() => api.training.getProgress(), 30_000)
  const { data: snapshots } = useFetch(() => api.training.getSnapshots(), 30_000)

  const pnlHistory = progress?.pnl_history ?? []
  const snapList   = snapshots ?? []
  const lastPnl    = pnlHistory.length > 0 ? pnlHistory[pnlHistory.length - 1].pnl : 0
  const pnlColor   = lastPnl >= 0 ? '#34d399' : '#f87171'

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">Training Run History</h3>
          <p className="text-slate-500 text-xs mt-0.5">Cumulative PnL curve &amp; snapshot log</p>
        </div>
        <div className="flex items-center gap-3 text-xs font-mono">
          {progress?.status && (
            <span className={`px-2 py-0.5 rounded border uppercase ${
              progress.status === 'running'   ? 'text-emerald-300 bg-emerald-900/30 border-emerald-700/40' :
              progress.status === 'completed' ? 'text-sky-300 bg-sky-900/30 border-sky-700/40' :
              progress.status === 'failed'    ? 'text-rose-300 bg-rose-900/30 border-rose-700/40' :
              'text-slate-500 bg-slate-700/30 border-slate-700/40'
            }`}>{progress.status}</span>
          )}
          {progress?.current_cycle != null && (
            <span className="text-slate-500">cycle {progress.current_cycle} / {progress.total_cycles}</span>
          )}
        </div>
      </div>

      <div className="p-5 space-y-4">
        {pnlHistory.length === 0 ? (
          <div className="h-36 flex items-center justify-center text-slate-600 text-sm font-mono">── no training data ──</div>
        ) : (
          <ResponsiveContainer width="100%" height={150}>
            <AreaChart data={pnlHistory} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <defs>
                <linearGradient id="trainPnlGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={pnlColor} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={pnlColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
                labelStyle={{ color: '#94a3b8', fontFamily: 'monospace' }}
                labelFormatter={v => `Cycle ${v}`}
                formatter={(v: number) => [`$${v.toFixed(2)}`, 'PnL']}
              />
              <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 2" />
              <Area
                type="monotone" dataKey="pnl" stroke={pnlColor} strokeWidth={2}
                fill="url(#trainPnlGrad)" dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}

        {snapList.length > 0 && (
          <div>
            <p className="text-slate-600 text-xs uppercase tracking-wider mb-2">Saved Snapshots</p>
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/40">
                  {['Cycle', 'PnL', 'Win Rate', 'Trades', 'Saved At'].map(h => (
                    <th key={h} className="pb-2 text-left text-xs font-medium text-slate-600 uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {snapList.slice().reverse().slice(0, 8).map((s, i) => (
                  <tr key={i} className="border-b border-slate-700/20 hover:bg-slate-700/20 transition-colors">
                    <td className="py-2 text-slate-400 font-mono text-xs">#{s.cycle}</td>
                    <td className={`py-2 font-mono text-xs ${s.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {s.total_pnl >= 0 ? '+' : ''}{usd(s.total_pnl)}
                    </td>
                    <td className={`py-2 font-mono text-xs ${s.win_rate >= 0.5 ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {pct(s.win_rate)}
                    </td>
                    <td className="py-2 text-slate-400 font-mono text-xs">{s.total_trades}</td>
                    <td className="py-2 text-slate-600 text-xs">{new Date(s.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── IntelligencePage ─────────────────────────────────────────────────────────

export function IntelligencePage() {
  const { data: history, loading: histLoading }   = useFetch(() => api.intelligence.getHistory(),      10_000)
  const { data: reflections }                      = useFetch(() => api.intelligence.getReflections(),  15_000)
  const { data: memQuality }                       = useFetch(() => api.intelligence.getMemoryQuality(), 30_000)

  const records  = history?.records ?? []
  const latest   = records.length > 0 ? records[records.length - 1] : null
  const score    = latest?.intelligence_score ?? history?.avg_score_7d ?? 0
  const checksPassing = latest ? computeChecksPassing(latest) : (history?.checks_passing ?? 0)
  const totalChecks   = history?.total_checks ?? 8
  const reflList      = reflections ?? []

  return (
    <div className="space-y-5" data-testid="intelligence-page">

      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
            <Brain className="w-6 h-6 text-emerald-400" />
            Intelligence Monitor
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Per-cycle intelligence layer · 8-check composite score · memory quality · LLM self-reflection
          </p>
        </div>
        <div className="flex items-center gap-2">
          {latest && (
            <span className="text-slate-500 text-xs font-mono bg-slate-800/80 px-2.5 py-1 rounded border border-slate-700/50">
              cycle #{latest.cycle}
            </span>
          )}
          {histLoading && <RefreshCw className="w-4 h-4 text-slate-500 animate-spin" />}
        </div>
      </div>

      {/* ── Status banner ── */}
      {latest && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${score >= 0.625 ? 'bg-emerald-400' : score >= 0.375 ? 'bg-amber-400' : 'bg-rose-400'} animate-pulse`} />
            <span className="text-slate-400 text-xs">Score</span>
            <span className={`font-bold text-sm tabular-nums ${scoreTextClass(score)}`}>{Math.round(score * 100)}%</span>
          </div>
          {latest.brain_provider && (
            <div className="flex items-center gap-1.5">
              <Cpu className="w-3 h-3 text-slate-600" />
              <span className="text-slate-500 text-xs font-mono">{latest.brain_provider}</span>
            </div>
          )}
          {latest.brain_latency_ms != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-600 text-xs font-mono">{latest.brain_latency_ms.toFixed(0)} ms</span>
            </div>
          )}
          {latest.brain_tokens_used != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-600 text-xs font-mono">{latest.brain_tokens_used.toLocaleString()} tok</span>
            </div>
          )}
          {latest.trust_score_avg != null && (
            <div className="flex items-center gap-1.5">
              <Star className="w-3 h-3 text-amber-500/60" />
              <span className="text-slate-500 text-xs font-mono">trust {fmt2(latest.trust_score_avg)}</span>
            </div>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            <span className="text-slate-600 text-xs">routing</span>
            <span className="text-slate-400 text-xs font-mono">{latest.routing_decisions}</span>
          </div>
        </div>
      )}

      {/* ── KPI row ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Score gauge */}
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4 flex flex-col items-center justify-center gap-1">
          <p className="text-slate-500 text-xs uppercase tracking-wider">Composite Score</p>
          <ScoreGauge score={score} />
        </div>

        <KpiCard
          label="Checks Passing"
          value={
            <span>
              <span className={scoreTextClass(checksPassing / totalChecks)}>
                {checksPassing}
              </span>
              <span className="text-slate-600 text-base">/{totalChecks}</span>
            </span>
          }
          sub="intelligence checks"
          icon={CheckCircle}
          accent={checksPassing === totalChecks ? 'emerald' : checksPassing >= 6 ? 'sky' : checksPassing >= 4 ? 'amber' : 'rose'}
        />

        <KpiCard
          label="Brain Calls"
          value={(latest?.brain_calls ?? 0).toLocaleString()}
          sub={latest?.brain_provider ?? 'no provider'}
          icon={Brain}
          accent="sky"
        />

        <KpiCard
          label="Episodes"
          value={(memQuality?.episode_count ?? 0).toLocaleString()}
          sub={`+${latest?.episodes_created ?? 0} this cycle`}
          icon={Database}
          accent="violet"
        />

        <KpiCard
          label="Semantic"
          value={(memQuality?.semantic_count ?? 0).toLocaleString()}
          sub={`+${latest?.semantic_patterns_extracted ?? 0} this cycle`}
          icon={Eye}
          accent="slate"
        />

        <KpiCard
          label="Avg Rating"
          value={(memQuality?.avg_episode_rating != null
            ? (memQuality.avg_episode_rating * 5).toFixed(1)
            : '—')}
          sub={memQuality
            ? '★'.repeat(Math.round(memQuality.avg_episode_rating * 5)).padEnd(5, '☆')
            : '☆☆☆☆☆'}
          icon={Star}
          accent="amber"
        />
      </div>

      {/* ── Score trend chart ── */}
      <ScoreTrendChart records={records} />

      {/* ── 3-column: checks + memory + reflections ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Checks breakdown */}
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
          <div className="px-4 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-300">Intelligence Checks</h3>
            <span className={`text-xs font-mono px-2 py-0.5 rounded border ${
              checksPassing === totalChecks
                ? 'text-emerald-300 bg-emerald-900/30 border-emerald-700/40'
                : checksPassing >= 6
                ? 'text-sky-300 bg-sky-900/30 border-sky-700/40'
                : 'text-amber-300 bg-amber-900/30 border-amber-700/40'
            }`}>
              {checksPassing}/{totalChecks} PASS
            </span>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/30">
                <th className="px-4 py-2 text-left text-xs text-slate-600 uppercase tracking-wider">Check</th>
                <th className="px-3 py-2 text-center text-xs text-slate-600 uppercase tracking-wider w-10">✓</th>
                <th className="px-3 py-2 text-right text-xs text-slate-600 uppercase tracking-wider w-20">Val</th>
                <th className="px-3 py-2 text-right text-xs text-slate-600 uppercase tracking-wider w-16">Min</th>
              </tr>
            </thead>
            <tbody>
              {CHECKS.map(def => (
                <CheckRow key={def.key} def={def} record={latest} />
              ))}
            </tbody>
          </table>
          {!latest && (
            <div className="py-8 text-center text-slate-600 text-sm font-mono">── no cycle data ──</div>
          )}
        </div>

        {/* Memory quality */}
        <MemoryQualityPanel mq={memQuality ?? null} />

        {/* Reflection feed */}
        <ReflectionFeed reflections={reflList} />
      </div>

      {/* ── 2-column: sparklines + adversarial ── */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-3">
          <CheckSparklineGrid records={records} />
        </div>
        <AdversarialPanel latest={latest} />
      </div>

      {/* ── Training run history + PnL curves ── */}
      <TrainingHistoryPanel />

    </div>
  )
}
