import React, { useState } from 'react'
import { ChevronDown, ChevronUp, Activity } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts'
import { StatusBadge } from '../components/StatusBadge'
import { useFetch } from '../hooks/useFetch'
import { api, type Node } from '../lib/api'

type AutonomyFilter = 'ALL' | 'PICO' | 'SUPERVISED' | 'AUTONOMOUS'
type StatusFilter = 'ALL' | 'active' | 'idle' | 'error'

function Sparkline({ color }: { color: string }) {
  const data = Array.from({ length: 12 }, () => ({ v: 50 + Math.random() * 50 }))
  return (
    <ResponsiveContainer width="100%" height={40}>
      <LineChart data={data}>
        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          itemStyle={{ color }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

function NodeRow({ node }: { node: Node }) {
  const [expanded, setExpanded] = useState(false)

  const sparkColor = node.autonomy_level === 'AUTONOMOUS'
    ? '#34d399'
    : node.autonomy_level === 'SUPERVISED'
    ? '#fbbf24'
    : '#94a3b8'

  return (
    <>
      <tr
        className="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer transition-colors"
        onClick={() => setExpanded((e) => !e)}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-slate-200 font-medium text-sm font-mono">{node.name}</span>
          </div>
        </td>
        <td className="px-4 py-3"><StatusBadge status={node.status} size="sm" /></td>
        <td className="px-4 py-3"><StatusBadge status={node.autonomy_level} size="sm" /></td>
        <td className="px-4 py-3 text-slate-400 text-sm">{node.strategy}</td>
        <td className="px-4 py-3"><StatusBadge status={node.circuit_breaker_state} size="sm" /></td>
        <td className="px-4 py-3 text-slate-500 text-xs tabular-nums">
          {node.last_execution ? new Date(node.last_execution).toLocaleTimeString() : '—'}
        </td>
        <td className="px-4 py-3 text-slate-500">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-slate-700/50 bg-slate-800/60">
          <td colSpan={7} className="px-4 py-4">
            <div className="grid grid-cols-3 gap-6">
              <div>
                <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Avg Duration</p>
                <p className="text-slate-200 text-lg font-bold tabular-nums">
                  {node.performance.avg_duration_ms}
                  <span className="text-slate-500 text-xs ml-1">ms</span>
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Success Rate</p>
                <p className="text-slate-200 text-lg font-bold tabular-nums">
                  {(node.performance.success_rate * 100).toFixed(1)}
                  <span className="text-slate-500 text-xs ml-1">%</span>
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Total Executions</p>
                <p className="text-slate-200 text-lg font-bold tabular-nums">
                  {node.performance.total_executions.toLocaleString()}
                </p>
              </div>
              <div className="col-span-3">
                <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Performance Trend</p>
                <Sparkline color={sparkColor} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export function NodesPage() {
  const { data: nodes, loading } = useFetch(api.getNodes)
  const [autonomyFilter, setAutonomyFilter] = useState<AutonomyFilter>('ALL')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')

  const filtered = (nodes ?? []).filter((n) => {
    if (autonomyFilter !== 'ALL' && n.autonomy_level !== autonomyFilter) return false
    if (statusFilter !== 'ALL' && n.status !== statusFilter) return false
    return true
  })

  const filterBtn = (active: boolean) =>
    `px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
      active ? 'bg-slate-600 text-slate-100' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'
    }`

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Nodes</h1>
          <p className="text-slate-400 text-sm mt-1">{filtered.length} nodes</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 border border-slate-700/50">
          {(['ALL', 'AUTONOMOUS', 'SUPERVISED', 'PICO'] as AutonomyFilter[]).map((f) => (
            <button key={f} className={filterBtn(autonomyFilter === f)} onClick={() => setAutonomyFilter(f)}>
              {f}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 border border-slate-700/50">
          {(['ALL', 'active', 'idle', 'error'] as StatusFilter[]).map((f) => (
            <button key={f} className={filterBtn(statusFilter === f)} onClick={() => setStatusFilter(f)}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50">
              {['Name', 'Status', 'Autonomy', 'Strategy', 'Circuit Breaker', 'Last Exec', ''].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-700/50">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="skeleton h-4 w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              : filtered.map((node) => <NodeRow key={node.id} node={node} />)}
          </tbody>
        </table>
        {!loading && filtered.length === 0 && (
          <div className="text-center py-12 text-slate-500 text-sm">No nodes match filters</div>
        )}
      </div>
    </div>
  )
}
