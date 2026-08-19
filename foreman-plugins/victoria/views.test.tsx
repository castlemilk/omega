/**
 * The phase-2 views, rendered.
 *
 * Same technique as `polymarket/shell.test.tsx`: `renderToStaticMarkup` rather
 * than a DOM, and assertions on the *text an operator reads* rather than on
 * element counts. A test that checked "six tiles rendered" would pass while
 * every tile said PASS.
 *
 * The presentational halves (`GateBoard`, `ConvictionFunnel`,
 * `ForensicsReportView`, `JournalEntry`) are exported by their views precisely
 * so the happy and empty states can be rendered against a fixture — server
 * rendering never runs effects, so a container renders only its loading state
 * and could otherwise never be asserted on anything else.
 *
 * Fixtures are the real files, trimmed: `data/v94_gate_result.json`,
 * `data/decision_traces/bt_v132a_crisis.jsonl`, `data/v93-v94-forensics.json`,
 * and `omega/nodes/victoria/training_log/V270.md`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { DataSourceError } from '@omega-harness/usecase-kit';
import type { ObjectiveState, UseCaseViewProps } from '@omega-harness/usecase-kit';
import type {
  DecisionTrace,
  ForensicsReport,
  GateResult,
  GridRulerResult,
  TrainingLogDetail,
} from './client.js';
import { GATE_VERDICTS, GRID_VERDICTS } from './client.js';
import {
  CampaignRulerCard,
  GRID_VERDICT_TONE,
  GateBoard,
  GateLoadFailure,
  VERDICT_TONE,
  VictoriaGates,
  campaignMeanAdvisory,
  rulerBars,
  standingGateEvidence,
} from './views/Gates.js';
import { ConvictionFunnel, NoDecisionTraces, VictoriaConviction } from './views/Conviction.js';
import { ForensicsList, ForensicsReportView } from './views/Forensics.js';
import { JournalEntry } from './views/Journal.js';
import { resetFocusVersion } from './store.js';

const props: UseCaseViewProps = {
  objectiveId: 'obj-1',
  state: {
    objective: { id: 'obj-1', name: 'Trade the book' },
    harnesses: [],
    interventions: [],
    tickets: [],
  } as unknown as ObjectiveState,
  focusId: null,
  onFocus: () => undefined,
  onOpenView: () => undefined,
  mutate: () => Promise.resolve(),
};

afterEach(() => {
  resetFocusVersion();
  vi.unstubAllGlobals();
});

// ── Gates ────────────────────────────────────────────────────────────────────

/** data/v94_gate_result.json, as the handler projects it. */
const GATE_RESULT: GateResult = {
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
  ],
  baseline_summary: {
    version: 'v93',
    pnl: 130.91,
    trades: 60,
    win_rate: 0.4833,
    max_drawdown: 0,
    regime_pnl: { normal: -22.7934, high_vol: 40.7237, crisis: 112.9818 },
  },
  candidate_summary: {
    version: 'v94',
    pnl: -37.86,
    trades: 69,
    win_rate: 0.3043,
    max_drawdown: 0,
    regime_pnl: { normal: -23.7077, high_vol: 42.1353, crisis: -56.2914 },
  },
  resolved_latest: false,
};

