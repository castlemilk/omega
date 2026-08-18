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
  getEquityCurve,
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
