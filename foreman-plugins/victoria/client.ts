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
import {
  createDataSource,
  DataSourceError,
  type UseCaseDataSourceConfig,
} from '@omega-harness/usecase-kit';

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

// ── Phase-2 REST types ───────────────────────────────────────────────────────
// Source: omega `internal/handler/training_handler.go` (the gates / forensics /
// log / decision-trace handlers) and, where the handler passes a file through
// untouched, the *writer* of that file. Each type says which.

/**
 * One side of a gate comparison — `v48_summary` / `v49_summary` in the file,
 * surfaced by the handler as `baseline_summary` / `candidate_summary`.
 *
 * The key names in the file are LITERAL `v48`/`v49` regardless of which versions
 * were actually compared (omega/eval/v49_gates.py hard-codes its dataclass field
 * names); the real labels live in each summary's own `version`. The handler
 * already renames them, so nothing here has to know that — but it is why the
 * board reads the version off the summary rather than off the key.
 *
 * `regime_pnl` is keyed by the regime labels Victoria's data actually uses
 * (`normal`, `high_vol`, `crisis`) and is typed open, because a run that never
 * entered a regime simply omits it.
 */
export interface GateSummary {
  version?: string;
  pnl?: number;
  trades?: number;
  win_rate?: number;
  max_drawdown?: number;
  regime_pnl?: Record<string, number>;
}

/**
 * The six hard gates, in the order `omega/eval/v49_gates.py` evaluates them.
 *
 * Held as data rather than as six tiles in JSX so the board renders a gate the
 * file omits as "not reported" instead of silently drawing five tiles — the
 * handler passes `gates` straight through and older gate files predate later
 * gates.
 */
export const GATE_NAMES = [
  'pnl_floor',
  'regime_parity',
  'drawdown_ceiling',
  'trade_count_floor',
  'signal_integrity',
  'auto_apply_audit',
] as const;

export type GateName = (typeof GATE_NAMES)[number];

/**
 * The standing-baseline gates (`omega/eval/standing_gates.py`, 2026-08-18), which
 * replaced the v49 sibling comparison as the live path.
 *
 * The names are DIFFERENT from `GATE_NAMES` on purpose — `cell_pnl_floor` is not
 * `pnl_floor`. The old gate asked "did this run beat the previous one"; this one
 * asks the per-cell question that needs no distributional argument: "did this
 * cell lose money" (`per_cell_floor_usd`, $0). A file carries one vocabulary or
 * the other, never both.
 *
 * The journal's crisis +$599 / trend +$2,997 / recent +$30 are still here, but
 * as `campaign_mean_usd` — an ADVISORY, not a bar. They are means of skewed
 * per-regime walk-forward distributions (crisis's median is +$65), so a cell
 * below one is not a failing cell; see `GateDetail.advisory`.
 */
export const STANDING_GATE_NAMES = [
  'cell_pnl_floor',
  'trade_count_floor',
  'drawdown_ceiling',
] as const;

/**
 * The verdict a standing-gate file carries. Present only on the new shape;
 * legacy files have no `verdict` at all and are rendered exactly as before.
 *
 * `NO_OP`, `NO_BASELINE` and `ERROR` are the three states the old boolean could
 * not express, and each of them was previously rendered — or not rendered at
 * all — as something misleading:
 *
 * - `NO_OP`: the run reproduced a prior run under a new label. 18 of the gate
 *   files in `data/` are this, and they read as an all-green board.
 * - `NO_BASELINE`: the cell's regime family did not resolve, so no floor could
 *   be applied. The old code wrote no file at all here — a silent skip.
 * - `ERROR`: gate evaluation itself raised. The old code swallowed it.
 */
export type GateVerdict = 'PASS' | 'FAIL' | 'NO_OP' | 'NO_BASELINE' | 'ERROR';

export const GATE_VERDICTS: readonly GateVerdict[] = [
  'PASS',
  'FAIL',
  'NO_OP',
  'NO_BASELINE',
  'ERROR',
];

/** Per-gate status in the standing shape. */
export type GateStatus = 'pass' | 'fail' | 'not_evaluated';

/**
 * One standing gate: its status plus whatever numbers it was computed from.
 * Typed open because the numbers differ per gate and the file, not this client,
 * decides what evidence a gate carries.
 */
