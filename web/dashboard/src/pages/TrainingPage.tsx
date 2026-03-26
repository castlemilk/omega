import React, { useState, useEffect } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { Dumbbell, TrendingUp, Percent, BookOpen, Zap, ChevronRight } from 'lucide-react'

// ─── Mock training data ────────────────────────────────────────────────────────

const TOTAL_CYCLES = 1000

function buildTrainingHistory(count: number) {
  const pts = []
  let pnl = 0
  let winStreak = 0
  for (let i = 1; i <= count; i++) {
    const winRate = 0.48 + (i / count) * 0.1 + (Math.random() - 0.5) * 0.08
    const won = Math.random() < winRate
    const trade = won ? 0.8 + Math.random() * 1.2 : -(0.4 + Math.random() * 0.6)
    pnl += trade
    winStreak = won ? winStreak + 1 : 0
    if (i % Math.max(1, Math.floor(count / 80)) === 0) {
      pts.push({
        cycle: i,
        pnl: parseFloat(pnl.toFixed(2)),
        winRate: parseFloat((winRate * 100).toFixed(1)),
        memories: Math.floor(i * 0.12 + Math.random() * 5),
      })
    }
  }
  return pts
}

interface TradeEvent {
  id: string
  cycle: number
  outcome: 'win' | 'loss'
  pnl: number
  signal: string
  confidence: number
  ts: string
}

function buildTradeLog(currentCycle: number): TradeEvent[] {
  const signals = ['Momentum', 'Sentiment', 'Trend', 'MeanRev', 'Breakout', 'Volume']
  const events: TradeEvent[] = []
  const now = Date.now()
  for (let i = 0; i < 12; i++) {
    const won = Math.random() > 0.4
    events.push({
      id: `trade-${currentCycle - i}`,
      cycle: currentCycle - i,
      outcome: won ? 'win' : 'loss',
      pnl: won ? parseFloat((0.5 + Math.random() * 1.5).toFixed(2)) : -parseFloat((0.3 + Math.random() * 0.8).toFixed(2)),
      signal: signals[Math.floor(Math.random() * signals.length)],
      confidence: parseFloat((0.5 + Math.random() * 0.45).toFixed(2)),
      ts: new Date(now - i * 180000).toTimeString().slice(0, 5),
    })
  }
  return events
}

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color = 'text-slate-100' }: {
  label: string; value: string; sub?: string; color?: string
}) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
      <p className="text-slate-500 text-xs mb-1">{label}</p>
      <p className={`text-2xl font-bold tabular-nums ${color}`}>{value}</p>
      {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
    </div>
  )
}

// ─── Trade feed row ───────────────────────────────────────────────────────────