describe('the Gates board', () => {
  it('renders the verdict, every gate, and each failure under its own gate', () => {
    const html = renderToStaticMarkup(<GateBoard result={GATE_RESULT} />);
    expect(html).toContain('v94');
    expect(html).toContain('gates failed');
    for (const label of [
      'PnL floor',
      'Regime parity',
      'Drawdown ceiling',
      'Trade-count floor',
      'Signal integrity',
      'Auto-apply audit',
    ]) {
      expect(html).toContain(label);
    }
    expect(html).toContain('pnl_floor: v49 -37.86 &lt; v48 130.91');
    expect(html).toContain('regime_parity[crisis]');
    expect(html).toContain('PASS');
    expect(html).toContain('FAIL');
  });

  it('renders the comparison with the versions from the summaries, and signed deltas', () => {
    const html = renderToStaticMarkup(<GateBoard result={GATE_RESULT} />);
    expect(html).toContain('$130.91');
    expect(html).toContain('-$37.86');
    expect(html).toContain('-$168.77'); // the PnL delta
    expect(html).toContain('PnL · crisis');
    expect(html).toContain('48.3%');
  });

  it('says a gate the file never mentioned was not reported, instead of passing it', () => {
    // The most dangerous thing this view could do is paint a gate green because
    // an older gate file predates it.
    const html = renderToStaticMarkup(
      <GateBoard result={{ ...GATE_RESULT, gates: { pnl_floor: true } }} />,
    );
    expect(html).toContain('not reported by this gate file');
  });

  it('says so, in words, when both summaries carry identical measurements', () => {
    // 19 of the 280 gate files are like this, the newest included. Every delta
    // is zero because the run was gated against itself.
    const same = {
      version: 'v231_x',
      pnl: -9507.88,
      trades: 47,
      win_rate: 0.1702,
      max_drawdown: 0,
      regime_pnl: { normal: -5827.65, crisis: -1255.63 },
    };
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          ...GATE_RESULT,
          baseline_summary: same,
          candidate_summary: { ...same, version: 'v232_x' },
        }}
      />,
    );
    expect(html).toContain('identical measurements');
    expect(html).toContain('gated against itself');
  });

  it('discloses that it resolved the latest when no version was asked for', () => {
    const html = renderToStaticMarkup(
      <GateBoard result={{ ...GATE_RESULT, resolved_latest: true }} />,
    );
    expect(html).toContain('resolved as latest');
  });

  it('renders an empty comparison honestly when the file carries no summaries', () => {
    const html = renderToStaticMarkup(
      <GateBoard
        result={{ ...GATE_RESULT, baseline_summary: undefined, candidate_summary: undefined }}
      />,
    );
    expect(html).toContain('This gate file carries no summaries');
  });

  it('renders a 404 as "the gates never ran", with the API’s own sentence', () => {
    const error = new DataSourceError(
      'Omega API: GET /api/v1/training/gates?version=V270 failed',
      404,
      'no gate result for version "V270"',
    );
    const html = renderToStaticMarkup(
      <GateLoadFailure error={error} version="V270" onShowLatest={() => undefined} />,
    );
    expect(html).toContain('HTTP 404');
    expect(html).toContain('no gate result for version');
    expect(html).toContain('A missing gate result is not a failed gate');
    expect(html).toContain('omega/eval/v49_gates.py');
    expect(html).toContain('show the latest gate result instead');
  });

  it('opens without fetching, and shows its loading state', () => {
    // Server rendering runs no effects, so this asserts the same property the
    // manifest-cost test asserts for registration: opening the tab costs
    // nothing until an effect runs.
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const html = renderToStaticMarkup(<VictoriaGates {...props} />);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(html).toContain('loading gate result');
    expect(html).toContain('Gates');
  });

  it('renders a legacy file with no verdict exactly as the six-tile board', () => {
    // The regression this pins: 280 archived gate files predate the verdict
    // vocabulary and must not be reinterpreted in it.
    const html = renderToStaticMarkup(<GateBoard result={GATE_RESULT} />);
    expect(html).toContain('Baseline vs candidate');
    expect(html).toContain('Regime parity');
    expect(html).not.toContain('Standing baseline applied');
    expect(html).not.toContain('NO_OP');
  });
});

// ── Gates, standing-baseline shape ───────────────────────────────────────────

/**
 * A real standing-gate file, as `omega/eval/standing_gates.py` writes it and the
 * handler projects it. This one FAILS the per-cell floor — the cell lost money
 * (-$186.45), which is the only thing that fails a cell.
 */
const STANDING_RESULT: GateResult = {
  version: 'v272_crisis_r1',
  passed: false,
  verdict: 'FAIL',
  family: 'crisis',
  gates: { cell_pnl_floor: false, trade_count_floor: true },
  gate_details: {
    cell_pnl_floor: {
      status: 'fail',
      family: 'crisis',
      candidate_pnl_usd: -186.45,
      floor_usd: 0,
      margin_usd: -186.45,
      campaign_mean_usd: 599,
      campaign_mean_margin_usd: -785.45,
      journal_cite: 'training_log/V271.md:6',
    },
    trade_count_floor: { status: 'pass', trades: 24, floor: 20 },
    drawdown_ceiling: {
      status: 'not_evaluated',
      reason: 'observability.max_drawdown_usd absent from candidate results',
    },
  },
  standing_baseline_used: {
    source: 'omega/nodes/victoria/training_log/V271.md:6 (pre-registration, 2026-08-18)',
    updated: '2026-08-18',
    family: 'crisis',
    family_source: 'snapshot_pattern',
    per_cell_floor_usd: 0,
    campaign_mean_usd: 599,
    trade_count_floor: 20,
    journal_cite: 'training_log/V271.md:6',
  },
  candidate_summary: { version: 'v272_crisis_r1', pnl: -186.45, trades: 24, win_rate: 0.4167 },
  failures: [
    'cell_pnl_floor[crisis]: candidate -186.45 < per-cell floor +0.00 (margin -186.45)',
  ],
  notes: ['candidate trade fingerprint (timestamp column dropped): e6289844ea6023a5…'],
  resolved_latest: false,
};