export interface GateDetail {
  status: GateStatus | string;
  reason?: string;
  family?: string;
  candidate_pnl_usd?: number;
  floor_usd?: number;
  margin_usd?: number;
  /**
   * `"below_campaign_mean"` on a PASSING `cell_pnl_floor` whose PnL sits under
   * its family's campaign mean. Informational: the gate passed, the verdict is
   * unaffected, and the board must render it as a note rather than a failure.
   */
  advisory?: string;
  /** The family's campaign mean — reported for context, never used as a bar. */
  campaign_mean_usd?: number;
  /** candidate PnL − campaign mean. Negative when the advisory is present. */
  campaign_mean_margin_usd?: number;
  campaign_mean_note?: string;
  journal_cite?: string;
  trades?: number;
  floor?: number;
  candidate_max_drawdown_usd?: number;
  ceiling_usd?: number;
  [key: string]: unknown;
}

/** `standing_baseline_used` — which floor was applied, and where it came from. */
export interface StandingBaselineUsed {
  source?: string;
  updated?: string;
  family?: string | null;
  /** How the family was resolved: manifest / snapshot_pattern / label_pattern / unresolved. */
  family_source?: string;
  /** The per-cell bar actually applied ($0 by default). */
  per_cell_floor_usd?: number;
  /** The journal's campaign mean for the family — advisory only. */
  campaign_mean_usd?: number;
  trade_count_floor?: number;
  journal_cite?: string;
}

/**
 * The N-1 sibling block — deliberately INFORMATIONAL.
 *
 * Under the v49 gates the sibling *was* the gate, which is how 18 files came to
 * carry a run compared with itself. Here it only answers "did this run
 * reproduce a prior one", and the board says so in those words.
 */
export interface SiblingComparison {
  status?: string;
  note?: string;
  sibling_label?: string | null;
  sibling_pnl_usd?: number | null;
  sibling_trades?: number | null;
  candidate_pnl_usd?: number | null;
  candidate_trades?: number | null;
  delta_pnl_usd?: number | null;
  identical_numbers?: boolean;
  identical_trade_fingerprint?: boolean;
  candidate_frozen_cache?: boolean;
}

/** `gateResponse` from `/api/v1/training/gates`. */
export interface GateResult {
  version: string;
  passed: boolean;
  /**
   * Present only on standing-gate files. Its absence is what tells the board to
   * render the legacy six-tile layout unchanged.
   */
  verdict?: GateVerdict | string;
  /** The regime family the standing floor was taken from; null when unresolved. */
  family?: string | null;
  /**
   * Typed open: the file decides which gates exist, not this client.
   *
   * The handler projects the standing shape into this map lossily — a gate whose
   * status is `not_evaluated` is OMITTED rather than guessed at, so it still
   * renders as "not reported" for a reader that only knows the booleans. Use
   * `gate_details` when it is present; it is the unlossy one.
   */
  gates: Record<string, boolean>;
  /** Verbatim per-gate objects from a standing-gate file. */
  gate_details?: Record<string, GateDetail>;
  /** Which standing floor was applied, and where in the journal it came from. */
  standing_baseline_used?: StandingBaselineUsed;
  /**
   * The N-1 sibling block. `status` is literally `"informational"`: it exists to
   * detect a run that reproduced a prior run, and never decides a pass or a fail.
   */
  sibling_comparison?: SiblingComparison;
  /** Free-text provenance lines the gate module chose to record. */
  notes?: string[];
  /** Only on an ERROR file: what gate evaluation raised. */
  error?: string;
  failures: string[];
  /** `omitempty` on the wire — a malformed gate file can carry neither. */
  baseline_summary?: GateSummary;
  candidate_summary?: GateSummary;
  /** The whole file, passed through. Rendered only as a disclosure. */
  raw?: unknown;
  /** True when no `version` was asked for and the handler picked the newest file. */
  resolved_latest: boolean;
}

/** `forensicsEntry` from `/api/v1/training/forensics` (list form). */
export interface ForensicsEntry {
  baseline: string;
  target: string;
  file: string;
  size_bytes: number;
  modified_at: string;
}

/**
 * The forensics list.
 *
 * `unpaired` is files that end in `forensics.json` but do not carry the
 * `{baseline}-{target}-forensics.json` naming — `v240_universe_forensics.json`
 * is a real one, and its contents are a completely different document. They are
 * listed, not opened.
 */
export interface ForensicsList {
  forensics: ForensicsEntry[];
  unpaired: string[];
}

