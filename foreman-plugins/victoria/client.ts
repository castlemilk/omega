/**
 * Victoria's typed client.
 *
 * Everything the Victoria shell reads goes through here. It lives in the
 * shell's own module by design: `UseCaseViewProps` never widens to carry domain
 * data, so a view imports this file directly and Foreman never learns Victoria's
 * endpoints or types.
 *
 * ── Provenance ──────────────────────────────────────────────────────────────
 * The omega Go API is a separate repo (`~/projects/omega`) with no shared
 * package, so these types are hand-derived rather than generated. Each one
 * names its source. Two properties of the wire drove every decision below, both
 * observed live against `omega-api` on 2026-08-18:
 *
 *   1. Connect-JSON serialises proto fields as **lowerCamelCase**
 *      (`compositeDirection`, `exitPrice`, `trainEnd`), not snake_case.
 *   2. Connect-JSON **omits zero-valued fields entirely**. `GetPositions` on an
 *      empty database answers `{}` — not `{"positions":[]}`. So every field
 *      here is optional and every reader defaults it. A non-optional
 *      `positions: Position[]` would throw on the empty state, which is the
 *      state a fresh checkout is actually in.
 *
 * The REST half (`/api/v1/training/*`) is Go structs with explicit snake_case
 * json tags, so those types are snake_case and their required fields really are
 * always present.
 */
import { createDataSource, type UseCaseDataSourceConfig } from '@omega-harness/usecase-kit';

/**
 * The omega Go API.
 *
 * `probePath` is `/api/v1/training/versions` — a real, cheap GET that reads a
 * directory listing and needs no database, so the health dot reports the API's
 * reachability rather than whether Postgres happens to be seeded.
 */
export const OMEGA_SOURCE: UseCaseDataSourceConfig = {
  id: 'omega-api',
  label: 'Omega API',
  baseUrl: 'http://localhost:8080',
  envVar: 'VITE_UC_VICTORIA_URL',
  probePath: '/api/v1/training/versions',
};

export const omega = createDataSource(OMEGA_SOURCE);

/** Fully-qualified Connect service name, from `proto/omega/v1/victoria_service.proto`. */
const VICTORIA_SERVICE = 'omega.v1.VictoriaService';

// ── Connect-RPC types ────────────────────────────────────────────────────────
// Source: omega `proto/omega/v1/victoria_service.proto`. Field names are the
// proto's, camelCased by Connect-JSON. All optional — see the header note.

/** proto `VictoriaAllocationSlice`. */
export interface AllocationSlice {
  name?: string;
  value?: number;
  color?: string;
}

/** proto `GetPortfolioResponse`. Backed by the `victoria_*` tables via `db.VictoriaDB`. */
export interface Portfolio {
  portfolioValue?: number;
  unrealisedPnl?: number;
  realisedPnl?: number;
  totalPnl?: number;
  totalReturn?: number;
  annReturn?: number;
  winRate?: number;
  profitFactor?: number;
  sharpe?: number;
  annVol?: number;
  allocation?: AllocationSlice[];
}

/** proto `VictoriaPosition`. */
export interface Position {
  sym?: string;
  side?: string;
  size?: number;
  entry?: number;
  mark?: number;
  upnl?: number;
  pct?: number;
  notional?: number;
  leverage?: number;
  var95?: number;
}

/** proto `GetPnLResponse`. */
export interface PnL {
  unrealisedPnl?: number;
  realisedPnl?: number;
  totalPnl?: number;
  totalReturn?: number;
  annReturn?: number;
  winRate?: number;
  profitFactor?: number;
  sharpe?: number;
  annVol?: number;
  maxDd?: number;
  var95?: number;
  cvar95?: number;
  sortino?: number;
  calmar?: number;
}

/** proto `VictoriaSignal`. */
export interface Signal {
  name?: string;
  avgIc?: number;
  weight?: number;
  halfLife?: number;
  color?: string;
  conviction?: number;
  brierScore?: number;
  currentValue?: number;
  trend?: string;
}

/** proto `GetSignalsResponse`. */
export interface SignalsSnapshot {
  signals?: Signal[];
  compositeScore?: number;
  compositeDirection?: string;
  oosSharpe?: number;
}

/** proto `VictoriaTrade`. Note `exit_price` — `exit` is not a proto-legal field name here. */
export interface RpcTrade {
  ts?: string;
  sym?: string;
  side?: string;
  size?: number;
  entry?: number;
  exitPrice?: number;
  pnl?: number;
  slippage?: number;
  duration?: string;
}

/**
 * proto `VictoriaEquityPoint`. `omega` is the strategy's equity, `btc` the
 * benchmark, `dd` the drawdown at that point, `i` the ordinal index.
 */
export interface EquityPoint {
  date?: string;
  i?: number;
  omega?: number;
  btc?: number;
  dd?: number;
}