describe('the Gates board, standing-baseline shape', () => {
  it('renders the verdict, the family, the floor and the failing gate’s numbers', () => {
    const html = renderToStaticMarkup(<GateBoard result={STANDING_RESULT} />);
    expect(html).toContain('v272_crisis_r1');
    expect(html).toContain('FAIL');
    expect(html).toContain('family: crisis');
    expect(html).toContain('Per-cell PnL floor');
    expect(html).toContain('-$186.45');
    expect(html).toContain('Standing baseline applied');
    expect(html).toContain('training_log/V271.md:6');
    // Both numbers are on the board, in their distinct roles.
    expect(html).toContain('Per-cell floor (the bar)');
    expect(html).toContain('Campaign mean (advisory)');
    expect(html).toContain('$599.00');
  });

  it('renders a positive-below-mean cell as a PASS with an amber advisory, not a failure', () => {
    // The revision, rendered: +$412.55 in crisis clears the $0 per-cell floor
    // but sits under the +$599 campaign mean. Crisis's median walk-forward
    // window is +$65, so failing this cell would fail most legitimate ones.
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          ...STANDING_RESULT,
          verdict: 'PASS',
          passed: true,
          failures: [],
          gates: { cell_pnl_floor: true, trade_count_floor: true },
          gate_details: {
            ...STANDING_RESULT.gate_details,
            cell_pnl_floor: {
              status: 'pass',
              family: 'crisis',
              candidate_pnl_usd: 412.55,
              floor_usd: 0,
              margin_usd: 412.55,
              campaign_mean_usd: 599,
              campaign_mean_margin_usd: -186.45,
              advisory: 'below_campaign_mean',
            },
          },
          candidate_summary: { version: 'v272_crisis_r1', pnl: 412.55, trades: 24 },
        }}
      />,
    );
    expect(html).toContain('PASS');
    expect(html).toContain('below campaign mean by $186.45');
    expect(html).toContain('informational');
    expect(html).toContain('grid-level');
    // Amber, not red: the advisory must not be tinted or worded as a failure.
    expect(html).toContain('text-warn');
    expect(html).not.toContain('gates failed');
    expect(html).not.toContain('FAIL');
  });

  it('builds the advisory line only for a below-mean gate', () => {
    expect(
      campaignMeanAdvisory({
        status: 'pass',
        advisory: 'below_campaign_mean',
        campaign_mean_usd: 2997,
        campaign_mean_margin_usd: -1997,
      }),
    ).toBe(
      'below campaign mean by $1,997.00 (mean +$2,997.00) — informational; the campaign ruler is grid-level, not per-cell.',
    );
    // No advisory field: nothing to say.
    expect(
      campaignMeanAdvisory({ status: 'pass', campaign_mean_usd: 599, campaign_mean_margin_usd: 101 }),
    ).toBeNull();
  });

  it('says NOT EVALUATED for a gate whose input was absent, never PASS', () => {
    const html = renderToStaticMarkup(<GateBoard result={STANDING_RESULT} />);
    expect(html).toContain('NOT EVALUATED');
    expect(html).toContain('max_drawdown_usd absent');
  });

  it('names a NO_OP instead of painting a green board', () => {
    // The 18-file failure mode: a deterministic replay gated against itself.
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          ...STANDING_RESULT,
          verdict: 'NO_OP',
          passed: false,
          failures: [],
          gate_details: {
            ...STANDING_RESULT.gate_details,
            cell_pnl_floor: {
              status: 'pass',
              family: 'crisis',
              candidate_pnl_usd: 1149.76,
              floor_usd: 0,
              margin_usd: 1149.76,
              campaign_mean_usd: 599,
              campaign_mean_margin_usd: 550.76,
            },
          },
          sibling_comparison: {
            status: 'informational',
            sibling_label: 'v271_crisis_r1',
            sibling_pnl_usd: 1149.76,
            sibling_trades: 24,
            candidate_pnl_usd: 1149.76,
            candidate_trades: 24,
            delta_pnl_usd: 0,
            identical_numbers: true,
            identical_trade_fingerprint: true,
            candidate_frozen_cache: true,
          },
        }}
      />,
    );
    expect(html).toContain('NO_OP');
    expect(html).toContain('measured nothing new');
    expect(html).toContain('N-1 sibling — informational only');
    expect(html).toContain('not the gate');
    expect(html).toContain('Identical trade fingerprint');
    // The PnL gate passed on its own terms — the board must still not read as a pass.
    expect(html).not.toContain('gates passed');
  });

  it('renders NO_BASELINE loudly, and does not let it look like a pass', () => {
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          ...STANDING_RESULT,
          verdict: 'NO_BASELINE',
          family: null,
          failures: [],
          gate_details: {
            cell_pnl_floor: {
              status: 'not_evaluated',
              reason: 'cell family unresolved — no standing floor applies',
            },
            trade_count_floor: { status: 'pass', trades: 24, floor: 20 },
          },
          standing_baseline_used: {
            ...STANDING_RESULT.standing_baseline_used,
            family: null,
            family_source: 'unresolved',
            per_cell_floor_usd: undefined,
            campaign_mean_usd: undefined,
          },
        }}
      />,
    );
    expect(html).toContain('NO_BASELINE');
    expect(html).toContain('family: unresolved');
    expect(html).toContain('This is NOT a pass');
    expect(html).toContain('silent skip');
  });

  it('renders ERROR with the exception the gate raised', () => {
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          version: 'v272_crisis_r1',
          passed: false,
          verdict: 'ERROR',
          gates: {},
          failures: ['gate evaluation raised: Expecting property name: line 1 column 2'],
          error: 'Expecting property name: line 1 column 2',
          resolved_latest: false,
        }}
      />,
    );
    expect(html).toContain('ERROR');
    expect(html).toContain('Gate evaluation itself raised');
    expect(html).toContain('Expecting property name');
    // Gates the file does not carry are reported as absent, not as passes.
    expect(html).toContain('not reported by this gate file');
  });

  it('renders an above-the-mean PASS as a pass, with no advisory at all', () => {
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          ...STANDING_RESULT,
          verdict: 'PASS',
          passed: true,
          failures: [],
          gate_details: {
            ...STANDING_RESULT.gate_details,
            cell_pnl_floor: {
              status: 'pass',
              family: 'crisis',
              candidate_pnl_usd: 700,
              floor_usd: 0,
              margin_usd: 700,
              campaign_mean_usd: 599,
              campaign_mean_margin_usd: 101,
            },
          },
        }}
      />,
    );
    expect(html).toContain('PASS');
    expect(html).toContain('+$700.00');
    expect(html).toContain('Every evaluated gate passed');
    expect(html).not.toContain('below campaign mean');
  });

  it('builds the evidence line for each standing gate', () => {
    expect(
      standingGateEvidence('cell_pnl_floor', {
        status: 'fail',
        family: 'crisis',
        candidate_pnl_usd: -186.45,
        floor_usd: 0,
        margin_usd: -186.45,
      }),
    ).toEqual(['-$186.45 vs floor $0.00 (margin -$186.45)', 'family: crisis']);
    expect(standingGateEvidence('trade_count_floor', { status: 'pass', trades: 24, floor: 20 })).toEqual([
      '24 trades vs floor 20',
    ]);
    expect(
      standingGateEvidence('drawdown_ceiling', {
        status: 'not_evaluated',
        reason: 'absent from candidate results',
      }),
    ).toEqual(['absent from candidate results']);
  });

  it('has a tone and a sentence for every verdict in the vocabulary', () => {
    for (const verdict of GATE_VERDICTS) {
      expect(VERDICT_TONE[verdict]).toBeDefined();
      expect(VERDICT_TONE[verdict]?.sentence.length).toBeGreaterThan(20);
    }
  });
});