/** A run summary inside a forensics report. Writer: `omega/tools/forensics/run_diff.py`. */
export interface ForensicsBaseline {
  version?: string;
  pnl?: number;
  trades?: number;
  win_rate?: number;
  long_trades?: number;
  short_trades?: number;
  profit_factor?: number;
  zero_trade_cycles?: number;
  conviction_filter_rate?: number;
  source?: string;
}

/** One side's conviction histogram — two bands, not a full distribution. */
export interface ForensicsHistogram {
  hold_threshold?: number;
  trade_band_count?: number;
  hold_band_count?: number;
  trade_band_pct?: number;
  hold_band_pct?: number;
  min_conviction?: number;
  max_conviction?: number;
  mean_conviction?: number;
}

export interface ForensicsSkippedTrade {
  cycle?: number;
  symbol?: string;
  side?: string;
  baseline_pnl?: number;
  baseline_conviction?: number;
  baseline_regime?: string;
  reason?: string;
}

export interface ForensicsHypothesis {
  rank?: number;
  claim?: string;
  confidence?: number;
  evidence_refs?: string[];
}

/**
 * A forensics report, as `run_diff.py` writes it.
 *
 * ⚠ The load-bearing quirk, verified across every paired report in the omega
 * data directory (`v93-v94`, `v48-v50`, `v35-v48`): the keys inside `baselines`,
 * `conviction_histogram` and `regime_breakdown` are the tool's own hard-coded
 * labels — literally `v35` and `v48` — and have **nothing to do** with the
 * versions being compared. `v93-v94-forensics.json` carries
 * `baselines.v35.version === "v93"`. So nothing may index these by the pair from
 * the filename; the view derives the two keys from the object's insertion order
 * (baseline first) and reads the real labels out of `.version`. `regime_breakdown`
 * is keyed by regime and its inner fields are `{key}_pnl` built from those same
 * two keys, which is why it is typed as an open record.
 */
export interface ForensicsReport {
  schema_version?: string;
  generated_at?: string;
  status?: string;
  baselines?: Record<string, ForensicsBaseline>;
  conviction_histogram?: Record<string, ForensicsHistogram>;
  signal_contribution_delta_proxy?: {
    per_symbol?: Record<string, number>;
    per_side?: Record<string, number>;
    note?: string;
  };
  skipped_trades?: ForensicsSkippedTrade[];
  hypotheses?: ForensicsHypothesis[];
  regime_breakdown?: Record<string, Record<string, number>>;
}

/** The detail envelope — the handler wraps the file rather than serving it bare. */
export interface ForensicsResponse {
  baseline: string;
  target: string;
  file: string;
  forensics: ForensicsReport;
}

/** `trainingLogEntry` from `/api/v1/training/log` (list form). */
export interface TrainingLogEntry {
  version: string;
  hasPreRegistration: boolean;
  /** `omitempty`: absent, not empty, when a cell has no verdict yet. */
  verdictFiles?: string[];
}

export interface TrainingLogList {
  entries: TrainingLogEntry[];
}

/**
 * `trainingLogResponse` — raw markdown, both halves.
 *
 * These two keys are **camelCase** while every other REST field in this API is
 * snake_case: the handler's struct tags say `preRegistration` / `verdictFiles`.
 * Following the handler rather than the convention.
 */
export interface TrainingLogDetail {
  version: string;
  preRegistration?: string;
  verdict?: string;
  files: string[];
  verdictFiles?: string[];
}

/**
 * One line of `data/decision_traces/{version}.jsonl`.
 *
 * Source of truth is the *writer* — the handler passes each line through as
 * opaque `json.RawMessage` and imposes no shape. Shape below is read from the
 * real files (e.g. `bt_v132a_crisis.jsonl`, 770 rows), where every row is one
 * **ticker in one cycle**, not a per-cycle snapshot: 770 rows = 7 tickers ×
 * 110 cycles. Everything is optional because the writer emits `null` for
 * unavailable geometry (`geo_dist_crash`) and omits nothing else consistently.
 *
 * The funnel is built from three of these fields:
 *   - `proposal` — "LONG" | "SHORT" | "NONE": what the strategy wanted;
 *   - `final_decision` — "TRADE" | "FILTERED" | "HOLD": what it got;
 *   - `blocking_filter` — the named filter that stopped it, "" when none did.
 */