/**
 * proto `GetEquityCurveResponse`. `trainEnd` is the IS/OOS boundary as an index
 * into `points` — everything at or after it is out-of-sample. Zero (and so
 * omitted from the JSON) means the backend has no boundary to report, which is
 * why the chart treats "absent" and "0" identically rather than drawing a
 * marker hard against the left axis.
 */
export interface EquityCurve {
  points?: EquityPoint[];
  trainEnd?: number;
}

/** proto `VictoriaBacktestStats`, via `GetBacktestResultsResponse.stats`. */
export interface BacktestStats {
  sharpeAnn?: number;
  sortinoAnn?: number;
  maxDdPct?: number;
  calmar?: number;
  sharpeIs?: number;
  sharpeOos?: number;
  var?: number;
  cvar?: number;
  meanR?: number;
  stdR?: number;
  annReturn?: number;
  totalReturn?: number;
  portfolioValue?: number;
  maxDdDuration?: number;
  winRate?: number;
  profitFactor?: number;
  trainEnd?: number;
}

// ── REST types ───────────────────────────────────────────────────────────────
// Source: omega `internal/handler/training_handler.go`. snake_case json tags.

/**
 * `trainingVersionInfo` from `/api/v1/training/versions`.
 *
 * `version` is whatever `data/<version>_results.json` is called minus the
 * suffix — observed live: `v100`, `v101b`, `v252_replay_2025-03-05`. Nothing
 * may assume `v\d+`; the ledger sorts and filters on the string as given.
 *
 * `sharpe_ratio` reads `eval.sharpe_ratio` out of the results file, a key the
 * files in the repo do not carry — so it is 0 for every row today. The ledger
 * renders a missing Sharpe as an em dash rather than a confident "0.00".
 */
export interface VersionInfo {
  version: string;
  total_pnl: number;
  total_trades: number;
  win_rate: number;
  sharpe_ratio: number;
}

/** `/api/v1/training/versions` envelope. */
export interface VersionsResponse {
  versions: VersionInfo[];
}

/** `trainingCompareResponse` from `/api/v1/training/compare?base=&target=`. */
export interface CompareResponse {
  base: string;
  target: string;
  pnl_delta: number;
  win_rate_delta: number;
  trade_count_delta: number;
  sharpe_delta: number;
  /** "improved" | "regressed" | "neutral", decided on PnL delta alone. */
  verdict: string;
}

/** `trainingSymbolStats` from `/api/v1/training/metrics`. */
export interface SymbolStats {
  symbol: string;
  trades: number;
  win_rate: number;
  total_pnl: number;
}

/** `trainingRecentTrade` from `/api/v1/training/metrics`. */
export interface RecentTrade {
  ts: string;
  sym: string;
  side: string;
  size: number;
  entry: number;
  exit_price: number;
  pnl: number;
}

/** `trainingSignalConviction` — used for both conviction and signal health. */
export interface NamedValue {
  name: string;
  value: number;
}

/**
 * `trainingMetrics` from `/api/v1/training/metrics`.
 *
 * This is the *reliable* live source: it aggregates the `victoria_trades` /
 * `victoria_episodes` tables directly and null-fills every slice, so it answers
 * 200 with `status: "idle"` on an unseeded database rather than failing.
 */
export interface TrainingMetrics {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  realised_pnl: number;
  unrealised_pnl: number;
  memory_count: { episodic: number; semantic: number; total: number };
  symbol_breakdown: SymbolStats[];
  recent_trades: RecentTrade[];
  signal_health: NamedValue[];
  current_cycle: number;
  total_cycles: number;
  status: string;
}

/** `trainingActivity` from `/api/v1/training/progress`. */
export interface ActivityEntry {
  cycle: number;
  /** "trade" | "signal" | "memory" per the handler's comment. */
  type: string;
  message: string;
}

/**
 * `trainingProgress` from `/api/v1/training/progress`.
 *
 * ⚠ This endpoint is fragile by construction: it `json.Unmarshal`s
 * `data/training_progress.json` into a *struct*, and the file that omega's own
 * `run_training.py` leaves behind is a JSON **array** of per-cycle records. The
 * handler answers **HTTP 500 "failed to parse progress file"** against the real
 * repo data (verified live, 2026-08-18). Every field is therefore optional and
 * the Live view treats the whole endpoint as best-effort enrichment over
 * `/metrics`, surfacing the 500 instead of pretending the run is idle.
 */
export interface TrainingProgress {
  run_id?: string;
  total_cycles?: number;
  current_cycle?: number;
  started_at?: string;
  status?: string;
  pnl_history?: { cycle: number; pnl: number }[];
  win_rate_history?: { cycle: number; win_rate: number }[];
  activity_log?: ActivityEntry[];
  current_regime?: { name?: string; confidence?: number; dominant_signal?: string };
  config?: { symbols?: string[]; initial_capital?: number; kelly_fraction?: number };
}