// ── Campaign ruler ───────────────────────────────────────────────────────────

/**
 * REAL ruler output: `check_grid_ruler()` over the V246 exit-adaptivity grid
 * committed in the omega repo's `tests/fixtures/v247_paired_grids.json`,
 * declared low-coupling. Every number below is reproduced by the Python and
 * traces to V247_RULER.md:
 *
 *   - pooled mean-Δ **+$626.94** is §3's published "+627";
 *   - pooled MDE **$875.12** is §4's "for a V246-class low-coupling mechanism
 *     the pooled MDE at n=32 is $875";
 *   - crisis/recent/trend Δ-sd 1023 / 1149 / 2699 are §3's v246_exit_adapt row.
 */
const RULER_PASS: GridRulerResult = {
  run_label: 'v246_wf',
  verdict: 'PASS',
  passed: true,
  failures: [],
  ruler_notes: [],
  resolved_latest: false,
  families: {
    crisis: {
      family: 'crisis', status: 'pass', n: 12, expected_n: 12,
      mean_delta_usd: 523.2075, sd_usd: 1023.1545, mde_usd: 827.3491,
      published_mde_usd: 1565, margin_usd: 1350.5566,
      bootstrap_ci95_usd: [-25.9875, 1078.0311],
    },
    recent: {
      family: 'recent', status: 'pass', n: 10, expected_n: 10,
      mean_delta_usd: 71.527, sd_usd: 1149.4338, mde_usd: 1017.9439,
      published_mde_usd: 1043, margin_usd: 1089.4709,
      bootstrap_ci95_usd: [-571.739, 783.0331],
    },
    trend: {
      family: 'trend', status: 'pass', n: 10, expected_n: 10,
      mean_delta_usd: 1306.847, sd_usd: 2699.4801, mde_usd: 2391.1493,
      published_mde_usd: 4118, margin_usd: 3697.9963,
      bootstrap_ci95_usd: [-211.4996, 2991.6817],
    },
    pooled: {
      family: 'pooled', status: 'pass', n: 32, expected_n: 32,
      mean_delta_usd: 626.9447, sd_usd: 1767.3336, mde_usd: 875.1155,
      published_mde_usd: 1425, margin_usd: 1502.0602,
      bootstrap_ci95_usd: [53.2395, 1258.0491],
    },
  },
  coverage: {
    expected_windows: 32,
    covered_windows: 32,
    complete: true,
    pairing: 'paired_per_window',
    per_family: {
      crisis: { expected: 12, covered: 12, missing: [] },
      recent: { expected: 10, covered: 10, missing: [] },
      trend: { expected: 10, covered: 10, missing: [] },
    },
    unpairable_cells: [],
  },
};

