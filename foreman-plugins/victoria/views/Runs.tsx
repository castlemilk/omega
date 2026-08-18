/**
 * Runs — the training-version ledger.
 *
 * Every `data/<version>_results.json` in the omega repo, summarised, sortable,
 * and searchable, with the selected row's delta against its predecessor.
 *
 * Two things this view must not assume, both learned from the live data:
 *
 *   1. **Version labels are arbitrary strings.** The handler accepts anything
 *      starting with `v`, and the real corpus holds `v100`, `v101b` and
 *      `v252_replay_2025-03-05` side by side. So nothing parses `v(\d+)`;
 *      ordering is by the label's natural sort and the filter is a substring
 *      match, both of which work on all three forms.
 *   2. **Version labels are not even unique.** `parseResultsFile` prefers the
 *      `version` field written *inside* a results file over the filename, and
 *      two files in the omega data directory both declare `"v10"` — 450 rows,
 *      449 distinct labels (observed live). Rows are therefore keyed on
 *      position, not on the label.
 *   3. **`sharpe_ratio` is 0 for every row.** The handler reads
 *      `eval.sharpe_ratio` from a results file that does not carry that key.
 *      Rendering "0.00" would assert a real, terrible Sharpe; an em dash says
 *      what is true, which is that the number is not recorded.
 *
 * Profit factor and max drawdown are in the *results file* but not in the
 * `/versions` projection, and no endpoint exposes the raw file. They are named
 * as phase-2 work rather than faked from what is here.
 */
import { useMemo, useState } from 'react';
import { Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import type { VersionInfo } from '../client.js';
import { pct, pnlClass, ratio, signedCount, signedPct, signedUsd } from '../format.js';
import { useVictoriaCompare, useVictoriaVersions } from '../hooks.js';
import { Async, Card, EmptyNote, ErrorNote, LoadingNote, Num, Table, Txt, ViewFrame } from './chrome.js';

/**
 * Natural sort, so `v9` precedes `v100` and `v101b` follows `v101`.
 *
 * A plain lexicographic sort puts v100 before v9, which makes "the newest run"
 * unfindable in a 586-row ledger. `numeric: true` handles the digit runs inside
 * an otherwise free-form label without needing to understand the label.
 */
const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

export function sortVersions(rows: readonly VersionInfo[]): VersionInfo[] {
  return [...rows].sort((a, b) => collator.compare(b.version, a.version));
}

/** The row immediately older than `version`, or null when it is the oldest. */
export function predecessorOf(sorted: readonly VersionInfo[], version: string): string | null {
  const idx = sorted.findIndex((r) => r.version === version);
  if (idx < 0 || idx + 1 >= sorted.length) return null;
  return sorted[idx + 1].version;
}

function VerdictPill({ verdict }: { verdict: string }) {
  const color =
    verdict === 'improved' ? '#4ec97a' : verdict === 'regressed' ? '#e5675b' : '#6b6b74';
  return <Pill color={color}>{verdict}</Pill>;
}

function RunDetail({ version, previous }: { version: string; previous: string | null }) {
  const compare = useVictoriaCompare(previous, version);

  if (previous === null) {
    return (
      <EmptyNote
        title={`${version} is the oldest run`}
        detail="There is no earlier version to compare it against."
      />
    );
  }
  if (compare.error) return <ErrorNote error={compare.error} what={`comparing ${previous} → ${version}`} />;
  if (compare.loading || !compare.data) return <LoadingNote what="comparing" />;

  const d = compare.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-ink3">
        <span className="text-faint">{d.base}</span>
        <span className="text-ghost">→</span>
        <span className="font-medium text-ink">{d.target}</span>
        <VerdictPill verdict={d.verdict} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[10.5px] md:grid-cols-4">
        {[
          ['PnL Δ', signedUsd(d.pnl_delta), pnlClass(d.pnl_delta)],
          ['Win rate Δ', signedPct(d.win_rate_delta), pnlClass(d.win_rate_delta)],
          ['Trades Δ', signedCount(d.trade_count_delta), 'text-ink2'],
          ['Sharpe Δ', d.sharpe_delta === 0 ? '—' : ratio(d.sharpe_delta), 'text-ink2'],
        ].map(([label, value, tone]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <span className="text-[9.5px] uppercase tracking-[.08em] text-faint">{label}</span>
            <span className={`text-[13px] tabular-nums ${tone}`}>{value}</span>
          </div>
        ))}
      </div>
      <p className="text-[10.5px] leading-relaxed text-muted">
        The verdict is decided on PnL delta alone, by the omega API — it is not a
        gate result. The six hard gates (PnL floor, regime parity, drawdown
        ceiling, trade-count floor, signal integrity, auto-apply audit) are
        written to <span className="font-mono">data/{version}_gate_result.json</span> and
        have no endpoint yet.
      </p>
    </div>
  );
}

