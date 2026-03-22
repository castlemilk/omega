export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'critical'
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

const BASE = '/api/v1/dashboard'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  getStatus: () => get<SystemStatus>('/status'),
  getNodes: () => get<Node[]>('/nodes'),
  getNode: (id: string) => get<Node>(`/nodes/${id}`),
  getCycles: () => get<Cycle[]>('/cycles'),
  getCycle: (id: string) => get<Cycle>(`/cycles/${id}`),
  getAdversarialAlerts: () => get<AdversarialAlert[]>('/adversarial/alerts'),
  getImprovements: () => get<Improvement[]>('/improvements'),
  getHealth: () => get<ComponentHealth[]>('/health'),
}
