import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronUp, Clock, Shield, AlertTriangle, Zap } from 'lucide-react'
import { StatusBadge } from '../components/StatusBadge'
import { useFetch } from '../hooks/useFetch'
import { api, type Cycle } from '../lib/api'

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function CycleRow({ cycle, projectId }: { cycle: Cycle; projectId: string }) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)

  const started = new Date(cycle.started_at)
  const ended = cycle.ended_at ? new Date(cycle.ended_at) : null

  return (
    <>
      <div
        className="bg-slate-800 rounded-xl border border-slate-700/50 p-4 hover:border-slate-600 cursor-pointer transition-colors"
        onClick={() => navigate(`/projects/${projectId}/cycles/${encodeURIComponent(cycle.id)}`)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <StatusBadge status={cycle.status} size="sm" />
            <div>
              <p className="text-slate-200 text-sm font-medium font-mono">{cycle.id}</p>
              <p className="text-slate-500 text-xs mt-0.5">{started.toLocaleString()}</p>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-center">
              <p className="text-slate-400 text-xs mb-1">Duration</p>
              <p className="text-slate-200 text-sm font-mono font-medium">{formatDuration(cycle.duration_ms)}</p>
            </div>
            <div className="text-center">
              <p className="text-slate-400 text-xs mb-1">Nodes</p>
              <p className="text-sky-400 text-sm font-mono font-medium">{cycle.nodes_executed}</p>
            </div>
            <div className="text-center">
              <p className="text-slate-400 text-xs mb-1">Violations</p>
              <p className={`text-sm font-mono font-medium ${cycle.safety_violations > 0 ? 'text-rose-400' : 'text-slate-500'}`}>
                {cycle.safety_violations}
              </p>
            </div>
            <div className="text-center">
              <p className="text-slate-400 text-xs mb-1">Alerts</p>
              <p className={`text-sm font-mono font-medium ${cycle.adversarial_alerts > 0 ? 'text-amber-400' : 'text-slate-500'}`}>
                {cycle.adversarial_alerts}
              </p>
            </div>
            <div className="text-center">
              <p className="text-slate-400 text-xs mb-1">Improvements</p>
              <p className={`text-sm font-mono font-medium ${cycle.improvements > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                {cycle.improvements}
              </p>
            </div>
            {expanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
          </div>
        </div>

        {expanded && (
          <div className="mt-4 pt-4 border-t border-slate-700/50 grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="flex items-center gap-3 bg-slate-700/40 rounded-lg p-3">
              <Clock className="w-4 h-4 text-sky-400" />
              <div>
                <p className="text-xs text-slate-500">Started</p>
                <p className="text-sm text-slate-200">{started.toLocaleTimeString()}</p>
              </div>
            </div>
            {ended && (
              <div className="flex items-center gap-3 bg-slate-700/40 rounded-lg p-3">
                <Clock className="w-4 h-4 text-slate-400" />
                <div>
                  <p className="text-xs text-slate-500">Ended</p>
                  <p className="text-sm text-slate-200">{ended.toLocaleTimeString()}</p>
                </div>
              </div>
            )}
            {cycle.safety_violations > 0 && (
              <div className="flex items-center gap-3 bg-rose-900/30 rounded-lg p-3">
                <Shield className="w-4 h-4 text-rose-400" />
                <div>
                  <p className="text-xs text-rose-500">Safety Violations</p>
                  <p className="text-sm text-rose-300 font-bold">{cycle.safety_violations}</p>
                </div>
              </div>
            )}
            {cycle.adversarial_alerts > 0 && (
              <div className="flex items-center gap-3 bg-amber-900/30 rounded-lg p-3">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <div>
                  <p className="text-xs text-amber-500">Adversarial Alerts</p>
                  <p className="text-sm text-amber-300 font-bold">{cycle.adversarial_alerts}</p>
                </div>
              </div>
            )}
            {cycle.improvements > 0 && (
              <div className="flex items-center gap-3 bg-emerald-900/30 rounded-lg p-3">
                <Zap className="w-4 h-4 text-emerald-400" />
                <div>
                  <p className="text-xs text-emerald-500">Improvements</p>
                  <p className="text-sm text-emerald-300 font-bold">{cycle.improvements}</p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

export function CyclesPage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const { data: cycles, loading } = useFetch(api.getCycles)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Cycle History</h1>
        <p className="text-slate-400 text-sm mt-1">{cycles?.length ?? 0} cycles</p>
      </div>

      {/* Summary bar */}
      {cycles && cycles.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Total Cycles', value: cycles.length, color: 'text-slate-200' },
            { label: 'Safety Violations', value: cycles.reduce((a, c) => a + c.safety_violations, 0), color: 'text-rose-400' },
            { label: 'Adversarial Alerts', value: cycles.reduce((a, c) => a + c.adversarial_alerts, 0), color: 'text-amber-400' },
            { label: 'Improvements', value: cycles.reduce((a, c) => a + c.improvements, 0), color: 'text-emerald-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4">
              <p className="text-slate-500 text-xs uppercase tracking-wider mb-1">{label}</p>
              <p className={`text-2xl font-bold tabular-nums ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-20 rounded-xl" />
            ))
          : (cycles ?? []).map((cycle) => <CycleRow key={cycle.id} cycle={cycle} projectId={projectId} />)}
        {!loading && (!cycles || cycles.length === 0) && (
          <div className="text-center py-16 text-slate-500 text-sm">No cycles recorded yet</div>
        )}
      </div>
    </div>
  )
}
