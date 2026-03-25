import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Briefcase, TrendingUp, TrendingDown } from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api, type Position } from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function usd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(v)
}

function pct(v: number) {
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}

// ─── Position row ─────────────────────────────────────────────────────────────

function PositionRow({ pos }: { pos: Position }) {
  const isLong = pos.side === 'LONG'

  return (
    <tr
      className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors"
      data-testid={`position-row-${pos.sym}`}
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {isLong
            ? <TrendingUp className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            : <TrendingDown className="w-3.5 h-3.5 text-rose-400 shrink-0" />
          }
          <span className="text-slate-200 font-mono text-sm font-medium">{pos.sym}</span>
        </div>
      </td>
      <td className="px-4 py-3">
        <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
          isLong ? 'bg-emerald-900/40 text-emerald-400' : 'bg-rose-900/40 text-rose-400'
        }`}>
          {pos.side}
        </span>
      </td>
      <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{pos.size.toFixed(4)}</td>
      <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{usd(pos.entry)}</td>
      <td className="px-4 py-3 text-slate-300 tabular-nums text-sm">{usd(pos.mark)}</td>
      <td className={`px-4 py-3 tabular-nums text-sm font-medium ${pos.upnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
        {pos.upnl >= 0 ? '+' : ''}{usd(pos.upnl)}
      </td>
      <td className={`px-4 py-3 tabular-nums text-sm ${pos.pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
        {pct(pos.pct)}
      </td>
      <td className="px-4 py-3 text-slate-400 tabular-nums text-sm">{usd(pos.notional)}</td>
      <td className="px-4 py-3 text-slate-400 tabular-nums text-sm">{pos.leverage.toFixed(1)}x</td>
      <td className="px-4 py-3 text-slate-500 tabular-nums text-xs">{usd(pos.var95)}</td>
    </tr>
  )
}

// ─── PositionsPage ────────────────────────────────────────────────────────────

export function PositionsPage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const { data, loading } = useFetch(() => api.victoria.getPositions(), 10000)

  const positions = data?.positions ?? []

  const totalUpnl = positions.reduce((sum, p) => sum + p.upnl, 0)
  const totalNotional = positions.reduce((sum, p) => sum + p.notional, 0)
  const longs = positions.filter(p => p.side === 'LONG')
  const shorts = positions.filter(p => p.side === 'SHORT')

  return (
    <div className="space-y-6" data-testid="positions-page">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Positions</h1>
        <p className="text-slate-400 text-sm mt-1">
          <span className="capitalize">{projectId}</span> · open positions
        </p>
      </div>

      {/* Summary bar */}
      {positions.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Open Positions', value: positions.length.toString() },
            {
              label: 'Total uPnL',
              value: (totalUpnl >= 0 ? '+' : '') + usd(totalUpnl),
              positive: totalUpnl >= 0,
            },
            { label: 'Long / Short', value: `${longs.length} / ${shorts.length}` },
            { label: 'Notional', value: usd(totalNotional) },
          ].map(({ label, value, positive }) => (
            <div key={label} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
              <p className="text-slate-500 text-xs uppercase tracking-wider mb-2">{label}</p>
              <p className={`text-lg font-bold tabular-nums ${
                positive === undefined ? 'text-slate-100' :
                positive ? 'text-emerald-400' : 'text-rose-400'
              }`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50">
              {['Symbol', 'Side', 'Size', 'Entry', 'Mark', 'uPnL', 'Chg%', 'Notional', 'Leverage', 'VaR 95'].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-700/40">
                    {Array.from({ length: 10 }).map((_, j) => (
                      <td key={j} className="px-4 py-3"><div className="skeleton h-4 w-16" /></td>
                    ))}
                  </tr>
                ))
              : positions.map((p) => <PositionRow key={p.sym} pos={p} />)}
          </tbody>
        </table>
        {!loading && positions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500 gap-3">
            <Briefcase className="w-8 h-8 text-slate-600" />
            <p className="text-sm">No open positions</p>
          </div>
        )}
      </div>
    </div>
  )
}
