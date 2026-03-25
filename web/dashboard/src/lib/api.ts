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
  listProjects: () =>
    rpc<{ projects: Project[] }>('ProjectService', 'ListProjects'),

  getProject: (project_id: string) =>
    rpc<{ project: Project }>('ProjectService', 'GetProject', { project_id }),

  // ── VictoriaService ───────────────────────────────────────────────────────
  victoria: {
    getPortfolio: () =>
      rpc<Portfolio>('VictoriaService', 'GetPortfolio'),

    getPositions: () =>
      rpc<{ positions: Position[] }>('VictoriaService', 'GetPositions'),

    getPnL: () =>
      rpc<PnLMetrics>('VictoriaService', 'GetPnL'),

    getSignals: () =>
      rpc<SignalsResponse>('VictoriaService', 'GetSignals'),

    getTrades: (params: { sym_filter?: string; side_filter?: string; limit?: number } = {}) =>
      rpc<{ trades: Trade[] }>('VictoriaService', 'GetTrades', params),

    getEquityCurve: (limit = 200) =>
      rpc<EquityCurveResponse>('VictoriaService', 'GetEquityCurve', { limit }),
  },

  // ── OrchestratorService (Connect-RPC) ─────────────────────────────────────
  orchestrator: {
    getHealth: () =>
      rpc<{ health: SystemHealth }>('OrchestratorService', 'GetHealth'),

    listNodes: () =>
      rpc<{ nodes: Node[] }>('OrchestratorService', 'ListNodes'),

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
}
