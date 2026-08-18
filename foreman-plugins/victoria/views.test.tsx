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
import type { DecisionTrace, ForensicsReport, GateResult, TrainingLogDetail } from './client.js';
import { GateBoard, GateLoadFailure, VictoriaGates } from './views/Gates.js';
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
