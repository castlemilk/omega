import React from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, Server, RefreshCw, CheckCircle, AlertTriangle, XCircle,
  ArrowRight, Layers, TrendingUp,
} from 'lucide-react'
import { useProjects } from '../context/ProjectContext'
import { useFetch } from '../hooks/useFetch'
import { useSSE } from '../hooks/useSSE'
import { api } from '../lib/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 24) return `${Math.floor(h / 24)}d ${h % 24}h`
  return `${h}h ${m}m`
}

const statusIcon: Record<string, React.ElementType> = {
  healthy: CheckCircle,
  degraded: AlertTriangle,
  critical: XCircle,
}

const statusColor: Record<string, string> = {
  healthy: 'text-emerald-400',
  degraded: 'text-amber-400',
  critical: 'text-rose-400',
}

// ─── MetricTile ───────────────────────────────────────────────────────────────

function MetricTile({
  label, value, sub, icon: Icon, accent = 'emerald',
}: {
  label: string; value: React.ReactNode; sub: string;
  icon: React.ElementType; accent?: 'emerald' | 'sky' | 'amber' | 'rose'
}) {
  const colors = {
    emerald: 'text-emerald-400 bg-emerald-500/10',
    sky:     'text-sky-400 bg-sky-500/10',
    amber:   'text-amber-400 bg-amber-500/10',
    rose:    'text-rose-400 bg-rose-500/10',
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
      <p className="text-slate-500 text-xs mt-1">{sub}</p>
    </div>
  )
}

// ─── ProjectCard ─────────────────────────────────────────────────────────────

interface Project {
  project_id: string
  name: string
  description: string
  status: string
  domain: string
  autonomy_level: string
  node_ids: string[]
  pipeline_config: Array<{ name: string }>
}

function ProjectCard({ project }: { project: Project }) {
  const statusColors: Record<string, string> = {
    active:   'bg-emerald-500/20 text-emerald-300 border-emerald-700/40',
    paused:   'bg-amber-500/20 text-amber-300 border-amber-700/40',
    archived: 'bg-slate-600/20 text-slate-400 border-slate-600/40',
  }
  const sc = statusColors[project.status] ?? statusColors.archived
  const domainLabels: Record<string, string> = {
    crypto_quant: 'Crypto Quant',
    macro_research: 'Macro Research',
    options_arb: 'Options Arb',
    custom: 'Custom',
  }

  return (
    <Link
      to={`/projects/${project.project_id}`}
      className="group block bg-slate-800 rounded-xl border border-slate-700/50 hover:border-slate-600 transition-colors p-5"
      data-testid={`project-card-${project.project_id}`}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-slate-100 font-semibold text-base">{project.name}</h3>
          <p className="text-slate-500 text-xs mt-0.5">
            {domainLabels[project.domain] ?? project.domain}
          </p>
        </div>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${sc}`}>
          {project.status}
        </span>
      </div>

      {project.description && (
        <p className="text-slate-400 text-sm mb-4 line-clamp-2">{project.description}</p>
      )}

      <div className="flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Server className="w-3.5 h-3.5" />
            {project.node_ids.length} nodes
          </span>
          <span className="flex items-center gap-1">
            <RefreshCw className="w-3.5 h-3.5" />
            {project.pipeline_config.length} steps
          </span>
        </div>
        <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-emerald-400 transition-colors" />
      </div>
    </Link>
  )
}

// ─── GlobalOverview ───────────────────────────────────────────────────────────

export function GlobalOverview() {
  const { projects } = useProjects()
  const { data: status, loading } = useFetch(api.getStatus)
  const { events, connected } = useSSE('/api/v1/dashboard/events/stream')

  const totalAutonomy = status
    ? Object.values(status.autonomy_distribution).reduce((a, b) => a + b, 0)
    : 0
  const StatusIcon = statusIcon[status?.status ?? 'healthy'] ?? CheckCircle
  const statusCls = statusColor[status?.status ?? 'healthy'] ?? 'text-emerald-400'

  return (
    <div className="space-y-8" data-testid="global-overview">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Platform Overview</h1>
          <p className="text-slate-400 text-sm mt-1">
            {projects.length} project{projects.length !== 1 ? 's' : ''} · Omega execution engine
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
            {connected ? 'Live' : 'Reconnecting…'}
          </div>
          {status && (
            <div className={`flex items-center gap-1.5 text-sm font-medium ${statusCls}`}>
              <StatusIcon className="w-4 h-4" />
              {status.status}
            </div>
          )}
        </div>
      </div>

      {/* ── System metrics ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="system-metrics">
        <MetricTile
          label="Total Nodes"
          value={loading ? '—' : (status?.total_nodes ?? 0)}
          sub="registered"
          icon={Server}
          accent="sky"
        />
        <MetricTile
          label="Active Cycles"
          value={loading ? '—' : (status?.active_cycles ?? 0)}
          sub="running"
          icon={RefreshCw}
          accent="emerald"
        />
        <MetricTile
          label="System Uptime"
          value={loading ? '—' : (status ? formatUptime(status.uptime_seconds) : '—')}
          sub="continuous"
          icon={Activity}
          accent="amber"
        />
        <MetricTile
          label="Autonomous Nodes"
          value={
            loading
              ? '—'
              : totalAutonomy > 0
              ? `${Math.round(((status?.autonomy_distribution?.AUTONOMOUS ?? 0) / totalAutonomy) * 100)}%`
              : '—'
          }
          sub="of fleet"
          icon={TrendingUp}
          accent="emerald"
        />
      </div>

      {/* ── Projects ── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            <Layers className="w-5 h-5 text-emerald-400" />
            Projects
          </h2>
        </div>
        {projects.length === 0 ? (
          <div className="text-center py-16 text-slate-500 text-sm bg-slate-800 rounded-xl border border-slate-700/50">
            No projects registered. Check backend connection.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4" data-testid="project-cards">
            {projects.map((p) => (
              <ProjectCard key={p.project_id} project={p} />
            ))}
          </div>
        )}
      </div>

      {/* ── Autonomy distribution ── */}
      {status && totalAutonomy > 0 && (
        <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Autonomy Distribution</h3>
          <div className="flex gap-3">
            {Object.entries(status.autonomy_distribution).map(([level, count]) => {
              const pct = totalAutonomy > 0 ? Math.round((count / totalAutonomy) * 100) : 0
              const colors: Record<string, string> = {
                AUTONOMOUS: 'bg-emerald-500',
                SUPERVISED: 'bg-amber-500',
                PICO: 'bg-slate-500',
              }
              return (
                <div key={level} className="flex-1">
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-slate-400">{level}</span>
                    <span className="text-slate-300 font-mono">{count}</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${colors[level] ?? 'bg-slate-500'} rounded-full transition-all duration-700`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <p className="text-slate-500 text-xs mt-1 text-right">{pct}%</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Recent events ── */}
      <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-300">Recent Events</h3>
          <span className="text-xs text-slate-500">{events.length} events</span>
        </div>
        {events.length === 0 ? (
          <p className="text-slate-500 text-sm text-center py-8">No events yet. Waiting for SSE stream…</p>
        ) : (
          <div className="space-y-2">
            {events.slice(0, 10).map((ev, i) => (
              <div key={i} className="flex items-start gap-3 text-sm">
                <span className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                  ev.severity === 'error' ? 'bg-rose-400' :
                  ev.severity === 'warning' ? 'bg-amber-400' : 'bg-emerald-400'
                }`} />
                <span className="text-slate-500 tabular-nums text-xs shrink-0 mt-0.5 w-16">
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-slate-300">{ev.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
