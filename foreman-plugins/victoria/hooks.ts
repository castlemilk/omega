/**
 * Data hooks, one per view.
 *
 * Every hook returns the same `Async<T>` triple so the shared `<Async>` renderer
 * in `views/chrome.tsx` can present loading, failure and success identically
 * across six views. The failure branch keeps the `DataSourceError` itself, not
 * a stringified message: its `bodyExcerpt` is what tells an operator that
 * `/progress` answered `500 failed to parse progress file` rather than simply
 * "something went wrong", and swallowing that is the exact failure mode the
 * data-source seam exists to prevent.
 *
 * Fetching happens here, in view-level hooks — never at module scope and never
 * in the manifest. A shell that is registered but not active must cost nothing,
 * so the only thing importing this module does is define functions.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  compareVersions,
  getDecisionTraces,
  getEquityCurve,
  getForensics,
  getGates,
  getTrainingLog,
  listForensics,
  listTrainingLog,
  getPnL,
  getPortfolio,
  getPositions,
  getSignalCorrelation,
  getSignals,
  getTradeDetails,
  getTrades,
  getTrainingMetrics,
  getTrainingProgress,
  getVersions,
  streamTraining,
  type CompareResponse,
  type DecisionTracesResponse,
  type EquityCurve,
  type ForensicsList,
  type ForensicsResponse,
  type GateResult,
  type TrainingLogDetail,
  type TrainingLogEntry,
  type PnL,
  type Portfolio,
  type Position,
  type RpcTrade,
  type SignalCorrelation,
  type SignalsSnapshot,
  type TradeDetail,
  type TrainingMetrics,
  type TrainingProgress,
  type TrainingStreamFrame,
  type VersionInfo,
} from './client.js';

export interface Async<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Run `fetcher` on mount and whenever `deps` change.
 *
 * The cancellation flag is load-bearing twice: a view unmounted mid-flight must
 * not setState, and a `deps` change must not let a slow earlier response land
 * after a fast later one and show the operator the wrong version's numbers.
 */
function useAsync<T>(fetcher: () => Promise<T>, deps: readonly unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  // Held in a ref so changing the fetcher identity every render (they are
  // inline closures at the call sites) doesn't re-fire the request.
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [...deps, nonce]);

  const reload = useCallback(() => { setNonce((n) => n + 1); }, []);
  return { data, error, loading, reload };
}

// ── Overview ─────────────────────────────────────────────────────────────────

export interface OverviewData {
  portfolio: Portfolio;
  pnl: PnL;
  positions: Position[];
  equity: EquityCurve;
}

/**
 * The Overview reads four endpoints as one unit.
 *
 * `Promise.all` rather than four hooks because they are one story: a portfolio
 * value with no positions beside it is not a partially-loaded overview, it is a
 * misleading one. One failure fails the panel, and the panel says which call.
 */
export function useVictoriaOverview(): Async<OverviewData> {
  return useAsync(
    async () => {
      const [portfolio, pnl, positions, equity] = await Promise.all([
        getPortfolio(),
        getPnL(),
        getPositions(),
        getEquityCurve(240),
      ]);
      return { portfolio, pnl, positions, equity };
    },
    [],
  );
}

// ── Runs ─────────────────────────────────────────────────────────────────────

export function useVictoriaVersions(): Async<VersionInfo[]> {
  return useAsync(() => getVersions(), []);
}

/**
 * The delta between a run and its predecessor in the ledger.
 *
 * Null `base`/`target` means "nothing selected", which must not fire a request —
 * `/compare` 400s without both params, and an error rail full of 400s from
 * merely opening a tab is noise.
 */
export function useVictoriaCompare(
  base: string | null,
  target: string | null,
): Async<CompareResponse | null> {
  return useAsync(
    () => (base && target ? compareVersions(base, target) : Promise.resolve(null)),
    [base, target],
  );
}

// ── Live ─────────────────────────────────────────────────────────────────────

export function useVictoriaMetrics(): Async<TrainingMetrics> {
  return useAsync(() => getTrainingMetrics(), []);
}

/**
 * Training progress, which is allowed to fail without taking the view down.
 *
 * `/api/v1/training/progress` unmarshals `data/training_progress.json` into a
 * struct while omega's own trainer writes an array there, so it answers 500 on
 * real repo data. The Live view treats it as enrichment over `/metrics` and
 * shows the error inline; see the note on `TrainingProgress` in `client.ts`.
 */
export function useVictoriaProgress(): Async<TrainingProgress> {
  return useAsync(() => getTrainingProgress(), []);
}

export interface LiveStream {
  /** Newest frame first. Bounded — this runs for as long as the tab is open. */
  frames: { name: string; at: number; frame: TrainingStreamFrame }[];
  connected: boolean;
  error: string | null;
}

const MAX_FRAMES = 60;

/**
 * The training SSE stream.
 *
 * Both frames the Go handler emits are *named*, so `client.streamTraining`
 * subscribes by name; an EventSource's `onmessage` would receive neither and
 * this panel would sit at "connecting" forever while the stream was in fact
 * healthy. The `connected` flag flips on the handler's own `connected` frame
 * rather than on `onopen`, so it means "the server greeted us", not "a socket
 * exists".
 */
export function useVictoriaLiveStream(enabled = true): LiveStream {
  const [frames, setFrames] = useState<LiveStream['frames']>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    setError(null);
    const close = streamTraining(
      (name, data) => {
        if (name === 'connected') {
          setConnected(true);
          setError(null);
          return;
        }
        setConnected(true);
        setFrames((prev) =>
          [{ name, at: Date.now(), frame: data as TrainingStreamFrame }, ...prev].slice(0, MAX_FRAMES),
        );
      },
      () => {
        // EventSource reconnects on its own; report the gap without tearing the
        // stream down, or a blip would permanently blank the panel.
        setConnected(false);
        setError('stream disconnected — retrying');
      },
    );
    return close;
  }, [enabled]);

  return { frames, connected, error };
}

