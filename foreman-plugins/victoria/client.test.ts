/**
 * The Victoria client against the wire the omega Go API actually serves.
 *
 * Every fixture in this file is a real payload or a faithful reduction of one.
 * Where a response was captured live it says so — those were taken on
 * 2026-08-18 from `omega-api` built from `cmd/omega-api` at omega HEAD, running
 * against the repo's own `data/` directory. Where the endpoint could not be
 * made to produce data locally (no seeded `victoria_*` tables, no
 * `/tmp/*_signal_correlation.json`), the fixture is derived from the writer or
 * the proto and says which.
 *
 * The assertions that matter most are the ones about *absence*: Connect-JSON
 * omits zero-valued fields, so `{}` is a well-formed `GetPositions` response and
 * anything that assumes `positions` exists breaks on an empty database — which
 * is the state a fresh checkout is in.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DataSourceError } from '@omega-harness/usecase-kit';
import {
  compareVersions,
  getDecisionTraces,
  getEquityCurve,
  getForensics,
  getGates,
  getGridRuler,
  getGridRulerOrNull,
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
  OMEGA_SOURCE,
} from './client.js';

interface Captured {
  url: string;
  init: RequestInit | undefined;
}

function stubFetch(respond: (req: Captured) => Response): Captured[] {
  const calls: Captured[] = [];
  vi.stubGlobal('fetch', (input: string | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return Promise.resolve(respond({ url: String(input), init }));
  });
  return calls;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const BASE = 'http://localhost:8080';

describe('the data source declaration', () => {
  it('points at the omega API with a probe that needs no database', () => {
    expect(OMEGA_SOURCE.id).toBe('omega-api');
    expect(OMEGA_SOURCE.baseUrl).toBe(BASE);
    expect(OMEGA_SOURCE.envVar).toBe('VITE_UC_VICTORIA_URL');
    // /versions reads a directory listing; a Postgres-dependent probe would
    // show the API as "down" whenever it was merely unseeded.
    expect(OMEGA_SOURCE.probePath).toBe('/api/v1/training/versions');
  });
});

describe('Connect-RPC request shape', () => {
  it('POSTs to /omega.v1.VictoriaService/<Method> with the Connect version header', async () => {
    const calls = stubFetch(() => json({}));
    await getPortfolio();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/omega.v1.VictoriaService/GetPortfolio`);
    expect(calls[0].init?.method).toBe('POST');
    expect(calls[0].init?.headers).toEqual({
      'Content-Type': 'application/json',
      'Connect-Protocol-Version': '1',
    });
    expect(calls[0].init?.body).toBe('{}');
  });

  it('sends request fields the proto declares, and omits a limit it does not have', async () => {
    const calls = stubFetch(() => json({}));
    await getTrades(25);
    await getEquityCurve(240);
    await getEquityCurve();

    expect(calls[0].init?.body).toBe('{"limit":25}');
    expect(calls[1].init?.body).toBe('{"limit":240}');
    // GetEquityCurve with no limit must not send `limit: 0` — the handler reads
    // that as "zero points", not "everything".
    expect(calls[2].init?.body).toBe('{}');
  });
});

describe('Connect responses with fields omitted', () => {
  it('reads an empty database without throwing', async () => {
    // Captured live: every VictoriaService RPC answers exactly `{}` (or
    // `{"stats":{}}`) against an unseeded database, because Connect-JSON drops
    // zero-valued fields rather than emitting empty arrays.
    stubFetch(() => json({}));

    await expect(getPositions()).resolves.toEqual([]);
    await expect(getTrades()).resolves.toEqual([]);
    await expect(getPortfolio()).resolves.toEqual({});
    await expect(getEquityCurve()).resolves.toEqual({});

    const pnl = await getPnL();
    expect(pnl.totalPnl).toBeUndefined();
  });

  it('projects a populated portfolio, camelCased as Connect serialises it', async () => {
    // Shape derived from proto GetPortfolioResponse; values follow the omega
    // dashboard's own mock (dashboard/src/mocks/victoria.ts) so they are
    // realistic rather than round.
    stubFetch(() =>
      json({
        portfolioValue: 128450.32,
        unrealisedPnl: 2140.18,
        realisedPnl: -318.4,
        totalPnl: 1821.78,
        totalReturn: 0.2845,
        winRate: 0.4032,
        profitFactor: 1.171,
        sharpe: 1.62,
        allocation: [
          { name: 'USDT Cash', value: 41200.5, color: '#4ec97a' },
          { name: 'BTCUSDT', value: 87249.82, color: '#e8963c' },
        ],
      }),
    );

    const p = await getPortfolio();
    expect(p.portfolioValue).toBe(128450.32);
    expect(p.unrealisedPnl).toBe(2140.18);
    expect(p.allocation).toHaveLength(2);
    expect(p.allocation?.[0].name).toBe('USDT Cash');
    expect(p.allocation?.[0].value).toBe(41200.5);
  });

  it('unwraps positions, keeping exit/entry naming from the proto', async () => {
    stubFetch(() =>
      json({
        positions: [
          {
            sym: 'BTCUSDT',
            side: 'long',
            size: 0.84,
            entry: 61240.5,
            mark: 63980.25,
            upnl: 2301.79,
            pct: 0.0447,
            notional: 53743.41,
            leverage: 2,
            var95: 1840.2,
          },
        ],
      }),
    );

    const positions = await getPositions();
    expect(positions).toHaveLength(1);
    expect(positions[0].sym).toBe('BTCUSDT');
    expect(positions[0].upnl).toBe(2301.79);
    expect(positions[0].leverage).toBe(2);
  });

  it('unwraps the equity curve and its train_end marker', async () => {
    stubFetch(() =>
      json({
        points: [
          { date: '2025-01-01', i: 0, omega: 100000, btc: 100000, dd: 0 },
          { date: '2025-01-02', i: 1, omega: 101250, btc: 100800, dd: -0.004 },
          { date: '2025-01-03', i: 2, omega: 99800, btc: 101900, dd: -0.021 },
        ],
        trainEnd: 2,
      }),
    );

    const curve = await getEquityCurve();
    expect(curve.points).toHaveLength(3);
    expect(curve.trainEnd).toBe(2);
    expect(curve.points?.[1].omega).toBe(101250);
  });

  it('unwraps backtest stats out of the stats envelope', async () => {
    // Captured live: the empty response is `{"stats":{}}`, not `{}`.
    stubFetch(() => json({ stats: {} }));
    await expect(
      (await import('./client.js')).getBacktestResults(),
    ).resolves.toEqual({});
  });

  it('keeps a composite direction that arrives without its score', async () => {
    // Captured live from an unseeded database: GetSignals answers
    // {"compositeDirection":"SHORT"} — the score was 0 and so was dropped.
    stubFetch(() => json({ compositeDirection: 'SHORT' }));
    const s = await getSignals();
    expect(s.compositeDirection).toBe('SHORT');
    expect(s.compositeScore).toBeUndefined();
    expect(s.signals).toBeUndefined();
  });
});

describe('REST request shapes', () => {
  it('GETs the training endpoints at their documented paths', async () => {
    const calls = stubFetch((req) =>
      req.url.includes('/versions') ? json({ versions: [] }) : json({}),
    );

    await getVersions();
    await getTrainingMetrics();
    await getTradeDetails();

    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/api/v1/training/versions`,
      `${BASE}/api/v1/training/metrics`,
      `${BASE}/api/v1/training/trade-details`,
    ]);
    // getJson issues a bare GET — no method, no headers to get wrong.
    expect(calls[0].init).toBeUndefined();
  });

  it('URL-encodes version labels, which are arbitrary strings', async () => {
    const calls = stubFetch(() => json({}));
    // Real label from the omega data directory — not `v\d+`.
    await getTradeDetails('v252_replay_2025-03-05');
    await getSignalCorrelation('v101b');
    await compareVersions('v95', 'v96');

    expect(calls[0].url).toBe(
      `${BASE}/api/v1/training/trade-details?version=v252_replay_2025-03-05`,
    );
    expect(calls[1].url).toBe(`${BASE}/api/v1/signals/correlation?version=v101b`);
    expect(calls[2].url).toBe(`${BASE}/api/v1/training/compare?base=v95&target=v96`);
  });

  it('omits the version param entirely so the handler auto-detects', async () => {
    const calls = stubFetch(() => json({}));
    await getSignalCorrelation();
    expect(calls[0].url).toBe(`${BASE}/api/v1/signals/correlation`);
  });
});

describe('REST projections', () => {
  it('unwraps the versions envelope, preserving non-numeric labels', async () => {
    // Captured live from /api/v1/training/versions (first rows, verbatim).
    stubFetch(() =>
      json({
        versions: [
          { version: 'v100', total_pnl: 99.76, total_trades: 38, win_rate: 0.3421, sharpe_ratio: 0 },
          { version: 'v101b', total_pnl: 86.7, total_trades: 3, win_rate: 0.6667, sharpe_ratio: 0 },
          { version: 'v102', total_pnl: -225.89, total_trades: 45, win_rate: 0.2444, sharpe_ratio: 0 },
        ],
      }),
    );

    const rows = await getVersions();
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.version)).toEqual(['v100', 'v101b', 'v102']);
    expect(rows[2].total_pnl).toBe(-225.89);
    // Sharpe is 0 across the corpus: the handler reads eval.sharpe_ratio, a key
    // the results files do not carry. The ledger renders that as an em dash.
    expect(rows.every((r) => r.sharpe_ratio === 0)).toBe(true);
  });

  it('reads a compare response', async () => {
    // Captured live: /api/v1/training/compare?base=v95&target=v96
    stubFetch(() =>
      json({
        base: 'v95',
        target: 'v96',
        pnl_delta: 14.769999999999996,
        win_rate_delta: -0.0968,
        trade_count_delta: 38,
        sharpe_delta: 0,
        verdict: 'improved',
      }),
    );

    const c = await compareVersions('v95', 'v96');
    expect(c.verdict).toBe('improved');
    expect(c.trade_count_delta).toBe(38);
    expect(c.win_rate_delta).toBeCloseTo(-0.0968, 6);
  });

  it('reads the idle metrics response an unseeded database produces', async () => {
    // Captured live from /api/v1/training/metrics, verbatim.
    stubFetch(() =>
      json({
        total_trades: 0,
        win_rate: 0,
        total_pnl: 0,
        realised_pnl: 0,
        unrealised_pnl: 0,
        memory_count: { episodic: 0, semantic: 0, total: 0 },
        symbol_breakdown: [],
        recent_trades: [],
        signal_health: [],
        current_cycle: 0,
        total_cycles: 0,
        status: 'idle',
      }),
    );

    const m = await getTrainingMetrics();
    expect(m.status).toBe('idle');
    expect(m.memory_count.total).toBe(0);
    expect(m.symbol_breakdown).toEqual([]);
  });

  it('reads a trade-details row as its writer emits it', async () => {
    // Shape from the *writer*, omega scripts/run_training.py ~line 1552 — the
    // handler passes the JSONL through as opaque json.RawMessage and imposes no
    // shape at all. Null sub-signals are emitted by the writer itself.
    stubFetch(() =>
      json([
        {
          cycle: 42,
          ts: '2026-04-09T13:27:12.707045+00:00',
          version: 'v96',
          symbol: 'ETHUSDT',
          side: 'long',
          pnl: 18.4204,
          size: 0.62,
          hold_cycles: 6,
          regime: 'high_vol',
          signals: { rsi: 0.412, macd_crossover: null, zscore_signal: -0.08 },
          composite: 0.2841,
          composite_method: 'ml_weighted',
          conviction: 'HIGH',
          conviction_score: 0.6412,
          filters_applied: ['agreement_ratio'],
          signal_traces: [{ name: 'rsi', value: 0.412, weight: 0.18 }],
          kelly_scale: 0.25,
        },
      ]),
    );

    const rows = await getTradeDetails('v96');
    expect(rows).toHaveLength(1);
    expect(rows[0].regime).toBe('high_vol');
    expect(rows[0].conviction_score).toBeCloseTo(0.6412, 6);
    expect(rows[0].signals?.macd_crossover).toBeNull();
    expect(rows[0].filters_applied).toEqual(['agreement_ratio']);
  });

  it('treats an empty correlation matrix as data, not an error', async () => {
    // Captured live: the handler answers 200 and echoes the version it
    // auto-detected when /tmp/{version}_signal_correlation.json is absent.
    stubFetch(() =>
      json({ matrix: [], n_observations: 0, signals: [], version: 'v252_replay_2025-03-05' }),
    );

    const c = await getSignalCorrelation();
    expect(c.signals).toEqual([]);
    expect(c.n_observations).toBe(0);
    expect(c.version).toBe('v252_replay_2025-03-05');
  });
});

// ── Phase-2 endpoints ────────────────────────────────────────────────────────
// Every fixture below is a real file from the omega repo, trimmed. The gate
// result is `internal/handler/testdata/training/data/v94_gate_result.json`
// verbatim (which is itself a copy of `data/v94_gate_result.json`); the
// forensics report is `data/v93-v94-forensics.json` with its 49 skipped trades
// and 3 hypotheses cut to one each; the decision trace is the first line of
// `data/decision_traces/bt_v132a_crisis.jsonl`, verbatim.

const GATE_FIXTURE = {
  version: 'v94',
  passed: false,
  gates: {
    pnl_floor: false,
    regime_parity: false,
    drawdown_ceiling: true,
    trade_count_floor: true,
    signal_integrity: true,
    auto_apply_audit: true,
  },
  failures: [
    'pnl_floor: v49 -37.86 < v48 130.91',
    'regime_parity[crisis]: v49 -56.29 < v48 +112.98 (delta -169.27)',
    'regime_parity[normal]: v49 -23.71 < v48 -22.79 (delta -0.91)',
  ],
  baseline_summary: {
    version: 'v93',
    pnl: 130.91,
    trades: 60,
    win_rate: 0.4833,
    max_drawdown: 0,
    regime_pnl: { normal: -22.79340000000001, high_vol: 40.723699999999994, crisis: 112.98179999999999 },
  },
  candidate_summary: {
    version: 'v94',
    pnl: -37.86,
    trades: 69,
    win_rate: 0.3043,
    max_drawdown: 0,
    regime_pnl: { normal: -23.707699999999996, high_vol: 42.1353, crisis: -56.291399999999996 },
  },
  raw: { passed: false },
  resolved_latest: false,
};

const FORENSICS_FIXTURE = {
  schema_version: '1.0',
  generated_at: '2026-04-09T12:14:47.267480+00:00',
  status: 'ok',
  baselines: {
    v35: { version: 'v93', pnl: 130.91, trades: 60, win_rate: 0.4833, source: 'data/v35_extended_results.json' },
    v48: { version: 'v94', pnl: -37.86, trades: 69, win_rate: 0.3043, source: 'data/v48_results.json' },
  },
  conviction_histogram: {
    v35: { hold_threshold: 0.2, trade_band_count: 1, hold_band_count: 59, mean_conviction: 0.0836116300853914 },
    v48: { hold_threshold: 0.2, trade_band_count: 1, hold_band_count: 68, mean_conviction: 0.08550816069748725 },
  },
  signal_contribution_delta_proxy: {
    per_symbol: { ADAUSDT: -55.1537, ARBUSDT: -60.93499999999999 },
    per_side: { short: 11.298000000000002, long: -180.07389999999998 },
    note: 'Phase 1 proxy — per-symbol PnL delta, not per-signal weight delta.',
  },
  skipped_trades: [
    {
      cycle: 7,
      symbol: 'ETHUSDT',
      side: 'long',
      baseline_pnl: -3.1552,
      baseline_conviction: 0.05790630250793523,
      baseline_regime: 'normal',
      reason: 'present_in_v35_absent_in_v48',
    },
  ],
  hypotheses: [
    {
      rank: 1,
      claim: '49 baseline trades were skipped by V48, representing $156.45 of the $168.77 PnL gap.',
      confidence: 0.848920779759436,
      evidence_refs: ['skipped_trades', 'baselines'],
    },
  ],
  regime_breakdown: {
    crisis: { v35_pnl: 112.98179999999999, v48_pnl: -56.291399999999996, delta: -169.27319999999997 },
  },
};

const DECISION_TRACE_FIXTURE = {
  ticker: 'BTCUSDT',
  cycle: 1,
  version: 'bt_v132a_crisis',
  timestamp: '2026-04-16T05:39:49.464622+00:00',
  signals: { sma_crossover: 0.4256354716811253, fear_greed_signal: 1.005201 },
  raw_composite: 0.7154182358405626,
  demeaned_composite: -0.27048950015860296,
  basket_mean: 0.9859077359991656,
  basket_std: 0.08622348148622201,
  weighted_conviction: -0.27048950015860296,
  regime: 'normal',
  bear_prob: 0.3333,
  bull_prob: 0.3333,
  thresh_scale: 0.43111740743111004,
  long_thresh: 0.024142574816142168,
  short_thresh: 0.024142574816142168,
  abs_min_conviction: 0.02,
  ricci_scalar: 0,
  orc_mean: 0,
  geo_dist_crash: null,
  fiedler_raw: 1,
  proposal: 'NONE',
  filters_fired: ['blacklist:skip'],
  blocking_filter: 'blacklist',
  final_decision: 'HOLD',
  threshold_gap: 0.24634692534246078,
  explanation: 'BTCUSDT: HOLD — composite -0.270 below conviction threshold',
};

describe('phase-2 request shapes', () => {
  it('asks for the latest gate result by omitting the param entirely', async () => {
    const calls = stubFetch(() => json(GATE_FIXTURE));
    await getGates();
    await getGates('bt_v132a_crisis');

    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/api/v1/training/gates`,
      `${BASE}/api/v1/training/gates?version=bt_v132a_crisis`,
    ]);
  });

  it('lists forensics with no params, and opens one with both', async () => {
    const calls = stubFetch((req) =>
      req.url.includes('baseline')
        ? json({ baseline: 'v93', target: 'v94', file: 'v93-v94-forensics.json', forensics: FORENSICS_FIXTURE })
        : json({ forensics: [], unpaired: [] }),
    );

    await listForensics();
    await getForensics('v93', 'v94');

    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/api/v1/training/forensics`,
      `${BASE}/api/v1/training/forensics?baseline=v93&target=v94`,
    ]);
  });

  it('lists the training log with no params, and reads one cell with a version', async () => {
    const calls = stubFetch((req) =>
      req.url.includes('version') ? json({ version: 'V270', files: [] }) : json({ entries: [] }),
    );

    await listTrainingLog();
    await getTrainingLog('V270');

    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/api/v1/training/log`,
      `${BASE}/api/v1/training/log?version=V270`,
    ]);
  });

  it('sends an explicit decision-trace limit, because the handler defaults to 200', async () => {
    // 200 rows is under two cycles of a seven-ticker run; a funnel drawn from
    // the default would be a confident lie about the run.
    const calls = stubFetch(() => json({ traces: [], total: 0 }));
    await getDecisionTraces('bt_v132a_crisis');
    await getDecisionTraces('v252_replay_2025-03-05', 50);

    expect(calls[0].url).toBe(
      `${BASE}/api/v1/training/decision-traces?version=bt_v132a_crisis&limit=4000`,
    );
    expect(calls[1].url).toBe(
      `${BASE}/api/v1/training/decision-traces?version=v252_replay_2025-03-05&limit=50`,
    );
  });
});

describe('phase-2 projections', () => {
  it('reads a gate result, keeping the verdict map separate from the failure prose', async () => {
    stubFetch(() => json(GATE_FIXTURE));
    const g = await getGates('v94');

    expect(g.passed).toBe(false);
    expect(g.gates.pnl_floor).toBe(false);
    expect(g.gates.drawdown_ceiling).toBe(true);
    expect(g.failures).toHaveLength(3);
    // The real version labels live in the summaries; the file's own keys are the
    // literal v48_summary/v49_summary regardless of what was compared.
    expect(g.baseline_summary?.version).toBe('v93');
    expect(g.candidate_summary?.version).toBe('v94');
    expect(g.candidate_summary?.regime_pnl?.crisis).toBeCloseTo(-56.2914, 6);
    expect(g.resolved_latest).toBe(false);
  });

  it('reads a gate response that resolved the latest for us', async () => {
    stubFetch(() => json({ ...GATE_FIXTURE, resolved_latest: true }));
    await expect(getGates()).resolves.toMatchObject({ resolved_latest: true });
  });

  it('surfaces a 404 for an ungated version with the handler’s own sentence', async () => {
    // Verified live: the handler answers 404 with exactly this body. A version
    // with no gate file is not a version that failed its gates.
    stubFetch(() => new Response('no gate result for version "V270"\n', { status: 404 }));

    await expect(getGates('V270')).rejects.toBeInstanceOf(DataSourceError);
    await expect(getGates('V270')).rejects.toMatchObject({
      status: 404,
      bodyExcerpt: 'no gate result for version "V270"',
    });
  });

  it('reads a grid verdict, keeping every family ruling intact', async () => {
    // Real `check_grid_ruler()` output over the V246 grid (low coupling),
    // reduced. V247_RULER.md §3 publishes pooled +$627; §4 publishes the
    // V246-class low-coupling pooled MDE of $875.
    stubFetch(() =>
      json({
        run_label: 'v246_wf',
        verdict: 'PASS',
        passed: true,
        families: {
          pooled: {
            family: 'pooled',
            status: 'pass',
            n: 32,
            expected_n: 32,
            mean_delta_usd: 626.9447,
            sd_usd: 1767.3336,
            mde_usd: 875.1155,
            published_mde_usd: 1425,
            margin_usd: 1502.0602,
            bootstrap_ci95_usd: [53.2395, 1258.0491],
          },
        },
        coverage: { expected_windows: 32, covered_windows: 32, complete: true, pairing: 'paired_per_window' },
        failures: [],
        ruler_notes: [],
        resolved_latest: false,
      }),
    );

    const r = await getGridRuler('v246_wf');
    expect(r.verdict).toBe('PASS');
    expect(r.passed).toBe(true);
    expect(r.families?.pooled.mean_delta_usd).toBeCloseTo(626.9447, 4);
    expect(r.families?.pooled.mde_usd).toBeCloseTo(875.1155, 4);
    expect(r.families?.pooled.bootstrap_ci95_usd).toEqual([53.2395, 1258.0491]);
    expect(r.coverage?.complete).toBe(true);
  });

  it('reads INSUFFICIENT_GRID as a verdict, not as an error and not as a pass', async () => {
    stubFetch(() =>
      json({
        run_label: 'v232',
        verdict: 'INSUFFICIENT_GRID',
        passed: false,
        coverage: {
          expected_windows: 32,
          covered_windows: 0,
          complete: false,
          per_family: { crisis: { expected: 12, covered: 0, missing: ['snap_wf_20200101'] } },
        },
        failures: [],
        resolved_latest: false,
      }),
    );

    const r = await getGridRuler('v232');
    expect(r.verdict).toBe('INSUFFICIENT_GRID');
    expect(r.passed).toBe(false);
    expect(r.coverage?.per_family?.crisis.missing).toEqual(['snap_wf_20200101']);
  });

  it('sends the run as ?run=, and omits it entirely for the latest verdict', async () => {
    const calls = stubFetch(() => json({ run_label: 'x', verdict: 'PASS', passed: true, failures: [], resolved_latest: true }));
    await getGridRuler('v246_wf');
    await getGridRuler();

    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/api/v1/training/grid-ruler?run=v246_wf`,
      `${BASE}/api/v1/training/grid-ruler`,
    ]);
  });

  it('turns a 404 grid verdict into null, because most runs never had one', async () => {
    // The ruler is an end-of-grid tool run by hand and is deliberately NOT in
    // the training loop, so "no verdict" is the ordinary state. A rejection here
    // would put a red card on the gate board for every ungridded cell.
    stubFetch(() => new Response('no grid verdict for run "v94"\n', { status: 404 }));
    await expect(getGridRulerOrNull('v94')).resolves.toBeNull();
  });

  it('still rejects a grid-verdict 500 — only the 404 is ordinary', async () => {
    // Matched on the status, not on prose: a 500 whose body mentioned "404"
    // must not be swallowed into an absent card.
    stubFetch(() => new Response('failed to parse grid verdict\n', { status: 500 }));
    await expect(getGridRulerOrNull('v246_wf')).rejects.toBeInstanceOf(DataSourceError);
    await expect(getGridRulerOrNull('v246_wf')).rejects.toMatchObject({ status: 500 });
  });

  it('reads the forensics list, keeping the unpairable files separate', async () => {
    // Captured shape from listForensics: v240_universe_forensics.json is real —
    // it carries the suffix but not the {baseline}-{target} naming, and it is a
    // different document entirely.
    stubFetch(() =>
      json({
        forensics: [
          {
            baseline: 'v93',
            target: 'v94',
            file: 'v93-v94-forensics.json',
            size_bytes: 15242,
            modified_at: '2026-04-09T12:14:47Z',
          },
        ],
        unpaired: ['v240_universe_forensics.json'],
      }),
    );

    const list = await listForensics();
    expect(list.forensics).toHaveLength(1);
    expect(list.forensics[0].baseline).toBe('v93');
    expect(list.unpaired).toEqual(['v240_universe_forensics.json']);
  });

  it('unwraps a forensics report out of the handler’s envelope, quirks intact', async () => {
    stubFetch(() =>
      json({
        baseline: 'v93',
        target: 'v94',
        file: 'v93-v94-forensics.json',
        forensics: FORENSICS_FIXTURE,
      }),
    );

    const res = await getForensics('v93', 'v94');
    expect(res.file).toBe('v93-v94-forensics.json');
    // The load-bearing quirk: the report's own keys are run_diff.py's hard-coded
    // labels, NOT the pair in the filename. v93's numbers live under "v35".
    expect(Object.keys(res.forensics.baselines ?? {})).toEqual(['v35', 'v48']);
    expect(res.forensics.baselines?.v35.version).toBe('v93');
    expect(res.forensics.regime_breakdown?.crisis.v35_pnl).toBeCloseTo(112.9818, 4);
    expect(res.forensics.hypotheses?.[0].rank).toBe(1);
    expect(res.forensics.skipped_trades?.[0].symbol).toBe('ETHUSDT');
  });

  it('unwraps the training-log index, where a cell may have no verdict at all', async () => {
    // Captured shape: verdictFiles is `omitempty`, so a cell with no verdict is
    // missing the key rather than carrying an empty array.
    stubFetch(() =>
      json({
        entries: [
          { version: 'V269', hasPreRegistration: true, verdictFiles: ['V269_DEPTH_ACQUISITION_VERDICT.md'] },
          { version: 'V270', hasPreRegistration: true },
        ],
      }),
    );

    const entries = await listTrainingLog();
    expect(entries.map((e) => e.version)).toEqual(['V269', 'V270']);
    expect(entries[0].verdictFiles).toEqual(['V269_DEPTH_ACQUISITION_VERDICT.md']);
    expect(entries[1].verdictFiles).toBeUndefined();
  });

  it('reads a log cell as raw markdown, under the handler’s camelCase keys', async () => {
    // These two keys are camelCase while every other REST field in this API is
    // snake_case — the handler's struct tags say so.
    stubFetch(() =>
      json({
        version: 'V270',
        preRegistration: '# V270 — spread-budget confirmation scoring (PRE-REGISTRATION)\n',
        verdict: '# V270 VERDICT\n',
        files: ['V270.md', 'V270_SPREAD_BUDGET_VERDICT.md'],
        verdictFiles: ['V270_SPREAD_BUDGET_VERDICT.md'],
      }),
    );

    const detail = await getTrainingLog('V270');
    expect(detail.preRegistration).toContain('PRE-REGISTRATION');
    expect(detail.files).toHaveLength(2);
  });

  it('reads a decision trace as its writer emits it, nulls and all', async () => {
    stubFetch(() => json({ traces: [DECISION_TRACE_FIXTURE], total: 1 }));

    const res = await getDecisionTraces('bt_v132a_crisis');
    expect(res.total).toBe(1);
    const t = res.traces[0];
    expect(t.ticker).toBe('BTCUSDT');
    expect(t.proposal).toBe('NONE');
    expect(t.final_decision).toBe('HOLD');
    expect(t.blocking_filter).toBe('blacklist');
    expect(t.filters_fired).toEqual(['blacklist:skip']);
    // The writer emits null for geometry it could not compute; that is data.
    expect(t.geo_dist_crash).toBeNull();
    expect(t.signals?.sma_crossover).toBeCloseTo(0.4256, 4);
  });

  it('treats a missing trace file as an empty 200, not an error', async () => {
    // Verified against the handler: a missing data/decision_traces/{v}.jsonl
    // answers 200 with an empty list rather than 404, so the view's empty state
    // has to say which side is missing.
    stubFetch(() => json({ traces: [], total: 0 }));
    await expect(getDecisionTraces('v100')).resolves.toEqual({ traces: [], total: 0 });
  });
});

describe('error propagation', () => {
  it('surfaces the progress endpoint 500 with its body, not a generic failure', async () => {
    // Captured live: GET /api/v1/training/progress answers 500 with this exact
    // body against the omega repo's real data/training_progress.json, because
    // the handler decodes a struct from what run_training.py writes as an array.
    stubFetch(() => new Response('failed to parse progress file\n', { status: 500 }));

    await expect(getTrainingProgress()).rejects.toBeInstanceOf(DataSourceError);
    await expect(getTrainingProgress()).rejects.toMatchObject({
      status: 500,
      bodyExcerpt: 'failed to parse progress file',
    });
  });

  it('carries the Connect method name in a failed RPC', async () => {
    stubFetch(() =>
      json({ code: 'internal', message: 'victoria db unavailable' }, 500),
    );

    await expect(getPositions()).rejects.toThrowError(
      /Omega API: omega\.v1\.VictoriaService\/GetPositions failed: 500/,
    );
  });

  it('bounds a huge error body so an HTML page cannot flood the panel', async () => {
    stubFetch(() => new Response('<html>'.repeat(500), { status: 502 }));
    const err = await getVersions().catch((e: unknown) => e as DataSourceError);
    expect(err).toBeInstanceOf(DataSourceError);
    expect((err as DataSourceError).bodyExcerpt.length).toBe(401); // 400 + ellipsis
  });
});