export function VictoriaRuns(_props: UseCaseViewProps) {
  const versions = useVictoriaVersions();
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  const sorted = useMemo(() => sortVersions(versions.data ?? []), [versions.data]);
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? sorted.filter((r) => r.version.toLowerCase().includes(q)) : sorted;
  }, [sorted, filter]);

  return (
    <ViewFrame
      title="Runs"
      subtitle="Every training run omega has results for, newest first. Selecting one compares it against the run before it."
      actions={
        <input
          value={filter}
          onChange={(e) => { setFilter(e.target.value); }}
          placeholder="filter versions…"
          aria-label="Filter versions"
          className="w-52 rounded-md border border-line bg-control px-2.5 py-1.5 font-mono text-[10.5px] text-ink placeholder:text-ghost focus:border-edge focus:outline-none"
        />
      }
    >
      <Async state={versions} what="loading run ledger">
        {(rows) => {
          if (rows.length === 0) {
            return (
              <Card>
                <EmptyNote
                  title="No training runs"
                  detail="The omega API found no data/*_results.json files. Runs appear here once scripts/run_training.py has completed one."
                />
              </Card>
            );
          }
          return (
            <div className="flex flex-col gap-4">
              {selected !== null && (
                <Card label={`Run ${selected}`} right={
                  <button
                    type="button"
                    onClick={() => { setSelected(null); }}
                    className="font-mono text-[9.5px] text-faint hover:text-ink3"
                  >
                    close
                  </button>
                }>
                  <RunDetail version={selected} previous={predecessorOf(sorted, selected)} />
                </Card>
              )}

              <Card
                label={`${String(shown.length)} of ${String(rows.length)} runs`}
                right={<span className="font-mono text-[9.5px] text-faint">/api/v1/training/versions</span>}
              >
                {shown.length === 0 ? (
                  <EmptyNote title="No run matches that filter" />
                ) : (
                  <Table head={['Version', 'PnL', 'Trades', 'Win rate', 'Sharpe']}>
                    {shown.map((r, i) => (
                      <tr
                        // NOT keyed on version alone: `version` is not unique.
                        // The handler prefers the `version` field written
                        // *inside* a results file over the filename, and two
                        // different files in the omega data directory both
                        // declare "v10" — which React reports as a duplicate-key
                        // warning and can render as a dropped row. The backend
                        // cannot disambiguate them either (`/compare` resolves a
                        // version to `data/<version>_results.json`), so the
                        // ledger keys on position and selects on the string,
                        // which is as precise as the API allows.
                        key={`${r.version}-${String(i)}`}
                        onClick={() => { setSelected(r.version === selected ? null : r.version); }}
                        className={`cursor-pointer border-b border-hair last:border-0 hover:bg-cardAlt ${
                          r.version === selected ? 'bg-cardAlt' : ''
                        }`}
                      >
                        <Txt className="font-mono font-medium text-ink">{r.version}</Txt>
                        <Num className={pnlClass(r.total_pnl)}>{signedUsd(r.total_pnl)}</Num>
                        <Num className="text-ink3">{String(r.total_trades)}</Num>
                        <Num className="text-ink2">{pct(r.win_rate)}</Num>
                        {/* 0 here means "not recorded" — see the header note. */}
                        <Num className="text-ink3">{r.sharpe_ratio === 0 ? '—' : ratio(r.sharpe_ratio)}</Num>
                      </tr>
                    ))}
                  </Table>
                )}
              </Card>
            </div>
          );
        }}
      </Async>
    </ViewFrame>
  );
}
