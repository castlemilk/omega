import React from 'react'
import { Zap, RotateCcw, TrendingUp } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useFetch } from '../hooks/useFetch'
import { api } from '../lib/api'

export function ImprovementPage() {
  const { data: improvements, loading } = useFetch(api.getImprovements)

  const improved = (improvements ?? []).filter((i) => !i.rolled_back).length
  const rolledBack = (improvements ?? []).filter((i) => i.rolled_back).length

  // Per-node aggregation
  const byNode: Record<string, { improved: number; rolledBack: number }> = {}
  for (const imp of improvements ?? []) {
    if (!byNode[imp.node_id]) byNode[imp.node_id] = { improved: 0, rolledBack: 0 }
    if (imp.rolled_back) byNode[imp.node_id].rolledBack++
    else byNode[imp.node_id].improved++
  }

  const nodeChartData = Object.entries(byNode).map(([node, v]) => ({
    node: node.length > 12 ? `${node.slice(0, 12)}…` : node,
    improved: v.improved,
    rolledBack: v.rolledBack,
  }))

  const ratioData = [
    { name: 'Improved', value: improved, color: '#34d399' },
    { name: 'Rolled Back', value: rolledBack, color: '#f87171' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Self-Improvement</h1>
        <p className="text-slate-400 text-sm mt-1">{improvements?.length ?? 0} strategy changes</p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4 text-emerald-400" />
            <p className="text-xs text-slate-500 uppercase tracking-wider">Improvements</p>
          </div>
          <p className="text-3xl font-bold text-emerald-400 tabular-nums">{improved}</p>
        </div>
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <div className="flex items-center gap-2 mb-2">
            <RotateCcw className="w-4 h-4 text-rose-400" />
            <p className="text-xs text-slate-500 uppercase tracking-wider">Rollbacks</p>
          </div>
          <p className="text-3xl font-bold text-rose-400 tabular-nums">{rolledBack}</p>
        </div>
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-sky-400" />
            <p className="text-xs text-slate-500 uppercase tracking-wider">Success Rate</p>
          </div>
          <p className="text-3xl font-bold text-sky-400 tabular-nums">
            {improvements && improvements.length > 0
              ? `${Math.round((improved / improvements.length) * 100)}%`
              : '—'}
          </p>
        </div>
      </div>

      {/* Ratio chart */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Improvement vs Rollback</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={ratioData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {ratioData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Per-Node Activity</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={nodeChartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <XAxis dataKey="node" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Bar dataKey="improved" fill="#34d399" radius={[4, 4, 0, 0]} name="Improved" />
              <Bar dataKey="rolledBack" fill="#f87171" radius={[4, 4, 0, 0]} name="Rolled Back" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Timeline */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
        <h3 className="text-sm font-semibold text-slate-300 mb-4">Strategy Evolution</h3>
        {loading ? (
          <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton h-14 rounded-lg" />)}</div>
        ) : (improvements ?? []).length === 0 ? (
          <div className="text-center py-10 text-slate-500 text-sm">No strategy changes yet</div>
        ) : (
          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {(improvements ?? []).map((imp) => (
              <div
                key={imp.id}
                className={`flex items-center gap-4 p-3 rounded-lg border ${
                  imp.rolled_back
                    ? 'border-rose-700/40 bg-rose-900/20'
                    : 'border-emerald-700/40 bg-emerald-900/20'
                }`}
              >
                {imp.rolled_back ? (
                  <RotateCcw className="w-4 h-4 text-rose-400 shrink-0" />
                ) : (
                  <Zap className="w-4 h-4 text-emerald-400 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-slate-200 text-sm">
                    <span className="font-mono text-xs text-slate-400">{imp.node_id}</span>
                    {' · '}
                    <span className="text-slate-300">{imp.strategy_from}</span>
                    <span className="text-slate-500 mx-2">→</span>
                    <span className="text-slate-100 font-medium">{imp.strategy_to}</span>
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={`text-xs font-mono ${imp.improvement_delta >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {imp.improvement_delta >= 0 ? '+' : ''}{imp.improvement_delta.toFixed(2)}
                    </span>
                    {imp.rolled_back && <span className="text-xs text-rose-400">rolled back</span>}
                  </div>
                </div>
                <span className="text-slate-500 text-xs shrink-0 tabular-nums">
                  {new Date(imp.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
