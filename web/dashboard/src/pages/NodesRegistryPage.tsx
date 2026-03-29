/**
 * NodesRegistryPage — platform-wide node registry view.
 *
 * Shows:
 *  1. Registered node types (NodeCapability enum values)
 *  2. Capability-based routing: which capabilities route to which nodes
 *  3. Node health dashboard with heartbeat indicators
 *  4. Project configurations (from ProjectService)
 */
import React, { useState } from 'react'
import {
  Server, Zap, Shield, Database, TrendingUp, Brain, GitMerge,
  CheckCircle, RefreshCw, Activity, Wifi, WifiOff, AlertCircle,
  LayoutDashboard, Clock, Globe, Cpu,
} from 'lucide-react'
import { useFetch } from '../hooks/useFetch'
import { api, type RegistryNode, type Project } from '../lib/api'

// ─── NodeCapability display map ───────────────────────────────────────────────

const CAPABILITY_META: Record<string, { label: string; icon: React.ElementType; color: string; description: string }> = {
  NODE_CAPABILITY_SIGNAL_RESEARCH:  { label: 'Signal Research',  icon: TrendingUp,     color: 'text-emerald-400', description: 'Generates and evaluates alpha signals from market data' },
  NODE_CAPABILITY_RISK_MANAGEMENT:  { label: 'Risk Management',  icon: Shield,         color: 'text-amber-400',   description: 'Portfolio risk controls and position sizing' },
  NODE_CAPABILITY_DATA_INGESTION:   { label: 'Data Ingestion',   icon: Database,       color: 'text-blue-400',    description: 'Fetches and normalises market and alternative data' },
  NODE_CAPABILITY_STRATEGY:         { label: 'Strategy',         icon: GitMerge,       color: 'text-purple-400',  description: 'Trade decision-making and order generation' },
  NODE_CAPABILITY_VERIFICATION:     { label: 'Verification',     icon: CheckCircle,    color: 'text-cyan-400',    description: 'Validates outputs and enforces correctness gates' },
  NODE_CAPABILITY_ADVERSARIAL:      { label: 'Adversarial',      icon: Zap,            color: 'text-red-400',     description: 'Stress-tests nodes via debate and adversarial probing' },
  NODE_CAPABILITY_MEMORY:           { label: 'Memory',           icon: Brain,          color: 'text-indigo-400',  description: 'Episodic and semantic memory persistence' },
  NODE_CAPABILITY_IMPROVEMENT:      { label: 'Improvement',      icon: RefreshCw,      color: 'text-pink-400',    description: 'TPE-driven node self-improvement loops' },
}

const ALL_CAPABILITIES = Object.keys(CAPABILITY_META)

// ─── Helpers ─────────────────────────────────────────────────────────────────

function nodeStatusIcon(status: string) {
  const s = status.toUpperCase()
  if (s.includes('OFFLINE'))  return <WifiOff className="w-3 h-3 text-red-400" />
  if (s.includes('DEGRADED')) return <AlertCircle className="w-3 h-3 text-amber-400" />
  if (s.includes('STARTING')) return <RefreshCw className="w-3 h-3 text-blue-400 animate-spin" />
  return <Wifi className="w-3 h-3 text-emerald-400" />
}

function nodeStatusLabel(status: string): string {
  return status.replace(/^NODE_STATUS_/, '').toLowerCase()
}

function healthDot(score: number) {
  const color = score >= 0.8 ? 'bg-emerald-500' : score >= 0.5 ? 'bg-amber-500' : 'bg-red-500'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}