describe('the campaign ruler card', () => {
  it('renders the verdict, the run, and coverage', () => {
    const html = renderToStaticMarkup(<CampaignRulerCard result={RULER_PASS} />);
    expect(html).toContain('v246_wf');
    expect(html).toContain('PASS');
    expect(html).toContain('32/32 manifest windows');
    expect(html).toContain('paired_per_window');
    // A PASS must not be allowed to read as "the candidate improved".
    expect(html).toContain('NO-REGRESSION');
    expect(html).toContain('V247_RULER.md');
  });

  it('draws a bar per family with its mean-Δ against its own MDE', () => {
    const html = renderToStaticMarkup(<CampaignRulerCard result={RULER_PASS} />);
    for (const family of ['crisis', 'recent', 'trend', 'pooled']) {
      expect(html).toContain(family);
    }
    // V247_RULER.md §3's published pooled +$627 and §4's low-coupling $875 bar.
    expect(html).toContain('+$626.94');
    expect(html).toContain('-$875.12');
    expect(html).toContain('HELD');
  });

  it('computes the bars, and never draws one for a family it did not measure', () => {
    const bars = rulerBars(RULER_PASS.families);
    expect(bars.map((b) => b.family)).toEqual(['crisis', 'recent', 'trend', 'pooled']);

    const pooled = bars[3];
    expect(pooled.tone).toBe('pass');
    expect(pooled.n).toBe(32);
    // +626.94 / 875.12 — comfortably above the floor, well under the clamp.
    expect(pooled.ratio).toBeCloseTo(0.7164, 3);
    expect(pooled.evidence).toBe('mean-Δ +$626.94 vs bar -$875.12 (margin +$1,502.06)');

    // A family with no covered windows has NO bar. A zero-length one would read
    // as "exactly on the baseline" — a measurement that was never made.
    const [none] = rulerBars({
      crisis: { family: 'crisis', status: 'not_evaluated', n: 0, reason: 'no candidate cell resolved to a crisis window — nothing to pair' },
    });
    expect(none.tone).toBe('not_evaluated');
    expect(none.ratio).toBeNull();
    expect(none.evidence).toContain('nothing to pair');
  });

  it('renders a negative Δ inside the MDE as within-noise, never as a failure', () => {
    // V245's real pooled −$31 (V247_RULER.md §3) against the median-row bar.
    const [bar] = rulerBars({
      pooled: {
        family: 'pooled', status: 'pass', n: 32, expected_n: 32,
        mean_delta_usd: -31.2, sd_usd: 1278, mde_usd: 632.9,
        published_mde_usd: 1425, margin_usd: 601.7,
        advisory: 'regression_within_noise',
      },
    });
    expect(bar.tone).toBe('within_noise');
    expect(bar.ratio).toBeLessThan(0);

    const html = renderToStaticMarkup(
      <CampaignRulerCard result={{ ...RULER_PASS, families: { pooled: { family: 'pooled', status: 'pass', n: 32, mean_delta_usd: -31.2, mde_usd: 632.9, margin_usd: 601.7 } } }} />,
    );
    expect(html).toContain('WITHIN NOISE');
    expect(html).toContain('§7 forbids reading it as signal');
    expect(html).not.toContain('REGRESSED');
  });

  it('renders a real regression as a failure with the ruler’s own sentence', () => {
    const html = renderToStaticMarkup(
      <CampaignRulerCard
        result={{
          ...RULER_PASS,
          verdict: 'FAIL',
          passed: false,
          failures: [
            'grid_regression[pooled]: mean-Δ -1,900.00 is below −MDE -875.12 (n=32, Δ-sd assumed $1,767); the standing baseline regressed by more than this instrument’s resolution',
          ],
          families: {
            pooled: { family: 'pooled', status: 'fail', n: 32, expected_n: 32, mean_delta_usd: -1900, mde_usd: 875.1155, margin_usd: -1024.88 },
          },
        }}
      />,
    );
    expect(html).toContain('FAIL');
    expect(html).toContain('REGRESSED');
    expect(html).toContain('grid_regression[pooled]');
    expect(html).toContain('baseline regressed');
  });

  it('renders INSUFFICIENT_GRID loudly, names the missing windows, and is not a pass', () => {
    const html = renderToStaticMarkup(
      <CampaignRulerCard
        result={{
          run_label: 'v232',
          verdict: 'INSUFFICIENT_GRID',
          passed: false,
          failures: [],
          resolved_latest: false,
          families: {
            crisis: { family: 'crisis', status: 'not_evaluated', n: 0, expected_n: 12, reason: 'no candidate cell resolved to a crisis window — nothing to pair' },
          },
          coverage: {
            expected_windows: 32,
            covered_windows: 0,
            complete: false,
            per_family: {
              crisis: { expected: 12, covered: 0, missing: ['snap_wf_20200101', 'snap_wf_20200629'] },
            },
            unpairable_cells: [
              { label: 'v232_crisis_snap_crisis_2020q1_off_crisis_r1', reason: "snapshot 'snap_crisis_2020q1' is not a walk_forward_manifest window id — not a walk-forward cell" },
            ],
          },
          ruler_notes: ['INSUFFICIENT_GRID: 32 of 32 manifest windows are not covered by this run'],
        }}
      />,
    );
    expect(html).toContain('INSUFFICIENT_GRID');
    expect(html).toContain('This is NOT a pass');
    expect(html).toContain('0/32 manifest windows');
    expect(html).toContain('snap_wf_20200101');
    expect(html).toContain('Manifest windows this run never covered');
    // Excluded cells are named, not silently dropped.
    expect(html).toContain('not a walk-forward cell');
    expect(html).toContain('NOT EVALUATED');
    // The ruler's own conservative notes are shown in full.
    expect(html).toContain('32 of 32 manifest windows are not covered');
  });

  it('says out loud when a CELL label was resolved to its GRID', () => {
    const html = renderToStaticMarkup(
      <CampaignRulerCard
        result={{ ...RULER_PASS, resolved_prefix: true, requested: 'v246_wf_snap_wf_20230912_on_trend_r1' }}
      />,
    );
    expect(html).toContain('is the verdict for the grid');
    expect(html).toContain('v246_wf_snap_wf_20230912_on_trend_r1');
  });

  it('has a tone and a sentence for every grid verdict in the vocabulary', () => {
    for (const verdict of GRID_VERDICTS) {
      expect(GRID_VERDICT_TONE[verdict]).toBeDefined();
      expect(GRID_VERDICT_TONE[verdict]?.sentence.length).toBeGreaterThan(20);
    }
  });

  it('is absent from the gate board until a grid has actually been ruled', () => {
    // The ruler is an end-of-grid tool run by hand, so most labels have no
    // verdict. That must render as nothing at all — not an error, not an empty
    // card. Server rendering never runs effects, so the container is in its
    // loading state and the card is necessarily absent; the assertion that
    // matters is that nothing shouts.
    const html = renderToStaticMarkup(<VictoriaGates {...props} />);
    expect(html).not.toContain('Campaign ruler');
    expect(html).not.toContain('INSUFFICIENT_GRID');
  });
});