// ── Trades ───────────────────────────────────────────────────────────────────

/** A trade source that rejected while the other one answered. */
export interface TradeSourceFailure {
  /** The endpoint, named the way the view already labels its table footers. */
  source: string;
  error: Error;
}

export interface TradesData {
  details: TradeDetail[];
  rpc: RpcTrade[];
  /** Empty when both sources answered. Never swallowed — the view renders it. */
  failures: TradeSourceFailure[];
}

/** The two endpoint labels, shared with the view's table footers. */
export const TRADE_DETAILS_SOURCE = '/api/v1/training/trade-details';
export const TRADE_RPC_SOURCE = 'VictoriaService/GetTrades';

function asError(reason: unknown): Error {
  return reason instanceof Error ? reason : new Error(String(reason));
}

/**
 * Fold the two settled sources into what the view renders.
 *
 * Exported so the partial-failure case — the one that used to render "No
 * trades" over a source that had actually 500'd — is assertable without a
 * renderer. Both rejected is still a failure of the whole panel; one rejected
 * keeps the good half AND carries why the other is missing.
 */
export function settleTrades(
  details: PromiseSettledResult<TradeDetail[]>,
  rpc: PromiseSettledResult<RpcTrade[]>,
): TradesData {
  if (details.status === 'rejected' && rpc.status === 'rejected') {
    throw asError(details.reason);
  }
  const failures: TradeSourceFailure[] = [];
  if (details.status === 'rejected') {
    failures.push({ source: TRADE_DETAILS_SOURCE, error: asError(details.reason) });
  }
  if (rpc.status === 'rejected') {
    failures.push({ source: TRADE_RPC_SOURCE, error: asError(rpc.reason) });
  }
  return {
    details: details.status === 'fulfilled' ? details.value : [],
    rpc: rpc.status === 'fulfilled' ? rpc.value : [],
    failures,
  };
}

/**
 * Both trade sources, because neither is complete.
 *
 * `/trade-details` (the training JSONL) carries conviction, regime, the signal
 * waterfall and the filters applied, but no prices. `GetTrades` (the
 * `victoria_trades` table) carries entry, exit and slippage, but none of the
 * decision context. The view prefers whichever has rows and labels which it
 * drew, rather than joining them on a key neither reliably shares.
 *
 * `Promise.allSettled`: an unseeded database makes one of these fail while the
 * other is fine, and losing the good half to the bad half would be a worse
 * empty state than either source produces alone. The half that was lost is
 * reported rather than absorbed — one source failing while the other returns
 * nothing is not "there are no trades", and saying so was a lie the operator
 * had no way to catch.
 */
export function useVictoriaTrades(version?: string): Async<TradesData> {
  return useAsync(
    async () => {
      const [details, rpc] = await Promise.allSettled([getTradeDetails(version), getTrades(200)]);
      return settleTrades(details, rpc);
    },
    [version],
  );
}

// ── Equity ───────────────────────────────────────────────────────────────────

export function useVictoriaEquity(): Async<EquityCurve> {
  return useAsync(() => getEquityCurve(), []);
}

// ── Signals ──────────────────────────────────────────────────────────────────

export interface SignalsData {
  snapshot: SignalsSnapshot;
  correlation: SignalCorrelation;
}

export function useVictoriaSignals(version?: string): Async<SignalsData> {
  return useAsync(
    async () => {
      const [snapshot, correlation] = await Promise.all([
        getSignals(),
        getSignalCorrelation(version),
      ]);
      return { snapshot, correlation };
    },
    [version],
  );
}

// ── Gates ────────────────────────────────────────────────────────────────────

/**
 * The gate board.
 *
 * `null` version means "whatever the newest gate file is" and is a real request,
 * unlike the compare hook's null: the handler resolves the latest itself and
 * reports that it did via `resolved_latest`. A 404 (no gate file for that
 * version, or none at all) rejects and the view renders the handler's sentence.
 */
export function useVictoriaGates(version: string | null): Async<GateResult> {
  return useAsync(() => getGates(version ?? undefined), [version]);
}

// ── Conviction ───────────────────────────────────────────────────────────────

/**
 * Decision traces for one version.
 *
 * No version selected means no request: the handler 400s without one, and a rail
 * full of 400s from merely opening the tab is the noise the Runs view already
 * refuses to make.
 */
export function useVictoriaDecisionTraces(
  version: string | null,
): Async<DecisionTracesResponse | null> {
  return useAsync(
    () => (version ? getDecisionTraces(version) : Promise.resolve(null)),
    [version],
  );
}

// ── Forensics ────────────────────────────────────────────────────────────────

export function useVictoriaForensicsList(): Async<ForensicsList> {
  return useAsync(() => listForensics(), []);
}

export function useVictoriaForensics(
  baseline: string | null,
  target: string | null,
): Async<ForensicsResponse | null> {
  return useAsync(
    () => (baseline && target ? getForensics(baseline, target) : Promise.resolve(null)),
    [baseline, target],
  );
}

// ── Journal ──────────────────────────────────────────────────────────────────

export function useVictoriaJournal(): Async<TrainingLogEntry[]> {
  return useAsync(() => listTrainingLog(), []);
}

export function useVictoriaJournalEntry(version: string | null): Async<TrainingLogDetail | null> {
  return useAsync(
    () => (version ? getTrainingLog(version) : Promise.resolve(null)),
    [version],
  );
}