function TradeFeedRow({ trade }: { trade: TradeEvent }) {
  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 text-sm border-b border-slate-700/40 last:border-0 ${
      trade.outcome === 'win' ? 'bg-emerald-500/5' : 'bg-rose-500/5'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
        trade.outcome === 'win' ? 'bg-emerald-400' : 'bg-rose-400'
      }`} />
      <span className="text-slate-500 text-xs w-10 shrink-0">#{trade.cycle}</span>
      <span className="text-slate-400 w-20 shrink-0">{trade.signal}</span>
      <span className={`font-medium tabular-nums ${trade.outcome === 'win' ? 'text-emerald-400' : 'text-rose-400'}`}>
        {trade.pnl > 0 ? '+' : ''}{trade.pnl}%
      </span>
      <span className="text-slate-600 text-xs ml-auto">conf {(trade.confidence * 100).toFixed(0)}%</span>
      <span className="text-slate-600 text-xs">{trade.ts}</span>
    </div>
  )
}

// ─── TrainingPage ─────────────────────────────────────────────────────────────

export function TrainingPage() {
  const [currentCycle, setCurrentCycle] = useState(724)
  const [isRunning, setIsRunning] = useState(true)
  const history = buildTrainingHistory(currentCycle)
  const trades = buildTradeLog(currentCycle)

  // Simulate live progress
  useEffect(() => {
    if (!isRunning) return
    const id = setInterval(() => {
      setCurrentCycle(c => {
        if (c >= TOTAL_CYCLES) { setIsRunning(false); return c }
        return c + 1
      })
    }, 800)
    return () => clearInterval(id)
  }, [isRunning])

  const progress = (currentCycle / TOTAL_CYCLES) * 100
  const latest = history[history.length - 1] ?? { pnl: 0, winRate: 52, memories: 0 }
  const wins = trades.filter(t => t.outcome === 'win').length
  const winPct = ((wins / trades.length) * 100).toFixed(1)

  return (
    <div className="space-y-6" data-testid="training-page">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <Dumbbell className="w-6 h-6 text-violet-400" />
            Training Progress
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Platform-wide training run — reinforcement learning loop
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isRunning && (
            <span className="flex items-center gap-1.5 text-xs text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              Running
            </span>
          )}
          <button
            onClick={() => setIsRunning(v => !v)}
            className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 text-xs font-medium transition-colors"
          >
            {isRunning ? 'Pause' : 'Resume'}
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5 space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-300 font-medium flex items-center gap-2">
            <Zap className="w-4 h-4 text-violet-400" />
            Cycle {currentCycle.toLocaleString()} / {TOTAL_CYCLES.toLocaleString()}
          </span>
          <span className="text-slate-400 tabular-nums">{progress.toFixed(1)}%</span>
        </div>
        <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-violet-500 to-emerald-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-slate-600">
          <span>Start</span>
          <span>{TOTAL_CYCLES - currentCycle} cycles remaining</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Cumulative PnL"
          value={`${latest.pnl > 0 ? '+' : ''}${latest.pnl.toFixed(1)}%`}
          color={latest.pnl > 0 ? 'text-emerald-400' : 'text-rose-400'}
          sub="since training start"
        />
        <StatCard
          label="Win Rate"
          value={`${latest.winRate.toFixed(1)}%`}
          color="text-sky-400"
          sub="rolling 50-cycle avg"
        />
        <StatCard
          label="Memories"
          value={latest.memories.toLocaleString()}
          color="text-violet-400"
          sub="episodic + semantic"
        />
        <StatCard
          label="Live Win Rate"
          value={`${winPct}%`}
          color={parseFloat(winPct) >= 50 ? 'text-emerald-400' : 'text-amber-400'}
          sub="last 12 trades"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* PnL chart */}
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
          <p className="text-slate-400 text-sm font-medium mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            Cumulative PnL
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={history} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelFormatter={v => `Cycle ${v}`}
                formatter={(v: number) => [`${v > 0 ? '+' : ''}${v.toFixed(2)}%`, 'PnL']}
              />
              <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 2" />
              <Line type="monotone" dataKey="pnl" stroke="#34d399" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Win rate trend */}
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
          <p className="text-slate-400 text-sm font-medium mb-3 flex items-center gap-2">
            <Percent className="w-4 h-4 text-sky-400" />
            Win Rate Trend
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={history} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis
                tick={{ fill: '#64748b', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={v => `${v}%`}
                domain={[40, 70]}
              />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelFormatter={v => `Cycle ${v}`}
                formatter={(v: number) => [`${v.toFixed(1)}%`, 'Win Rate']}
              />
              <ReferenceLine y={50} stroke="#fbbf24" strokeDasharray="4 2" strokeWidth={1} />
              <Line type="monotone" dataKey="winRate" stroke="#38bdf8" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Memory accumulation */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
        <p className="text-slate-400 text-sm font-medium mb-3 flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-violet-400" />
          Memory Accumulation
        </p>
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={history} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <XAxis dataKey="cycle" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelFormatter={v => `Cycle ${v}`}
              formatter={(v: number) => [v, 'Memories']}
            />
            <Line type="monotone" dataKey="memories" stroke="#a78bfa" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Trade activity feed */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
          <p className="text-slate-300 text-sm font-medium">Live Trade Activity</p>
          <ChevronRight className="w-4 h-4 text-slate-600" />
        </div>
        <div>
          {trades.map(t => <TradeFeedRow key={t.id} trade={t} />)}
        </div>
      </div>
    </div>
  )
}