// ── Conviction ───────────────────────────────────────────────────────────────

/** Reduced from data/decision_traces/bt_v132a_crisis.jsonl. */
const TRACES: DecisionTrace[] = [
  {
    ticker: 'BTCUSDT',
    cycle: 1,
    regime: 'normal',
    bear_prob: 0.3333,
    bull_prob: 0.3333,
    raw_composite: 0.7154182358405626,
    weighted_conviction: -0.27048950015860296,
    long_thresh: 0.024142574816142168,
    short_thresh: 0.024142574816142168,
    abs_min_conviction: 0.02,
    thresh_scale: 0.43111740743111004,
    threshold_gap: 0.24634692534246078,
    proposal: 'NONE',
    filters_fired: ['blacklist:skip'],
    blocking_filter: 'blacklist',
    final_decision: 'HOLD',
  },
  {
    ticker: 'ETHUSDT',
    cycle: 1,
    regime: 'normal',
    raw_composite: 0.988757568970664,
    weighted_conviction: 0.0824,
    long_thresh: 0.0241,
    short_thresh: 0.0241,
    proposal: 'LONG',
    blocking_filter: '',
    final_decision: 'TRADE',
  },
  {
    ticker: 'ADAUSDT',
    cycle: 1,
    regime: 'normal',
    raw_composite: 0.41,
    weighted_conviction: 0.031,
    proposal: 'SHORT',
    blocking_filter: 'position_limit',
    final_decision: 'FILTERED',
  },
];