/**
 * One row of `/api/v1/training/trade-details`.
 *
 * Source of truth is the *writer*, omega `scripts/run_training.py` (~line 1552),
 * not the handler — the handler passes the JSONL through as opaque
 * `json.RawMessage`, so it imposes no shape at all. Everything is optional
 * because the writer itself emits `null` for absent sub-signals and skips
 * fields when the strategy object is missing.
 *
 * Note what is NOT here: entry/exit price, slippage, MAE/MFE. Those live in the
 * `victoria_trades` table behind `GetTrades`, which is why the Trades view can
 * read either source and labels which one it drew.
 */
export interface TradeDetail {
  cycle?: number;
  ts?: string;
  version?: string;
  symbol?: string;
  side?: string;
  pnl?: number;
  size?: number;
  hold_cycles?: number | null;
  regime?: string;
  signals?: Record<string, number | null>;
  composite?: number | null;
  raw_composite?: number | null;
  composite_method?: string;
  conviction?: string;
  conviction_score?: number | null;
  filters_applied?: string[];
  signal_traces?: { name: string; value: number; weight: number }[];
  kelly_scale?: number;
}

/**
 * `/api/v1/signals/correlation`.
 *
 * Reads `/tmp/{version}_signal_correlation.json`, written by strategy.py's
 * `SignalCorrelationMonitor`. When the file is absent the handler answers 200
 * with empty `signals`/`matrix` and echoes the version it auto-detected, so an
 * empty grid is a legitimate response and not an error.
 */
export interface SignalCorrelation {
  signals: string[];
  matrix: number[][];
  n_observations: number;
  version?: string;
}

// ── Calls ────────────────────────────────────────────────────────────────────

const rpc = <T>(method: string, body: unknown = {}): Promise<T> =>
  omega.postConnect<T>(VICTORIA_SERVICE, method, body);

export const getPortfolio = (): Promise<Portfolio> => rpc<Portfolio>('GetPortfolio');

export const getPositions = (): Promise<Position[]> =>
  rpc<{ positions?: Position[] }>('GetPositions').then((r) => r.positions ?? []);

export const getPnL = (): Promise<PnL> => rpc<PnL>('GetPnL');

export const getSignals = (): Promise<SignalsSnapshot> => rpc<SignalsSnapshot>('GetSignals');

export const getTrades = (limit = 100): Promise<RpcTrade[]> =>
  rpc<{ trades?: RpcTrade[] }>('GetTrades', { limit }).then((r) => r.trades ?? []);

export const getEquityCurve = (limit = 0): Promise<EquityCurve> =>
  rpc<EquityCurve>('GetEquityCurve', limit > 0 ? { limit } : {});

export const getBacktestResults = (): Promise<BacktestStats> =>
  rpc<{ stats?: BacktestStats }>('GetBacktestResults').then((r) => r.stats ?? {});

export const getVersions = (): Promise<VersionInfo[]> =>
  omega
    .getJson<VersionsResponse>('/api/v1/training/versions')
    .then((r) => r.versions);

export const compareVersions = (base: string, target: string): Promise<CompareResponse> =>
  omega.getJson<CompareResponse>(
    `/api/v1/training/compare?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`,
  );

export const getTrainingMetrics = (): Promise<TrainingMetrics> =>
  omega.getJson<TrainingMetrics>('/api/v1/training/metrics');

export const getTrainingProgress = (): Promise<TrainingProgress> =>
  omega.getJson<TrainingProgress>('/api/v1/training/progress');

/** Version is optional: the handler auto-detects the newest run when omitted. */
export const getTradeDetails = (version?: string): Promise<TradeDetail[]> =>
  omega.getJson<TradeDetail[]>(
    version ? `/api/v1/training/trade-details?version=${encodeURIComponent(version)}` : '/api/v1/training/trade-details',
  );

export const getSignalCorrelation = (version?: string): Promise<SignalCorrelation> =>
  omega.getJson<SignalCorrelation>(
    version ? `/api/v1/signals/correlation?version=${encodeURIComponent(version)}` : '/api/v1/signals/correlation',
  );

/**
 * The training event stream.
 *
 * Both frames the Go handler writes are **named** (`event: connected` once on
 * open, then `event: progress` every 5s), so they must be listed explicitly —
 * an EventSource's `onmessage` would receive neither. Handlers read `ev.type`.
 */
export const TRAINING_STREAM_EVENTS = ['connected', 'progress'] as const;

/** The `progress` frame's payload, built inline in `handleStream`. */
export interface TrainingStreamFrame {
  type?: string;
  timestamp?: string;
  current_cycle?: number;
  total_cycles?: number;
  status?: string;
}

export function streamTraining(
  onFrame: (name: string, data: unknown) => void,
  onError?: (ev: Event) => void,
): () => void {
  return omega.sse(
    '/api/v1/training/events/stream',
    (ev) => {
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(ev.data as string);
      } catch {
        // A malformed frame must not kill the stream; the cycle counter simply
        // does not advance until the next good one.
        return;
      }
      onFrame(ev.type, parsed);
    },
    { events: [...TRAINING_STREAM_EVENTS], onError },
  );
}