export interface DecisionTrace {
  ticker?: string;
  cycle?: number;
  version?: string;
  timestamp?: string;
  signals?: Record<string, number | null>;
  raw_composite?: number;
  demeaned_composite?: number;
  basket_mean?: number;
  basket_std?: number;
  weighted_conviction?: number;
  regime?: string;
  bear_prob?: number;
  bull_prob?: number;
  thresh_scale?: number;
  long_thresh?: number;
  short_thresh?: number;
  abs_min_conviction?: number;
  ricci_scalar?: number;
  orc_mean?: number;
  geo_dist_crash?: number | null;
  fiedler_raw?: number;
  proposal?: string;
  filters_fired?: string[];
  blocking_filter?: string;
  final_decision?: string;
  threshold_gap?: number;
  explanation?: string;
}

/**
 * `/api/v1/training/decision-traces`.
 *
 * `total` is the number of rows **returned**, not the number in the file — the
 * handler counts what it emitted after applying `limit`. So `total === limit`
 * means "truncated", and the funnel says so rather than reporting a partial
 * count as the run's whole story.
 */
export interface DecisionTracesResponse {
  traces: DecisionTrace[];
  total: number;
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
 * The gate board for a version, or for the newest gate file when omitted.
 *
 * 404 is a real answer here (`no gate result for version "x"`), and it is left
 * to reject: a version with no gate file is not a version that passed, and the
 * board renders the handler's own sentence rather than an empty board.
 */
export const getGates = (version?: string): Promise<GateResult> =>
  omega.getJson<GateResult>(
    version ? `/api/v1/training/gates?version=${encodeURIComponent(version)}` : '/api/v1/training/gates',
  );

// ── Grid ruler (the campaign-level verdict) ──────────────────────────────────
//
// A DIFFERENT SUBJECT from the gate board above, and the distinction is the
// whole point of the instrument:
//
//   - a gate result judges ONE CELL (one 90-day window) against a $0 floor;
//   - a grid verdict judges ONE GRID (all 32 manifest windows) against the
//     STANDING BASELINE, on the paired per-window Δ that
//     `training_log/V247_RULER.md` specifies.
//
// The campaign means the gate board can only whisper about (+$599 crisis /
// +$2,997 trend / +$30 recent) are readable HERE, and only here, because only
// here is there an n to read them at.

/** The families the ruler rules on. `pooled` is all 32 windows together. */
export const GRID_FAMILIES = ['crisis', 'recent', 'trend', 'pooled'] as const;
export type GridFamily = (typeof GRID_FAMILIES)[number];

/**
 * A grid verdict.
 *
 * `INSUFFICIENT_GRID` is the one that matters most and the one a naive board
 * would get wrong: it is emphatically **not** a pass. It means the run did not
 * cover the manifest, so the campaign question was never actually asked.
 */
export type GridVerdictName = 'PASS' | 'FAIL' | 'INSUFFICIENT_GRID' | 'ERROR';

export const GRID_VERDICTS: readonly GridVerdictName[] = [
  'PASS',
  'FAIL',
  'INSUFFICIENT_GRID',
  'ERROR',
];

/** One family's ruling. Writer: `omega/eval/grid_ruler.FamilyRuling`. */
export interface GridFamilyRuling {
  family: string;
  /** `pass` | `fail` | `not_evaluated`. A family with no cells is the last one. */
  status: string;
  /** Windows actually covered, which is what the bar is computed at. */
  n: number;
  /** Windows the manifest says this family has. */
  expected_n?: number;
  /** The verdict statistic: mean paired Δ (candidate − standing), same window. */
  mean_delta_usd?: number;
  sd_usd?: number;
  se_usd?: number;
  two_se_usd?: number;
  /**
   * The bar, one-sided: a family FAILS iff `mean_delta_usd < −mde_usd`.
   * Recomputed at the grid's ACTUAL n, so a short grid gets a wider bar.
   */
  mde_usd?: number;
  /** The published §7 threshold at the manifest's n, for comparison. */
  published_mde_usd?: number;
  /** `mean_delta_usd − (−mde_usd)` — headroom above the floor. Negative = failed. */
  margin_usd?: number;
  bootstrap_ci95_usd?: [number, number];
  /**
   * `regression_within_noise` when the mean-Δ is negative but inside the MDE.
   * V247_RULER.md §7 forbids reading signal into that, so it is neither a
   * failure nor a silence — it rides as a note.
   */
  advisory?: string;
  reason?: string;
  [key: string]: unknown;
}

/** Which manifest windows the run actually covered. */
export interface GridCoverage {
  expected_windows?: number;
  covered_windows?: number;
  complete?: boolean;
  /** `paired_per_window` when every candidate window found its baseline twin. */
  pairing?: string;
  manifest_built_by?: string;
  per_family?: Record<string, { expected: number; covered: number; missing: string[] }>;
  /** Cells that named no manifest window — excluded, never zeroed. */
  unpairable_cells?: { label: string; reason: string }[];
}

/** `gridRulerResponse` from `/api/v1/training/grid-ruler`. */
export interface GridRulerResult {
  run_label: string;
  verdict: GridVerdictName | string;
  passed: boolean;
  families?: Record<string, GridFamilyRuling>;
  coverage?: GridCoverage;
  failures: string[];
  /**
   * Every conservative interpretation the ruler made, in its own words — an
   * undeclared coupling class, a widened bar, a deduped cell. These are not
   * decoration: the ruler is only trustworthy to the extent its choices are
   * legible, so the card renders all of them.
   */
  ruler_notes?: string[];
  standing_distribution_used?: unknown;
  provenance?: unknown;
  error?: string;
  raw?: unknown;
  /** True when no run was asked for and the handler picked the newest verdict. */
  resolved_latest: boolean;
  /**
   * True when the label asked for had no verdict of its own and the grid it
   * belongs to was served instead. The card must say so — otherwise a reader
   * takes a grid's PASS for their cell's.
   */
  resolved_prefix?: boolean;
  /** The label actually asked for, when it differs from `run_label`. */
  requested?: string;
}

/**
 * The campaign ruler for a run, or for the newest verdict when omitted.
 *
 * 404 is the ordinary case, not an error to shout about: the ruler is an
 * end-of-grid tool run by hand, so most labels will never have one. Callers
 * that want "show the card only if it exists" should use
 * {@link getGridRulerOrNull}.
 */
export const getGridRuler = (run?: string): Promise<GridRulerResult> =>
  omega.getJson<GridRulerResult>(
    run ? `/api/v1/training/grid-ruler?run=${encodeURIComponent(run)}` : '/api/v1/training/grid-ruler',
  );

/**
 * The campaign ruler, with "no verdict for this run" as `null` rather than a
 * rejection.
 *
 * This is the shape the Gates board wants. A missing grid verdict is the NORMAL
 * state — the ruler is not wired into the training loop, by design — so a cell
 * without one must render an absent card, never a red one. Only a 404 is
 * swallowed: a 500 is a real failure and still rejects.
 */
export const getGridRulerOrNull = (run?: string): Promise<GridRulerResult | null> =>
  getGridRuler(run).catch((err: unknown) => {
    // Matched on the STATUS, not on the message. A DataSourceError carries the
    // real code; sniffing "404" out of prose would also swallow a 500 whose body
    // happened to mention one.
    if (err instanceof DataSourceError && err.status === 404) return null;
    throw err;
  });

/** Every `{baseline}-{target}-forensics.json` in the data directory. */
export const listForensics = (): Promise<ForensicsList> =>
  omega.getJson<ForensicsList>('/api/v1/training/forensics');

export const getForensics = (baseline: string, target: string): Promise<ForensicsResponse> =>
  omega.getJson<ForensicsResponse>(
    `/api/v1/training/forensics?baseline=${encodeURIComponent(baseline)}&target=${encodeURIComponent(target)}`,
  );

/** The training-log index: one row per version cell that has markdown. */
export const listTrainingLog = (): Promise<TrainingLogEntry[]> =>
  omega.getJson<TrainingLogList>('/api/v1/training/log').then((r) => r.entries);

export const getTrainingLog = (version: string): Promise<TrainingLogDetail> =>
  omega.getJson<TrainingLogDetail>(
    `/api/v1/training/log?version=${encodeURIComponent(version)}`,
  );

/**
 * Per-cycle decision traces for a version.
 *
 * `limit` is sent explicitly because the handler's default is 200 rows, which is
 * under two cycles of a seven-ticker run — a funnel drawn from that would be a
 * confident lie about the run. A missing trace file is a **200** with
 * `{"traces":[],"total":0}`, not a 404, so an empty answer is an empty state.
 */
export const DECISION_TRACE_LIMIT = 4000;

export const getDecisionTraces = (
  version: string,
  limit = DECISION_TRACE_LIMIT,
): Promise<DecisionTracesResponse> =>
  omega.getJson<DecisionTracesResponse>(
    `/api/v1/training/decision-traces?version=${encodeURIComponent(version)}&limit=${String(limit)}`,
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