describe('the Conviction funnel', () => {
  const markup = (cycle: number | null = null, truncated = false) =>
    renderToStaticMarkup(
      <ConvictionFunnel traces={TRACES} version="bt_v132a_crisis" truncated={truncated} cycle={cycle} />,
    );

  it('draws the three funnel steps with their counts and the two drop-offs named', () => {
    const html = markup();
    expect(html).toContain('Evaluated');
    expect(html).toContain('Proposed');
    expect(html).toContain('Traded');
    // A HOLD and a FILTERED are different findings and are labelled as such.
    expect(html).toContain('held — composite never cleared the threshold');
    expect(html).toContain('filtered — a proposal the pipeline killed');
  });

  it('renders the per-ticker decisions with their thresholds and blocking filter', () => {
    const html = markup();
    expect(html).toContain('BTCUSDT');
    expect(html).toContain('ETHUSDT');
    expect(html).toContain('blacklist');
    expect(html).toContain('position_limit');
    expect(html).toContain('TRADE');
    expect(html).toContain('FILTERED');
  });

  it('renders the regime context and says where the run’s own sit-out reason lives', () => {
    const html = markup();
    expect(html).toContain('normal');
    expect(html).toContain('long thresh');
    expect(html).toContain('sit_out_reason');
  });

  it('warns when the API returned exactly the row limit, so the counts are partial', () => {
    expect(markup(null, true)).toContain('longer than what is drawn here');
    expect(markup(null, false)).not.toContain('longer than what is drawn here');
  });

  it('names the producing side when a version has no traces', () => {
    // A missing trace file is a 200 with zero rows, not a 404 — without this
    // copy the panel is indistinguishable from a run that evaluated nothing.
    const html = renderToStaticMarkup(<NoDecisionTraces version="v100" />);
    expect(html).toContain('No decision traces for v100');
    expect(html).toContain('data/decision_traces/v100.jsonl');
    expect(html).toContain('scripts/run_training.py');
  });

  it('asks for a version before requesting anything, and fetches nothing to say so', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const html = renderToStaticMarkup(<VictoriaConviction {...props} />);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(html).toContain('Pick a version');
  });
});

// ── Forensics ────────────────────────────────────────────────────────────────

/** Trimmed from data/v93-v94-forensics.json — keys v35/v48 are the real ones. */
const REPORT: ForensicsReport = {
  generated_at: '2026-04-09T12:14:47.267480+00:00',
  baselines: {
    v35: { version: 'v93', pnl: 130.91, trades: 60, win_rate: 0.4833 },
    v48: { version: 'v94', pnl: -37.86, trades: 69, win_rate: 0.3043 },
  },
  conviction_histogram: {
    v35: { hold_threshold: 0.2, trade_band_count: 1, hold_band_count: 59, trade_band_pct: 0.0167, mean_conviction: 0.0836 },
    v48: { hold_threshold: 0.2, trade_band_count: 1, hold_band_count: 68, trade_band_pct: 0.0145, mean_conviction: 0.0855 },
  },
  signal_contribution_delta_proxy: {
    per_symbol: { ADAUSDT: -55.1537, ARBUSDT: -60.935 },
    note: 'Phase 1 proxy — per-symbol PnL delta, not per-signal weight delta.',
  },
  skipped_trades: [
    {
      cycle: 7,
      symbol: 'ETHUSDT',
      side: 'long',
      baseline_pnl: -3.1552,
      baseline_conviction: 0.0579,
      baseline_regime: 'normal',
      reason: 'present_in_v35_absent_in_v48',
    },
  ],
  hypotheses: [
    {
      rank: 1,
      claim: '49 baseline trades were skipped by V48, representing $156.45 of the $168.77 PnL gap.',
      confidence: 0.8489,
      evidence_refs: ['skipped_trades', 'baselines'],
    },
  ],
  regime_breakdown: {
    crisis: { v35_pnl: 112.9818, v48_pnl: -56.2914, delta: -169.2732 },
  },
};

