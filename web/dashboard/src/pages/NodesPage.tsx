import React, { useState } from 'react'
import { Activity, ChevronDown, ChevronUp, Server, Cpu, Globe, Clock, Wifi, WifiOff, AlertCircle } from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api, type RegistryNode } from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function capabilityLabel(cap: string): string {
  return cap
    .replace(/^NODE_CAPABILITY_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

function statusColor(status: string): string {
  const s = status.toUpperCase()
  if (s.includes('HEALTHY')) return 'text-emerald-400'
  if (s.includes('DEGRADED')) return 'text-amber-400'
  if (s.includes('OFFLINE')) return 'text-red-400'
  return 'text-slate-400'
}

function statusBg(status: string): string {
  const s = status.toUpperCase()
  if (s.includes('HEALTHY')) return 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
  if (s.includes('DEGRADED')) return 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
  if (s.includes('OFFLINE')) return 'bg-red-500/10 text-red-400 border border-red-500/20'
  if (s.includes('STARTING')) return 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
  return 'bg-slate-700/50 text-slate-400 border border-slate-600/30'
}

function healthBar(score: number) {
  const pct = Math.round(score * 100)
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-400">{pct}%</span>
    </div>
  )
}

function StatusIcon({ status }: { status: string }) {
  const s = status.toUpperCase()
  if (s.includes('OFFLINE')) return <WifiOff className="w-3.5 h-3.5 text-red-400" />
  if (s.includes('DEGRADED')) return <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
  return <Wifi className="w-3.5 h-3.5 text-emerald-400" />
}

// ─── NodeRow ─────────────────────────────────────────────────────────────────

function NodeRow({ node }: { node: RegistryNode }) {
  const [expanded, setExpanded] = useState(false)

  const shortStatus = node.status
    .replace(/^NODE_STATUS_/, '')
    .toLowerCase()

  const lastHB = node.last_heartbeat
    ? new Date(node.last_heartbeat).toLocaleTimeString()
    : '—'

  return (
    <>
      <tr
        className="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        {/* Name */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <StatusIcon status={node.status} />
            <span className="text-slate-200 font-medium text-sm font-mono">{node.name || node.id}</span>
          </div>
        </td>

        {/* Status */}
        <td className="px-4 py-3">
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusBg(node.status)}`}>
            {shortStatus || 'unknown'}
          </span>
        </td>

        {/* Health */}
        <td className="px-4 py-3">
          {node.health_score > 0 ? healthBar(node.health_score) : <span className="text-slate-500 text-xs">—</span>}
        </td>

        {/* Capabilities */}
        <td className="px-4 py-3">
          <div className="flex flex-wrap gap-1">
            {(node.capabilities ?? []).slice(0, 3).map(c => (
              <span key={c} className="px-1.5 py-0.5 bg-slate-700/60 text-slate-300 text-xs rounded border border-slate-600/40">
                {capabilityLabel(c)}
              </span>
            ))}
            {(node.capabilities ?? []).length > 3 && (
              <span className="text-slate-500 text-xs">+{node.capabilities.length - 3}</span>
            )}
          </div>
        </td>

        {/* Language */}
        <td className="px-4 py-3">
          <span className="text-slate-400 text-sm">{node.language || '—'}</span>
        </td>

        {/* Last heartbeat */}
        <td className="px-4 py-3 text-slate-500 text-xs tabular-nums">{lastHB}</td>

        {/* Expand chevron */}
        <td className="px-4 py-3 text-slate-500">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </td>
      </tr>

      {/* Expanded detail */}
      {expanded && (
        <tr className="border-b border-slate-700/50 bg-slate-800/60">
          <td colSpan={7} className="px-4 py-4">
            <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
              <div>
                <p className="text-xs text-slate-500 mb-1 uppercase tracking-wider flex items-center gap-1">
                  <Server className="w-3 h-3" /> Address
                </p>
                <p className="text-slate-300 text-sm font-mono break-all">{node.address || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1 uppercase tracking-wider flex items-center gap-1">
                  <Cpu className="w-3 h-3" /> Version
                </p>
                <p className="text-slate-300 text-sm font-mono">{node.version || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1 uppercase tracking-wider flex items-center gap-1">
                  <Globe className="w-3 h-3" /> Language
                </p>
                <p className="text-slate-300 text-sm">{node.language || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1 uppercase tracking-wider flex items-center gap-1">
                  <Clock className="w-3 h-3" /> Registered
                </p>
                <p className="text-slate-300 text-sm">
                  {node.registered_at ? new Date(node.registered_at).toLocaleString() : '—'}
                </p>
              </div>

              {(node.capabilities ?? []).length > 0 && (
                <div className="col-span-2 md:col-span-4">
                  <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">All Capabilities</p>
                  <div className="flex flex-wrap gap-1.5">
                    {node.capabilities.map(c => (
                      <span key={c} className="px-2 py-1 bg-slate-700/60 text-slate-300 text-xs rounded border border-slate-600/40">
                        {capabilityLabel(c)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ─── NodesPage ────────────────────────────────────────────────────────────────

type StatusFilter = 'ALL' | 'healthy' | 'degraded' | 'offline'

export function NodesPage() {
  const { data, loading, error } = useFetch(api.node.listNodes)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [capFilter, setCapFilter] = useState('')

  const nodes = data?.nodes ?? []

  const filtered = nodes.filter(n => {
    if (statusFilter !== 'ALL') {
      const s = n.status.toUpperCase()
      if (statusFilter === 'healthy' && !s.includes('HEALTHY')) return false
      if (statusFilter === 'degraded' && !s.includes('DEGRADED')) return false
      if (statusFilter === 'offline' && !s.includes('OFFLINE')) return false
    }
    if (capFilter) {
      const label = capFilter.toUpperCase()
      if (!(n.capabilities ?? []).some(c => c.toUpperCase().includes(label))) return false
    }
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
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <Activity className="w-6 h-6 text-emerald-400" />
            Nodes
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            {loading ? 'Loading…' : `${filtered.length} registered nodes`}
            {error && <span className="text-amber-400 ml-2">Registry unavailable — {error}</span>}
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 border border-slate-700/50">
          {(['ALL', 'healthy', 'degraded', 'offline'] as StatusFilter[]).map(f => (
            <button key={f} className={filterBtn(statusFilter === f)} onClick={() => setStatusFilter(f)}>
              {f}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Filter by capability…"
          value={capFilter}
          onChange={e => setCapFilter(e.target.value)}
          className="px-3 py-1.5 bg-slate-800 border border-slate-700/50 rounded-lg text-xs text-slate-300 placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 w-48"
        />
      </div>

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50">
              {['Name', 'Status', 'Health', 'Capabilities', 'Language', 'Last Heartbeat', ''].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-700/50">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-slate-700/50 rounded animate-pulse w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              : filtered.map(node => <NodeRow key={node.id} node={node} />)}
          </tbody>
        </table>

        {!loading && filtered.length === 0 && (
          <div className="text-center py-12 text-slate-500 text-sm">
            {nodes.length === 0
              ? 'No nodes registered — start a node to see it here'
              : 'No nodes match filters'}
          </div>
        )}
      </div>
    </div>
  )
}