function capLabel(cap: string): string {
  return cap.replace(/^NODE_CAPABILITY_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ─── Section: Capability Routing ─────────────────────────────────────────────

function CapabilityRoutingSection({ nodes }: { nodes: RegistryNode[] }) {
  // Build map: capability → nodes that serve it
  const routing = new Map<string, RegistryNode[]>()
  for (const cap of ALL_CAPABILITIES) {
    routing.set(cap, [])
  }
  for (const node of nodes) {
    for (const cap of node.capabilities ?? []) {
      if (routing.has(cap)) {
        routing.get(cap)!.push(node)
      }
    }
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50 flex items-center gap-2">
        <GitMerge className="w-4 h-4 text-emerald-400" />
        <h2 className="text-slate-100 font-semibold text-sm">Capability Routing</h2>
        <span className="ml-auto text-xs text-slate-500">which capabilities route to which nodes</span>
      </div>
      <div className="divide-y divide-slate-700/40">
        {ALL_CAPABILITIES.map(cap => {
          const meta = CAPABILITY_META[cap]
          const Icon = meta.icon
          const capNodes = routing.get(cap) ?? []
          const hasNodes = capNodes.length > 0

          return (
            <div key={cap} className={`px-5 py-3 flex items-center gap-4 ${!hasNodes ? 'opacity-50' : ''}`}>
              <div className="flex items-center gap-2 w-44 shrink-0">
                <Icon className={`w-4 h-4 ${meta.color} shrink-0`} />
                <span className="text-slate-300 text-sm font-medium">{meta.label}</span>
              </div>
              <span className="text-slate-600 text-xs w-32 shrink-0 hidden lg:block">{meta.description}</span>
              <div className="flex-1 flex items-center gap-2 flex-wrap">
                {hasNodes ? (
                  capNodes.map(n => (
                    <span
                      key={n.id}
                      className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-slate-700/60 text-slate-300 text-xs rounded border border-slate-600/40"
                    >
                      {nodeStatusIcon(n.status)}
                      {n.name || n.id}
                    </span>
                  ))
                ) : (
                  <span className="text-slate-600 text-xs italic">no nodes registered</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Section: Node Health Dashboard ──────────────────────────────────────────

function NodeHealthSection({ nodes }: { nodes: RegistryNode[] }) {
  const healthy  = nodes.filter(n => n.status.toUpperCase().includes('HEALTHY')).length
  const degraded = nodes.filter(n => n.status.toUpperCase().includes('DEGRADED')).length
  const offline  = nodes.filter(n => n.status.toUpperCase().includes('OFFLINE')).length

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Healthy',  count: healthy,  color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
          { label: 'Degraded', count: degraded, color: 'text-amber-400',   bg: 'bg-amber-500/10 border-amber-500/20' },
          { label: 'Offline',  count: offline,  color: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/20' },
        ].map(({ label, count, color, bg }) => (
          <div key={label} className={`rounded-xl border p-4 ${bg}`}>
            <p className={`text-2xl font-bold tabular-nums ${color}`}>{count}</p>
            <p className={`text-sm ${color} opacity-75`}>{label}</p>
          </div>
        ))}
      </div>

      {/* Per-node health grid */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-700/50 flex items-center gap-2">
          <Activity className="w-4 h-4 text-emerald-400" />
          <h2 className="text-slate-100 font-semibold text-sm">Node Health</h2>
          <span className="ml-auto text-xs text-slate-500">live heartbeat states</span>
        </div>
        {nodes.length === 0 ? (
          <div className="px-5 py-8 text-center text-slate-500 text-sm">
            No nodes registered yet — start a node to see its health here
          </div>
        ) : (
          <div className="divide-y divide-slate-700/40">
            {nodes.map(node => {
              const hb = node.last_heartbeat
                ? new Date(node.last_heartbeat).toLocaleTimeString()
                : '—'
              const pct = Math.round((node.health_score ?? 0) * 100)

              return (
                <div key={node.id} className="px-5 py-3 flex items-center gap-4">
                  <div className="flex items-center gap-2 w-48 shrink-0">
                    {nodeStatusIcon(node.status)}
                    <span className="text-slate-300 text-sm font-mono">{node.name || node.id}</span>
                  </div>

                  <div className="flex items-center gap-1.5 w-20 shrink-0">
                    {healthDot(node.health_score ?? 0)}
                    <span className="text-xs tabular-nums text-slate-400">{pct}%</span>
                  </div>

                  <span className={`text-xs w-20 shrink-0 ${
                    node.status.includes('HEALTHY')  ? 'text-emerald-400' :
                    node.status.includes('DEGRADED') ? 'text-amber-400'   :
                    node.status.includes('OFFLINE')  ? 'text-red-400'     : 'text-slate-400'
                  }`}>
                    {nodeStatusLabel(node.status)}
                  </span>

                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock className="w-3 h-3" />
                    <span className="tabular-nums">{hb}</span>
                  </div>

                  <div className="flex items-center gap-1 text-xs text-slate-500 ml-auto">
                    <Globe className="w-3 h-3" />
                    <span>{node.language || '—'}</span>
                    {node.address && (
                      <>
                        <span className="mx-1 text-slate-700">·</span>
                        <Cpu className="w-3 h-3" />
                        <span className="font-mono">{node.address.replace(/^https?:\/\//, '')}</span>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Section: Project Configs ─────────────────────────────────────────────────

function ProjectConfigsSection({ projects }: { projects: Project[] }) {
  if (projects.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-8 text-center text-slate-500 text-sm">
        No projects loaded
      </div>
    )
  }

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50 flex items-center gap-2">
        <LayoutDashboard className="w-4 h-4 text-emerald-400" />
        <h2 className="text-slate-100 font-semibold text-sm">Project Configs</h2>
        <span className="ml-auto text-xs text-slate-500">{projects.length} loaded from projects/</span>
      </div>
      <div className="divide-y divide-slate-700/40">
        {projects.map(p => (
          <div key={p.project_id} className="px-5 py-4">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-200 font-medium text-sm">{p.name}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    p.status === 'active'   ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                    p.status === 'paused'   ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                    'bg-slate-700/50 text-slate-400 border border-slate-600/30'
                  }`}>
                    {p.status}
                  </span>
                </div>
                {p.description && (
                  <p className="text-slate-500 text-xs mt-0.5">{p.description}</p>
                )}
              </div>
              <div className="text-right text-xs text-slate-500 shrink-0 ml-4">
                <p>{p.domain || '—'}</p>
                <p className="text-slate-600">{p.node_ids?.length ?? 0} nodes</p>
              </div>
            </div>

            {p.pipeline_config && p.pipeline_config.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-slate-600 mb-2 uppercase tracking-wider">Pipeline</p>
                <div className="flex items-center gap-1 flex-wrap">
                  {p.pipeline_config
                    .sort((a, b) => a.order - b.order)
                    .map((step, i) => (
                      <React.Fragment key={step.step_id}>
                        {i > 0 && <span className="text-slate-700 text-xs">→</span>}
                        <span className="px-2 py-0.5 bg-slate-700/60 text-slate-400 text-xs rounded border border-slate-600/30">
                          {step.name || step.node_type}
                        </span>
                      </React.Fragment>
                    ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── NodesRegistryPage ────────────────────────────────────────────────────────

export function NodesRegistryPage() {
  const { data: nodesData, loading: nodesLoading } = useFetch(api.node.listNodes)
  const { data: projectsData, loading: projLoading } = useFetch(api.listProjects)

  const [activeTab, setActiveTab] = useState<'capabilities' | 'routing' | 'health' | 'projects'>('health')

  const nodes = nodesData?.nodes ?? []
  const projects = projectsData?.projects ?? []

  const tabs: Array<{ id: typeof activeTab; label: string; icon: React.ElementType }> = [
    { id: 'health',       label: 'Health',       icon: Activity },
    { id: 'routing',      label: 'Routing',      icon: GitMerge },
    { id: 'capabilities', label: 'Capabilities', icon: Zap },
    { id: 'projects',     label: 'Projects',     icon: LayoutDashboard },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
          <Server className="w-6 h-6 text-emerald-400" />
          Node Registry
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          {nodesLoading
            ? 'Loading registry…'
            : `${nodes.length} registered node${nodes.length !== 1 ? 's' : ''} · ${projects.length} project config${projects.length !== 1 ? 's' : ''}`}
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 border border-slate-700/50 w-fit">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              activeTab === id
                ? 'bg-slate-700 text-slate-100'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'health' && (
        nodesLoading
          ? <div className="text-slate-500 text-sm">Loading…</div>
          : <NodeHealthSection nodes={nodes} />
      )}

      {activeTab === 'routing' && (
        nodesLoading
          ? <div className="text-slate-500 text-sm">Loading…</div>
          : <CapabilityRoutingSection nodes={nodes} />
      )}

      {activeTab === 'capabilities' && (
        <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-700/50 flex items-center gap-2">
            <Zap className="w-4 h-4 text-emerald-400" />
            <h2 className="text-slate-100 font-semibold text-sm">Node Capability Types</h2>
            <span className="ml-auto text-xs text-slate-500">all capabilities from NodeCapability enum</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px bg-slate-700/30">
            {ALL_CAPABILITIES.map(cap => {
              const meta = CAPABILITY_META[cap]
              const Icon = meta.icon
              const count = nodes.filter(n => (n.capabilities ?? []).includes(cap)).length

              return (
                <div key={cap} className="bg-slate-800 px-5 py-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Icon className={`w-4 h-4 ${meta.color}`} />
                    <span className="text-slate-200 font-medium text-sm">{meta.label}</span>
                    <span className={`ml-auto text-xs tabular-nums font-medium ${count > 0 ? 'text-emerald-400' : 'text-slate-600'}`}>
                      {count} node{count !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <p className="text-slate-500 text-xs">{meta.description}</p>
                  <p className="text-slate-700 text-xs mt-2 font-mono">{cap}</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {activeTab === 'projects' && (
        projLoading
          ? <div className="text-slate-500 text-sm">Loading…</div>
          : <ProjectConfigsSection projects={projects} />
      )}
    </div>
  )
}