describe('the Forensics report', () => {
  const html = () =>
    renderToStaticMarkup(<ForensicsReportView report={REPORT} file="v93-v94-forensics.json" />);

  it('leads with the ranked hypotheses and their evidence', () => {
    expect(html()).toContain('49 baseline trades were skipped');
    expect(html()).toContain('confidence 0.849');
    expect(html()).toContain('skipped_trades');
  });

  it('labels the two sides by their real versions, and discloses the report’s own keys', () => {
    // v93-v94-forensics.json keys its sides "v35"/"v48". Presenting those as
    // the versions would be wrong; hiding them would make the numbers
    // unverifiable against the file.
    const out = html();
    expect(out).toContain('v93 PnL');
    expect(out).toContain('v94 PnL');
    expect(out).toContain('run_diff.py&#x27;s own hard-coded labels');
    expect(out).toContain('v93-v94-forensics.json');
  });

  it('renders the per-symbol deltas biggest-first, the regimes, and the skipped trades', () => {
    const out = html();
    expect(out.indexOf('ARBUSDT')).toBeLessThan(out.indexOf('ADAUSDT')); // -60.94 before -55.15
    expect(out).toContain('-$60.94');
    expect(out).toContain('crisis');
    expect(out).toContain('-$169.27');
    expect(out).toContain('1 baseline entries the target never took'); // collapsed
    expect(out).toContain('present_in_v35_absent_in_v48');
  });

  it('renders the conviction histogram for both sides', () => {
    const out = html();
    expect(out).toContain('mean conviction');
    expect(out).toContain('trade band');
    expect(out).toContain('hold band');
  });

  it('renders a report with nothing in it without inventing anything', () => {
    const out = renderToStaticMarkup(<ForensicsReportView report={{}} file="empty.json" />);
    expect(out).toContain('No hypotheses in this report');
    expect(out).toContain('No per-symbol deltas');
    expect(out).toContain('No regime breakdown in this report');
    expect(out).toContain('No skipped trades recorded');
  });

  it('lists the pairs it can open and names the files it cannot pair', () => {
    const out = renderToStaticMarkup(
      <ForensicsList
        entries={[
          {
            baseline: 'v93',
            target: 'v94',
            file: 'v93-v94-forensics.json',
            size_bytes: 15242,
            modified_at: '2026-04-09T12:14:47Z',
          },
        ]}
        unpaired={['v240_universe_forensics.json']}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(out).toContain('v93-v94-forensics.json');
    expect(out).toContain('14.9 KB');
    expect(out).toContain('v240_universe_forensics.json');
    expect(out).toContain('universe-selection sweep');
  });

  it('says there are no reports rather than drawing an empty table', () => {
    const out = renderToStaticMarkup(
      <ForensicsList entries={[]} unpaired={[]} selected={null} onSelect={() => undefined} />,
    );
    expect(out).toContain('No forensics reports');
    expect(out).toContain('run_diff.py');
  });
});

// ── Journal ──────────────────────────────────────────────────────────────────

/** The opening of omega/nodes/victoria/training_log/V270.md, plus a verdict. */
const JOURNAL: TrainingLogDetail = {
  version: 'V270',
  preRegistration: [
    '# V270 — spread-budget confirmation scoring (PRE-REGISTRATION)',
    '',
    '**Date:** 2026-08-18 · **Parent:** [`V269`](V269_DEPTH_ACQUISITION_VERDICT.md)',
    '',
    '## 1. The one question',
    '',
    'Does the realized half-spread confirm, tighten, or refute V267 G2?',
  ].join('\n'),
  verdict: ['# V270 VERDICT', '', '| gate | result |', '|---|---|', '| G1 | CONFIRMED |'].join('\n'),
  files: ['V270.md', 'V270_SPREAD_BUDGET_VERDICT.md'],
  verdictFiles: ['V270_SPREAD_BUDGET_VERDICT.md'],
};

describe('the Journal entry', () => {
  it('renders both halves as markdown, side by side', () => {
    const html = renderToStaticMarkup(<JournalEntry detail={JOURNAL} />);
    expect(html).toContain('Pre-registration');
    expect(html).toContain('Verdict');
    expect(html).toContain('V270 — spread-budget confirmation scoring (PRE-REGISTRATION)');
    expect(html).toContain('1. The one question');
    // The verdict's table is a table, not pipe soup.
    expect(html).toContain('<table');
    expect(html).toContain('CONFIRMED');
    // A link is text plus its target, because there is nowhere to navigate.
    expect(html).toContain('V269_DEPTH_ACQUISITION_VERDICT.md');
    expect(html).toContain('V270.md · V270_SPREAD_BUDGET_VERDICT.md');
  });

  it('offers the jump back to the gate board for that version', () => {
    const html = renderToStaticMarkup(
      <JournalEntry detail={JOURNAL} onOpenGates={() => undefined} />,
    );
    expect(html).toContain('open the gate board for V270');
  });

  it('names a verdict with no pre-registration as the thing it is', () => {
    const html = renderToStaticMarkup(
      <JournalEntry detail={{ ...JOURNAL, preRegistration: undefined }} />,
    );
    expect(html).toContain('No pre-registration');
    expect(html).toContain('a result with no promise to measure it against');
  });

  it('says a registered question has not reported back yet', () => {
    const html = renderToStaticMarkup(<JournalEntry detail={{ ...JOURNAL, verdict: undefined }} />);
    expect(html).toContain('No verdict yet');
    expect(html).toContain('never reported');
  });

  it('names every verdict file when the API could only serve one', () => {
    const html = renderToStaticMarkup(
      <JournalEntry
        detail={{
          ...JOURNAL,
          version: 'V262',
          verdictFiles: ['V262_AUDIT_VERDICT.md', 'V262_F4_VERDICT.md'],
        }}
      />,
    );
    expect(html).toContain('2 verdict files');
    expect(html).toContain('V262_F4_VERDICT.md');
  });
});
