/**
 * Drive B — the four fixes observed live on 2026-08-20.
 *
 * Same technique as `victoria/views.test.tsx`: `renderToStaticMarkup`, no DOM,
 * and assertions on the *sentence an operator reads* rather than on element
 * counts. Where a whole sentence is the thing under test, it is asserted as one
 * exact string via `text()` — a `toContain` on a fragment would pass while the
 * verb still disagreed with the noun beside it.
 *
 * There is no DOM here by design (see `vitest.config.ts`), so the expander is
 * exercised the way a click actually works: its `onClick` is pulled off the
 * rendered element tree and invoked, and the resulting state is rendered.
 */
import { isValidElement } from 'react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { CompareResponse, GateResult, VersionInfo } from '../client.js';
import { pluralize } from '../format.js';
import { GateBoard, hardcodedFailureLabels } from './Gates.js';
import { ForensicsList } from './Forensics.js';
import {
  RUN_ROW_CAP,
  RunComparePanel,
  RunsLedger,
  duplicateLabelFlags,
  sharpeRecorded,
} from './Runs.js';

/** Markup → the plain sentence, entities decoded and whitespace normalised. */
function text(html: string): string {
  return html
    .replace(/<[^>]*>/g, '')
    .replace(/&#123;/g, '{')
    .replace(/&#125;/g, '}')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Every `<button>` in a rendered element tree, outermost first. */
function buttons(node: unknown, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) buttons(child, found);
    return found;
  }
  if (!isValidElement(node)) return found;
  if (node.type === 'button') found.push(node);
  const props = node.props as { children?: unknown };
  if (props.children !== undefined) buttons(props.children, found);
  return found;
}

/** Body rows carry `cursor-pointer`; the header row does not. */
function rowCount(html: string): number {
  return (html.match(/cursor-pointer/g) ?? []).length;
}

// ── V6 · pluralize, and the forensics sentence it fixes ──────────────────────

describe('pluralize', () => {
  it('returns the singular word for exactly 1 and the plural for everything else', () => {
    expect(pluralize(1, 'file', 'files')).toBe('file');
    expect(pluralize(2, 'file', 'files')).toBe('files');
    expect(pluralize(0, 'file', 'files')).toBe('files');
    // Verbs are the half the old code got wrong.
    expect(pluralize(1, 'ends', 'end')).toBe('ends');
    expect(pluralize(2, 'ends', 'end')).toBe('end');
    expect(pluralize(1, 'is', 'are')).toBe('is');
    expect(pluralize(3, 'is', 'are')).toBe('are');
  });
});

const FORENSICS_ENTRY = {
  file: 'v93-v94-forensics.json',
  baseline: 'v93',
  target: 'v94',
  size_bytes: 20480,
  modified_at: '2026-08-01T00:00:00Z',
};

describe('the Forensics unpaired-files note', () => {
  it('reads as correct singular English for one file — noun, verb and pronoun all agree', () => {
    const html = renderToStaticMarkup(
      <ForensicsList
        entries={[FORENSICS_ENTRY]}
        unpaired={['v240_universe_forensics.json']}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(text(html)).toContain(
      '1 file in the data directory ends in forensics.json without the ' +
        '{baseline}-{target} naming and is not openable here: ' +
        'v240_universe_forensics.json. It is a different document — ' +
        'v240_universe_forensics.json is a universe-selection sweep, not a run diff.',
    );
  });

  it('reads as correct plural English for two files', () => {
    const html = renderToStaticMarkup(
      <ForensicsList
        entries={[FORENSICS_ENTRY]}
        unpaired={['v240_universe_forensics.json', 'v250_universe_forensics.json']}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(text(html)).toContain(
      '2 files in the data directory end in forensics.json without the ' +
        '{baseline}-{target} naming and are not openable here: ' +
        'v240_universe_forensics.json, v250_universe_forensics.json. ' +
        'They are different documents — v240_universe_forensics.json is a ' +
        'universe-selection sweep, not a run diff.',
    );
  });
});

// ── V5 · the archived gate file's hard-coded v48/v49 labels ──────────────────

/** data/v94_gate_result.json, as the handler projects it. */
const ARCHIVED_GATES: GateResult = {
  version: 'v94',
  passed: false,
  gates: { pnl_floor: false, regime_parity: false, drawdown_ceiling: true },
  failures: [
    'pnl_floor: v49 -37.86 < v48 130.91',
    'regime_parity[crisis]: v49 -56.29 < v48 +112.98 (delta -169.27)',
  ],
  baseline_summary: { version: 'v93', pnl: 130.91, trades: 60, win_rate: 0.4833, max_drawdown: 0 },
  candidate_summary: { version: 'v94', pnl: -37.86, trades: 69, win_rate: 0.3043, max_drawdown: 0 },
  resolved_latest: false,
};

describe('hardcodedFailureLabels', () => {
  it('finds the gate module’s own literals as whole words, and nothing else', () => {
    expect(hardcodedFailureLabels(ARCHIVED_GATES.failures)).toEqual(['v48', 'v49']);
    expect(hardcodedFailureLabels(['trade_count_floor: 12 < 20'])).toEqual([]);
    // Neither a longer label nor a suffixed one is the placeholder.
    expect(hardcodedFailureLabels(['pnl_floor: v480 1.0 < v490 2.0'])).toEqual([]);
    expect(hardcodedFailureLabels(['pnl_floor: v49_replay 1.0 < v48_replay 2.0'])).toEqual([]);
  });
});

describe('the archived gate board’s placeholder note', () => {
  it('names the placeholders and interpolates the real baseline and candidate labels', () => {
    const html = renderToStaticMarkup(<GateBoard result={ARCHIVED_GATES} />);
    expect(text(html)).toContain(
      'The failure lines key their two sides as v48 and v49 — ' +
        "v49_gates.py's own hard-coded field names, which are not the versions compared. " +
        'The real labels are v93 (baseline) and v94 (candidate), ' +
        "read from each summary's version field.",
    );
  });

  it('says nothing when no failure string carries a placeholder', () => {
    const html = renderToStaticMarkup(
      <GateBoard
        result={{ ...ARCHIVED_GATES, failures: ['trade_count_floor: 12 trades < 20'] }}
      />,
    );
    expect(html).not.toContain('hard-coded field names');
    expect(text(html)).toContain('trade_count_floor: 12 trades < 20');
  });

  it('says nothing when the compared runs really were v48 and v49', () => {
    const html = renderToStaticMarkup(
      <GateBoard
        result={{
          ...ARCHIVED_GATES,
          baseline_summary: { ...ARCHIVED_GATES.baseline_summary, version: 'v48' },
          candidate_summary: { ...ARCHIVED_GATES.candidate_summary, version: 'v49' },
        }}
      />,
    );
    expect(html).not.toContain('hard-coded field names');
  });
});

// ── V3 · the compare panel no longer claims six hard gates ───────────────────

const COMPARE: CompareResponse = {
  base: 'v93',
  target: 'v94',
  pnl_delta: -168.77,
  win_rate_delta: -0.179,
  trade_count_delta: 9,
  sharpe_delta: 0,
  verdict: 'regressed',
};

describe('the Runs compare panel gate note', () => {
  it('points at the standing-baseline gates and their verdict vocabulary', () => {
    const html = renderToStaticMarkup(<RunComparePanel data={COMPARE} />);
    expect(text(html)).toContain(
      'The verdict is decided on PnL delta alone, by the omega API — it is not a gate result. ' +
        'Whether v94 may become a baseline is decided by the standing-baseline gates — ' +
        'per-cell PnL floor, trade-count floor, drawdown ceiling — which return one of ' +
        'PASS, FAIL, NO_BASELINE, NO_OP or ERROR. ' +
        'The Gates tab shows that verdict for any run one has been recorded for.',
    );
  });

  it('makes none of the retired six-gate claims, and asserts no file exists', () => {
    const html = renderToStaticMarkup(<RunComparePanel data={COMPARE} />);
    for (const forbidden of [
      'six hard gates',
      'signal integrity',
      'Signal integrity',
      'auto-apply audit',
      'Auto-apply audit',
      'regime parity',
      '_gate_result.json',
    ]) {
      expect(html).not.toContain(forbidden);
    }
  });
});

// ── V7 · the ledger: render cap, duplicate labels, the empty Sharpe column ───

function ledgerRows(n: number, overrides: Partial<VersionInfo> = {}): VersionInfo[] {
  return Array.from({ length: n }, (_, i) => ({
    version: `v${String(i + 1)}`,
    total_pnl: i,
    total_trades: 20 + i,
    win_rate: 0.5,
    sharpe_ratio: 0,
    ...overrides,
  }));
}

describe('duplicateLabelFlags', () => {
  it('flags the second and later occurrence of a label and never the first', () => {
    const rows = [
      { version: 'v10' },
      { version: 'v11' },
      { version: 'v10' },
      { version: 'v10' },
    ] as VersionInfo[];
    expect(duplicateLabelFlags(rows)).toEqual([false, false, true, true]);
  });
});

describe('sharpeRecorded', () => {
  it('is false when every row is the API’s placeholder 0, and true once one is not', () => {
    expect(sharpeRecorded(ledgerRows(3))).toBe(false);
    expect(sharpeRecorded([...ledgerRows(2), ...ledgerRows(1, { sharpe_ratio: 1.17 })])).toBe(true);
  });
});

describe('the Runs ledger render cap', () => {
  const rows = ledgerRows(450);

  it('renders exactly 100 of the 450 rows before the expander is used', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={rows}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(RUN_ROW_CAP).toBe(100);
    expect(rowCount(html)).toBe(100);
    expect(text(html)).toContain(
      'Showing the first 100 of 450 runs. The rest are not rendered yet — ' +
        'this list is truncated, not complete.',
    );
  });

  it('states the real total on the expander', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={rows}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(text(html)).toContain('Show all 450 runs');
  });

  it('renders all 450 rows, and drops the expander, once its onClick has fired', () => {
    let expanded = false;
    const onExpand = vi.fn(() => {
      expanded = true;
    });
    const tree = (
      <RunsLedger
        rows={rows}
        expanded={expanded}
        onExpand={onExpand}
        selected={null}
        onSelect={() => undefined}
      />
    );
    // No DOM in this suite, so the expander is driven through the handler the
    // click would call — pulled off the rendered tree, not guessed at.
    const found = buttons(RunsLedger(tree.props));
    expect(found).toHaveLength(1);
    (found[0].props as { onClick: () => void }).onClick();
    expect(onExpand).toHaveBeenCalledTimes(1);
    expect(expanded).toBe(true);

    const html = renderToStaticMarkup(
      <RunsLedger
        rows={rows}
        expanded={expanded}
        onExpand={onExpand}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(rowCount(html)).toBe(450);
    expect(html).not.toContain('Show all 450 runs');
  });

  it('does not truncate, and offers no expander, at exactly the cap', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={ledgerRows(100)}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(rowCount(html)).toBe(100);
    expect(html).not.toContain('Show all');
  });
});

describe('the Runs ledger duplicate-label marker', () => {
  const rows: VersionInfo[] = [
    { version: 'v11', total_pnl: 1, total_trades: 21, win_rate: 0.5, sharpe_ratio: 0 },
    { version: 'v10', total_pnl: 2, total_trades: 22, win_rate: 0.5, sharpe_ratio: 0 },
    { version: 'v10', total_pnl: 3, total_trades: 23, win_rate: 0.5, sharpe_ratio: 0 },
  ];

  it('marks the second v10 and leaves the first alone', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={rows}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect((html.match(/\(duplicate label\)/g) ?? []).length).toBe(1);
    // The marker sits on the LAST v10 cell, not the first: the markup before the
    // second v10's own cell must not contain it.
    const cells = html.split('v10');
    expect(cells[1]).not.toContain('(duplicate label)');
    expect(cells[2]).toContain('(duplicate label)');
  });

  it('marks nothing when every label is distinct', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={ledgerRows(5)}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(html).not.toContain('(duplicate label)');
  });
});

describe('the Runs ledger Sharpe column', () => {
  it('says in the header why it is empty, and explains it under the table', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={ledgerRows(3)}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain('Sharpe (not recorded)');
    expect(text(html)).toContain(
      'No run here carries a Sharpe ratio, which is why that column is empty. ' +
        '/api/v1/training/versions reads eval.sharpe_ratio and the results files ' +
        'do not write that key. The column stays, empty, rather than rendering the ' +
        "API's 0 as 0.00 — that would assert a real and terrible Sharpe.",
    );
  });

  it('drops the qualifier and the note the moment a real Sharpe arrives', () => {
    const html = renderToStaticMarkup(
      <RunsLedger
        rows={ledgerRows(3, { sharpe_ratio: 1.17 })}
        expanded={false}
        onExpand={() => undefined}
        selected={null}
        onSelect={() => undefined}
      />,
    );
    expect(html).not.toContain('Sharpe (not recorded)');
    expect(html).toContain('Sharpe');
    expect(html).toContain('1.17');
    expect(html).not.toContain('No run here carries a Sharpe ratio');
  });
});
