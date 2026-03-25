import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { useFetch } from '../hooks/useFetch'
import { api } from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function usd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
}
function pct(v: number) {
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}
function fmt2(v: number) { return v.toFixed(2) }

// ─── Stat cell ───────────────────────────────────────────────────────────────

function StatCell({ label, value, positive, mono = true }: {
  label: string; value: string; positive?: boolean; mono?: boolean;
}) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
      <p className="text-slate-500 text-xs uppercase tracking-wider mb-2">{label}</p>
      <p className={`text-lg font-bold ${mono ? 'tabular-nums' : ''} ${
        positive === undefined ? 'text-slate-100' :
        positive ? 'text-emerald-400' : 'text-rose-400'
      }`}>{value}</p>
    </div>
  )
}

// ─── Equity Curve chart ───────────────────────────────────────────────────────

function EquityCurve() {
  const { data, loading } = useFetch(() => api.victoria.getEquityCurve(300))

  if (loading) return <div className="skeleton h-56 rounded-xl" />

  const points = data?.points ?? []
  const trainEnd = data?.train_end ?? 0

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Equity Curve vs BTC</h3>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
          <defs>
            <linearGradient id="omegaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="btcGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.15} />
              <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
          />
          {trainEnd > 0 && (
            <ReferenceLine x={trainEnd} stroke="#475569" strokeDasharray="4 2"
              label={{ value: 'OOS', fill: '#64748b', fontSize: 10 }} />
          )}
          <Area type="monotone" dataKey="btc" stroke="#f59e0b" strokeWidth={1.5} fill="url(#btcGrad)" dot={false} name="BTC" />
          <Area type="monotone" dataKey="omega" stroke="#34d399" strokeWidth={2} fill="url(#omegaGrad)" dot={false} name="Victoria" />
        </AreaChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-emerald-400 inline-block" /> Victoria</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-amber-400 inline-block" /> BTC</span>
        {trainEnd > 0 && <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-slate-500 inline-block border-dashed" /> OOS split</span>}
      </div>
    </div>
  )
}

// ─── Trades table ─────────────────────────────────────────────────────────────

function TradesTable() {
  const [symFilter, setSymFilter] = useState('')
  const [sideFilter, setSideFilter] = useState('')

  const { data, loading } = useFetch(() =>
    api.victoria.getTrades({ sym_filter: symFilter || undefined, side_filter: sideFilter || undefined, limit: 50 })
  )

  const trades = data?.trades ?? []

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      {/* Filters */}
      <div className="px-5 py-4 border-b border-slate-700/50 flex items-center gap-3 flex-wrap">
        <h3 className="text-sm font-semibold text-slate-300 flex-1">Recent Trades</h3>
        <div className="flex items-center gap-1 bg-slate-700 rounded-lg p-0.5">
          {['', 'LONG', 'SHORT'].map((side) => (
            <button
              key={side}
              onClick={() => setSideFilter(side)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                sideFilter === side ? 'bg-slate-600 text-slate-100' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {side || 'All'}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Filter symbol…"
          value={symFilter}
          onChange={(e) => setSymFilter(e.target.value)}
          className="bg-slate-700 border border-slate-600 text-slate-200 text-xs px-3 py-1.5 rounded-lg w-36 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
        />
      </div>

      <table className="w-full" data-testid="trades-table">
        <thead>
          <tr className="border-b border-slate-700/50">
            {['Time', 'Symbol', 'Side', 'Size', 'Entry', 'Exit', 'PnL', 'Duration'].map((h) => (
              <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-slate-700/40">
                  {Array.from({ length: 8 }).map((_, j) => (
                    <td key={j} className="px-4 py-3"><div className="skeleton h-4 w-16" /></td>
                  ))}
                </tr>
              ))
            : trades.map((t, i) => (
                <tr key={i} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                  <td className="px-4 py-3 text-slate-500 text-xs tabular-nums">{t.ts ? new Date(t.ts).toLocaleString() : '—'}</td>
                  <td className="px-4 py-3 text-slate-200 font-mono text-sm">{t.sym}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                      t.side === 'LONG' ? 'bg-emerald-900/40 text-emerald-400' : 'bg-rose-900/40 text-rose-400'
                    }`}>
                      {t.side}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{t.size.toFixed(4)}</td>
                  <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{fmt2(t.entry)}</td>
                  <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{t.exit_price ? fmt2(t.exit_price) : '—'}</td>
                  <td className={`px-4 py-3 tabular-nums text-sm font-medium ${t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {t.pnl >= 0 ? '+' : ''}{usd(t.pnl)}
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{t.duration}</td>
                </tr>
              ))}
          {!loading && trades.length === 0 && (
            <tr>
              <td colSpan={8} className="text-center py-12 text-slate-500 text-sm">No trades found</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── PnL Stats bar ────────────────────────────────────────────────────────────

function PnLStats() {
  const { data: pnl, loading } = useFetch(() => api.victoria.getPnL())

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
      {[
        { label: 'Total PnL', value: pnl ? usd(pnl.total_pnl) : '—', positive: pnl ? pnl.total_pnl >= 0 : undefined },
        { label: 'Unrealised', value: pnl ? usd(pnl.unrealised_pnl) : '—', positive: pnl ? pnl.unrealised_pnl >= 0 : undefined },
        { label: 'Ann Return', value: pnl ? pct(pnl.ann_return) : '—', positive: pnl ? pnl.ann_return >= 0 : undefined },
        { label: 'Sharpe', value: pnl ? fmt2(pnl.sharpe) : '—', positive: pnl ? pnl.sharpe > 0 : undefined },
        { label: 'Max DD', value: pnl ? pct(pnl.max_dd) : '—', positive: pnl ? pnl.max_dd >= 0 : undefined },
        { label: 'Sortino', value: pnl ? fmt2(pnl.sortino) : '—', positive: pnl ? pnl.sortino > 0 : undefined },
        { label: 'Win Rate', value: pnl ? `${(pnl.win_rate * 100).toFixed(1)}%` : '—', positive: pnl ? pnl.win_rate >= 0.5 : undefined },
      ].map(({ label, value, positive }) => (
        <StatCell key={label} label={label} value={loading ? '—' : value} positive={positive} />
      ))}
    </div>
  )
}

// ─── TradingPage ──────────────────────────────────────────────────────────────

export function TradingPage() {
  const { projectId = '' } = useParams<{ projectId: string }>()

  return (
    <div className="space-y-6" data-testid="trading-page">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Trading Overview</h1>
        <p className="text-slate-400 text-sm mt-1">
          <span className="capitalize">{projectId}</span> · live performance metrics
        </p>
      </div>

      {(projectId === 'victoria' || projectId === 'proj_victoria') ? (
        <>
          <PnLStats />
          <EquityCurve />
          <TradesTable />
        </>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
          <p className="text-sm">Trading data not available for project: {projectId}</p>
        </div>
      )}
    </div>
  )
}
