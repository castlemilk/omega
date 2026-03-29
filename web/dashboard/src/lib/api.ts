/**
 * Connect-RPC JSON client layer.
 *
 * Uses the Connect-RPC unary JSON protocol:
 *   POST /<package>.<Service>/<Method>
 *   Content-Type: application/json
 *   Connect-Protocol-Version: 1
 *   Body: JSON request message
 *
 * All paths proxy through Vite's /api → localhost:8080, but Connect-RPC
 * mounts at the package root. We call the real backend paths directly.
 */

// ─── Base RPC ────────────────────────────────────────────────────────────────

const RPC_BASE = ''  // relative, proxied by Vite to localhost:8080

async function rpc<T>(service: string, method: string, body: unknown = {}): Promise<T> {
  const res = await fetch(`${RPC_BASE}/omega.v1.${service}/${method}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Connect-Protocol-Version': '1',
    },
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`RPC ${service}/${method} failed: ${res.status} ${text}`)
  }

  return res.json() as Promise<T>
}

// ─── Legacy REST client (dashboard helper endpoints) ─────────────────────────
// The Go API also serves REST at /api/v1/dashboard for the existing dashboard
// pages. Keep this for pages that haven't been migrated yet.

const REST_BASE = '/api/v1/dashboard'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${REST_BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ─── Types: OrchestratorService ──────────────────────────────────────────────

export interface SystemHealth {
  status: string          // "healthy" | "degraded" | "critical"
  total_nodes: number
  active_cycles: number
  uptime_seconds: number
  autonomy_distribution: Record<string, number>
}

export interface Node {
  id: string
  name: string
  autonomy_level: 'PICO' | 'SUPERVISED' | 'AUTONOMOUS'
  strategy: string
  circuit_breaker_state: 'CLOSED' | 'OPEN' | 'HALF_OPEN'
  last_execution: string
  status: 'active' | 'idle' | 'error'
  performance: {
    avg_duration_ms: number
    success_rate: number
    total_executions: number
  }
  // Registry fields (present when node is registered via NodeService)
  capabilities?: string[]
  health_state?: string
  last_heartbeat?: string
  address?: string
  language?: string
  health_score?: number
}

// RegistryNode is the full NodeRegistration from the NodeService Connect-RPC.
// Fields mirror the proto NodeRegistration message, normalised to snake_case.
export interface RegistryNode {
  id: string
  name: string
  language: string
  capabilities: string[]  // e.g. "NODE_CAPABILITY_SIGNAL_RESEARCH"
  address: string
  health_score: number    // [0.0, 1.0]
  last_heartbeat: string  // RFC3339
  autonomy_level: string
  version: string
  status: string          // "NODE_STATUS_HEALTHY" | "NODE_STATUS_DEGRADED" | "NODE_STATUS_OFFLINE" | …
  registered_at: string   // RFC3339
}

export interface Cycle {
  id: string
  started_at: string
  ended_at: string
  duration_ms: number
  nodes_executed: number
  safety_violations: number
  adversarial_alerts: number
  improvements: number
  status: 'completed' | 'running' | 'failed'
}

export interface AdversarialAlert {
  id: string
  ring: 1 | 2 | 3
  severity: 'low' | 'medium' | 'high' | 'critical'
  node_id: string
  message: string
  timestamp: string
}

export interface Improvement {
  id: string
  node_id: string
  strategy_from: string
  strategy_to: string
  timestamp: string
  rolled_back: boolean
  improvement_delta: number
}

export interface ComponentHealth {
  name: string
  status: 'healthy' | 'degraded' | 'unhealthy'
  latency_ms: number
  last_check: string
}

export interface DashboardEvent {
  type: string
  timestamp: string
  node_id?: string
  message: string
  severity?: 'info' | 'warning' | 'error'
}

// ─── Types: ProjectService ────────────────────────────────────────────────────

export interface PipelineStep {
  step_id: string
  name: string
  node_type: string
  description: string
  order: number
}

export interface Project {
  project_id: string
  name: string
  description: string
  status: string            // "active" | "paused" | "archived"
  domain: string            // "crypto_quant" | ...
  autonomy_level: string
  node_ids: string[]
  pipeline_config: PipelineStep[]
}

// ─── Types: VictoriaService ───────────────────────────────────────────────────

export interface Portfolio {
  portfolio_value: number
  unrealised_pnl: number
  realised_pnl: number
  total_pnl: number
  total_return: number
  ann_return: number
  win_rate: number
  profit_factor: number
  sharpe: number
  ann_vol: number
  allocation: Array<{ name: string; value: number; color: string }>
}

export interface Position {
  sym: string
  side: string
  size: number
  entry: number
  mark: number
  upnl: number
  pct: number
  notional: number
  leverage: number
  var95: number
}

export interface Signal {
  name: string
  avg_ic: number
  weight: number
  half_life: number
  color: string
  conviction: number
  brier_score: number
  current_value: number
  trend: string
}

export interface SignalsResponse {
  signals: Signal[]
  composite_score: number
  composite_direction: string
  oos_sharpe: number
}

export interface Trade {
  ts: string
  sym: string
  side: string
  size: number
  entry: number
  exit_price: number
  pnl: number
  slippage: number
  duration: string
}

export interface PnLMetrics {
  unrealised_pnl: number
  realised_pnl: number
  total_pnl: number
  total_return: number
  ann_return: number
  win_rate: number
  profit_factor: number
  sharpe: number
  ann_vol: number
  max_dd: number
  var95: number
  cvar95: number
  sortino: number
  calmar: number
}

export interface EquityPoint {
  date: string
  i: number
  omega: number
  btc: number
  dd: number
}

export interface EquityCurveResponse {
  points: EquityPoint[]
  train_end: number
}

// ─── Types: Training ─────────────────────────────────────────────────────────

export interface TrainingCyclePnL     { cycle: number; pnl: number }
export interface TrainingCycleWinRate { cycle: number; win_rate: number }
export interface TrainingMemoryPoint  { cycle: number; episodic: number; semantic: number }
export interface TrainingSignalConviction { name: string; value: number }
export interface TrainingActivity { cycle: number; type: 'trade' | 'signal' | 'memory'; message: string }
export interface TrainingRegime { name: string; confidence: number; dominant_signal: string }
export interface TrainingConfig { symbols: string[]; initial_capital: number; kelly_fraction: number }

export interface TrainingSnapshot {
  id: string
  cycle: number
  created_at: string
  total_pnl: number
  win_rate: number
  total_trades: number
}

export interface TrainingProgress {
  run_id: string
  total_cycles: number
  current_cycle: number
  started_at: string
  status: string  // "running" | "idle" | "completed" | "failed"
  pnl_history: TrainingCyclePnL[]
  win_rate_history: TrainingCycleWinRate[]
  memory_growth: TrainingMemoryPoint[]
  signal_conviction: TrainingSignalConviction[]
  activity_log: TrainingActivity[]
  current_regime: TrainingRegime
  config: TrainingConfig
  snapshots: TrainingSnapshot[]
}

export interface TrainingSymbolStats {
  symbol: string
  trades: number
  win_rate: number
  total_pnl: number
}

export interface TrainingRecentTrade {
  ts: string
  sym: string
  side: string
  size: number
  entry: number
  exit_price: number
  pnl: number
}

export interface TrainingMemoryCount { episodic: number; semantic: number; total: number }

export interface TrainingMetrics {
  total_trades: number
  win_rate: number
  total_pnl: number
  realised_pnl: number
  unrealised_pnl: number
  memory_count: TrainingMemoryCount
  symbol_breakdown: TrainingSymbolStats[]
  recent_trades: TrainingRecentTrade[]
  signal_health: TrainingSignalConviction[]
  current_cycle: number
  total_cycles: number
  status: string
}

// ─── Types: Intelligence ─────────────────────────────────────────────────────

export interface IntelligenceCycleRecord {
  cycle: number
  intelligence_score: number
  brain_calls: number
  improve_calls: number
  episodes_created: number
  semantic_patterns_extracted: number
  shared_memory_reads: number
  signals_nonzero: number
  rmt_info_ratio: number
  debate_gate_invocations: number
  brain_provider: string
  brain_latency_ms: number
  brain_tokens_used: number
  trust_score_avg: number
  routing_decisions: number
  adversarial_ring1: number
  adversarial_ring2: number
  adversarial_ring3: number
}

export interface IntelligenceHistory {
  records: IntelligenceCycleRecord[]
  avg_score_7d: number
  checks_passing: number
  total_checks: number
}

export interface ReflectionRecord {
  episode_id: string
  cycle: number
  trade_result: string
  regime: string
  rating: number
  lesson: string
  signal_summary: string
  conviction: number
}

export interface MemoryQuality {
  episode_count: number
  semantic_count: number
  shared_memory_count: number
  memory_ratings_count: number
  memory_influenced_trades: number
  memory_win_rate: number
  memory_utilization: number
  episode_diversity: number
  cross_project_ratio: number
  stale_memory_pct: number
  avg_episode_rating: number
}

// ─── API client ──────────────────────────────────────────────────────────────

export const api = {
  // ── OrchestratorService (legacy REST fallback for existing pages) ──────────
  getStatus: () => get<SystemHealth>('/status'),
  getNodes: () => get<Node[]>('/nodes'),
  getNode: (id: string) => get<Node>(`/nodes/${id}`),
  getCycles: () => get<Cycle[]>('/cycles'),
  getCycle: (id: string) => get<Cycle>(`/cycles/${id}`),
  getAdversarialAlerts: () => get<AdversarialAlert[]>('/adversarial/alerts'),
  getImprovements: () => get<Improvement[]>('/improvements'),
  getHealth: () => get<ComponentHealth[]>('/health'),

  // ── ProjectService ────────────────────────────────────────────────────────
  listProjects: async () => {
    // Connect-RPC returns camelCase; normalize to snake_case for the frontend.
    type RawProject = {
      projectId: string; name: string; description: string; status: string
      domain: string; autonomyLevel: string; nodeIds: string[]
      pipelineConfig: Array<{ stepId: string; name: string; nodeType: string; description: string; order: number }>
    }
    const res = await rpc<{ projects: RawProject[] }>('ProjectService', 'ListProjects')
    const projects: Project[] = (res.projects ?? []).map(p => ({
      project_id:    p.projectId,
      name:          p.name,
      description:   p.description ?? '',
      status:        p.status,
      domain:        p.domain,
      autonomy_level: p.autonomyLevel,
      node_ids:      p.nodeIds ?? [],
      pipeline_config: (p.pipelineConfig ?? []).map(s => ({
        step_id:     s.stepId,
        name:        s.name,
        node_type:   s.nodeType,
        description: s.description,
        order:       s.order,
      })),
    }))
    return { projects }
  },

  getProject: (project_id: string) =>
    rpc<{ project: Project }>('ProjectService', 'GetProject', { project_id }),

  // ── VictoriaService ───────────────────────────────────────────────────────
  // Connect-RPC returns camelCase; normalise all responses to snake_case.
  victoria: {
    getPortfolio: async () => {
      type R = { portfolioValue: number; unrealisedPnl: number; realisedPnl: number; totalPnl: number; totalReturn: number; annReturn: number; winRate: number; profitFactor: number; sharpe: number; annVol: number; allocation: Array<{ name: string; value: number; color: string }> }
      const r = await rpc<R>('VictoriaService', 'GetPortfolio')
      const p: Portfolio = { portfolio_value: r.portfolioValue ?? 0, unrealised_pnl: r.unrealisedPnl ?? 0, realised_pnl: r.realisedPnl ?? 0, total_pnl: r.totalPnl ?? 0, total_return: r.totalReturn ?? 0, ann_return: r.annReturn ?? 0, win_rate: r.winRate ?? 0, profit_factor: r.profitFactor ?? 0, sharpe: r.sharpe ?? 0, ann_vol: r.annVol ?? 0, allocation: r.allocation ?? [] }
      return p
    },

    getPositions: async () => {
      type RPos = { sym: string; side: string; size: number; entry: number; mark: number; upnl: number; pct: number; notional: number; leverage: number; var95: number }
      const r = await rpc<{ positions: RPos[] }>('VictoriaService', 'GetPositions')
      return { positions: (r.positions ?? []) as Position[] }
    },

    getPnL: async () => {
      type R = { unrealisedPnl: number; realisedPnl: number; totalPnl: number; totalReturn: number; annReturn: number; winRate: number; profitFactor: number; sharpe: number; annVol: number; maxDd: number; var95: number; cvar95: number; sortino: number; calmar: number }
      const r = await rpc<R>('VictoriaService', 'GetPnL')
      const p: PnLMetrics = { unrealised_pnl: r.unrealisedPnl ?? 0, realised_pnl: r.realisedPnl ?? 0, total_pnl: r.totalPnl ?? 0, total_return: r.totalReturn ?? 0, ann_return: r.annReturn ?? 0, win_rate: r.winRate ?? 0, profit_factor: r.profitFactor ?? 0, sharpe: r.sharpe ?? 0, ann_vol: r.annVol ?? 0, max_dd: r.maxDd ?? 0, var95: r.var95 ?? 0, cvar95: r.cvar95 ?? 0, sortino: r.sortino ?? 0, calmar: r.calmar ?? 0 }
      return p
    },

    getSignals: async () => {
      type RSig = { name: string; avgIc: number; weight: number; halfLife: number; color: string; conviction: number; brierScore: number; currentValue: number; trend: string }
      type R = { signals: RSig[]; compositeScore: number; compositeDirection: string; oosSharpe: number }
      const r = await rpc<R>('VictoriaService', 'GetSignals')
      const sr: SignalsResponse = {
        signals: (r.signals ?? []).map(s => ({ name: s.name, avg_ic: s.avgIc ?? 0, weight: s.weight ?? 0, half_life: s.halfLife ?? 0, color: s.color ?? '', conviction: s.conviction ?? 0, brier_score: s.brierScore ?? 0, current_value: s.currentValue ?? 0, trend: s.trend ?? '' })),
        composite_score: r.compositeScore ?? 0,
        composite_direction: r.compositeDirection ?? 'NEUTRAL',
        oos_sharpe: r.oosSharpe ?? 0,
      }
      return sr
    },

    getTrades: async (params: { sym_filter?: string; side_filter?: string; limit?: number } = {}) => {
      type RTrade = { ts: string; sym: string; side: string; size: number; entry: number; exitPrice: number; pnl: number; slippage: number; duration: string }
      const r = await rpc<{ trades: RTrade[] }>('VictoriaService', 'GetTrades', params)
      const trades: Trade[] = (r.trades ?? []).map(t => ({ ts: t.ts, sym: t.sym, side: t.side, size: t.size ?? 0, entry: t.entry ?? 0, exit_price: t.exitPrice ?? 0, pnl: t.pnl ?? 0, slippage: t.slippage ?? 0, duration: t.duration ?? '' }))
      return { trades }
    },

    getEquityCurve: async (limit = 200) => {
      type RPoint = { date: string; i: number; omega: number; btc: number; dd: number }
      type R = { points: RPoint[]; trainEnd: number }
      const r = await rpc<R>('VictoriaService', 'GetEquityCurve', { limit })
      const ec: EquityCurveResponse = { points: (r.points ?? []).map(p => ({ date: p.date, i: p.i ?? 0, omega: p.omega ?? 0, btc: p.btc ?? 0, dd: p.dd ?? 0 })), train_end: r.trainEnd ?? 0 }
      return ec
    },
  },

  // ── Training progress ─────────────────────────────────────────────────────
  training: {
    getProgress: () => fetch('/api/v1/training/progress').then(r => r.json()) as Promise<TrainingProgress>,
    getMetrics:  () => fetch('/api/v1/training/metrics').then(r => r.json()) as Promise<TrainingMetrics>,
    getSnapshots: () => fetch('/api/v1/training/snapshots').then(r => r.json()) as Promise<TrainingSnapshot[]>,
    takeSnapshot: () => fetch('/api/v1/training/snapshot', { method: 'POST' }).then(r => r.json()) as Promise<TrainingSnapshot>,
  },

  // ── OrchestratorService (Connect-RPC) ─────────────────────────────────────
  orchestrator: {
    getHealth: () =>
      rpc<{ health: SystemHealth }>('OrchestratorService', 'GetHealth'),

    streamEvents: (signal?: AbortSignal) =>
      fetch('/omega.v1.OrchestratorService/StreamEvents', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Connect-Protocol-Version': '1',
        },
        body: JSON.stringify({}),
        signal,
      }),
  },

  // ── Intelligence (REST) ───────────────────────────────────────────────────
  intelligence: {
    getHistory:      () => get<IntelligenceHistory>('/intelligence/history'),
    getReflections:  () => get<ReflectionRecord[]>('/intelligence/reflections'),
    getMemoryQuality:() => get<MemoryQuality>('/intelligence/memory-quality'),
  },

  // ── NodeService (Connect-RPC) ──────────────────────────────────────────────
  node: {
    listNodes: async (): Promise<{ nodes: RegistryNode[] }> => {
      type RawNode = {
        id: string; name: string; language: string
        capabilities: string[]; address: string
        healthScore: number; lastHeartbeat: string
        autonomyLevel: string; version: string
        status: string; registeredAt: string
      }
      const res = await rpc<{ nodes: RawNode[] }>('NodeService', 'ListNodes')
      const nodes: RegistryNode[] = (res.nodes ?? []).map(n => ({
        id:             n.id ?? '',
        name:           n.name ?? '',
        language:       n.language ?? '',
        capabilities:   n.capabilities ?? [],
        address:        n.address ?? '',
        health_score:   n.healthScore ?? 0,
        last_heartbeat: n.lastHeartbeat ?? '',
        autonomy_level: n.autonomyLevel ?? '',
        version:        n.version ?? '',
        status:         n.status ?? '',
        registered_at:  n.registeredAt ?? '',
      }))
      return { nodes }
    },
  },
}
