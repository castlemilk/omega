/**
 * Journal — the training log, which is the narrative the numbers belong to.
 *
 * `omega/nodes/victoria/training_log/` holds 160 markdown files written by hand
 * around each version: `V270.md` is the **pre-registration** (the question, the
 * hypothesis, the deviations, all committed *before* the run) and
 * `V270_SPREAD_BUDGET_VERDICT.md` is what actually happened. Pre-registration is
 * the whole point of the practice — a verdict read without the promise it was
 * measured against is a story told after the fact — so this view puts them side
 * by side and never shows a verdict alone without saying its pre-registration is
 * missing.
 *
 * `/api/v1/training/log` serves raw markdown; `../markdown.tsx` renders it. See
 * that file for why a renderer rather than a `<pre>` (short version: 3,231 table
 * lines in the corpus).
 *
 * ── The loop back to Gates ───────────────────────────────────────────────────
 * Each entry offers "open the gate board for this version", which is the only
 * cross-view navigation in the shell. `onOpenView` takes a view id and nothing
 * else, so the version travels through the shell-local store (`../store.ts`).
 *
 * A real finding, surfaced rather than hidden: the two corpora do not currently
 * overlap **at all**. The journal runs V148 → V270; the 280 gate files in
 * `data/` are the v50–v127 era plus suffixed cells like
 * `v232_crisis_snap_..._r2`. Zero journal versions have a gate file, even
 * case-insensitively. The jump is still offered — it is the loop the design asks
 * for, and it will work the moment gates are written for a journalled run — but
 * the button says what it will find, and the Gates view renders the 404 as "the
 * gates never ran for that label", not as a failure.
 *
 * Two *different* things separate the corpora and only one of them is fixable
 * here. The label CASE is: journal cells are `V270`, every gate file on disk is
 * `v270_gate_result.json`, and the handler resolves the label by string, so the
 * jump used to carry a label that could not match even if the file existed —
 * `gateLabel` lowercases it (see there for why client-side and not in the fetch
 * layer). The corpora themselves are the other, and no amount of normalising
 * closes it; a lowercased `v270` still 404s today because no per-cell gate has
 * ever been run for that journal cell. That is an honest empty state and the
 * Gates view says so in those terms.
 */
import { useMemo, useState } from 'react';
import { Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import type { TrainingLogDetail, TrainingLogEntry } from '../client.js';
import { Markdown } from '../markdown.js';
import { useVictoriaJournal, useVictoriaJournalEntry } from '../hooks.js';
import { setFocusVersion } from '../store.js';
import { Async, Card, EmptyNote, ErrorNote, LoadingNote, ViewFrame } from './chrome.js';

/**
 * A journal version as the gate corpus spells it.
 *
 * The journal writes `V270.md`; `data/` holds `v270_gate_result.json`, and every
 * one of the 280 gate files is lowercase. The gates handler matches the label as
 * a string, so `V270` cannot resolve — the jump was guaranteed to 404 on the
 * spelling alone, before the question of whether the file exists.
 *
 * Normalised HERE, at the jump, rather than in `client.getGates`: the picker is
 * a free-text input over a corpus whose labels are the truth (`v232_crisis_snap`
 * — case included), and a fetch layer that quietly lowercased whatever an
 * operator typed would be papering over a case-sensitive API and would make a
 * genuinely-uppercase label unreachable. What is being converted is one known
 * naming convention into another, which is a fact about these two corpora and
 * belongs where that fact is known.
 */
export function gateLabel(version: string): string {
  return version.toLowerCase();
}

/** The view id the Gates board is registered under, in the shell's manifest. */
export const GATES_VIEW_ID = 'victoria-gates';

/**
 * Seed the Gates picker and go there.
 *
 * Exported so the value that reaches the store is assertable without a click:
 * the whole point of the jump is *which label* it carries, and a test that only
 * proved "navigation happened" would have passed all through the era when every
 * jump landed on a 404 it had caused itself.
 */
export function openGatesFor(version: string, onOpenView: (viewId: string) => void): void {
  setFocusVersion(gateLabel(version));
  onOpenView(GATES_VIEW_ID);
}

/** Newest first, by the same natural order the Runs ledger uses for versions. */
const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

export function sortJournal(entries: readonly TrainingLogEntry[]): TrainingLogEntry[] {
  return [...entries].sort((a, b) => collator.compare(b.version, a.version));
}

/** How an entry reads in one line: what it has, and what it is missing. */
export function entryStatus(entry: TrainingLogEntry): {
  label: string;
  color: string;
  verdicts: number;
} {
  const verdicts = entry.verdictFiles?.length ?? 0;
  if (entry.hasPreRegistration && verdicts > 0) {
    return { label: 'closed', color: '#4ec97a', verdicts };
  }
  if (entry.hasPreRegistration) {
    return { label: 'open — no verdict', color: '#e5c04a', verdicts };
  }
  // A verdict with no pre-registration is the failure mode the practice exists
  // to prevent, and it is worth naming as such rather than showing as "fine".
  return { label: 'verdict only — not pre-registered', color: '#e5675b', verdicts };
}

function JournalList({
  entries,
  selected,
  onSelect,
}: {
  entries: readonly TrainingLogEntry[];
  selected: string | null;
  onSelect: (version: string) => void;
}) {
  return (
    <div className="flex flex-col">
      {entries.map((entry) => {
        const status = entryStatus(entry);
        return (
          <button
            key={entry.version}
            type="button"
            onClick={() => { onSelect(entry.version); }}
            className={`flex items-center justify-between gap-3 border-b border-hair px-3 py-2 text-left last:border-0 hover:bg-cardAlt ${
              entry.version === selected ? 'bg-cardAlt' : ''
            }`}
          >
            <span className="font-mono text-[11px] font-medium text-ink">{entry.version}</span>
            <span className="flex items-center gap-2">
              <span className="font-mono text-[9.5px] text-faint">
                {status.verdicts > 0
                  ? `${String(status.verdicts)} verdict${status.verdicts === 1 ? '' : 's'}`
                  : 'no verdict'}
              </span>
              <Pill color={status.color}>{status.label}</Pill>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** The detail pane, separated from the fetch so it renders on a fixture. */
export function JournalEntry({
  detail,
  onOpenGates,
}: {
  detail: TrainingLogDetail;
  onOpenGates?: (version: string) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[13px] font-semibold text-ink">{detail.version}</span>
            <span className="font-mono text-[9.5px] text-faint">{detail.files.join(' · ')}</span>
          </div>
          {onOpenGates && (
            <button
              type="button"
              onClick={() => { onOpenGates(detail.version); }}
              className="rounded-md border border-line bg-control px-2.5 py-1.5 font-mono text-[10px] text-ink3 hover:text-ink"
            >
              open the gate board for {detail.version} →
            </button>
          )}
        </div>
        {detail.verdictFiles != null && detail.verdictFiles.length > 1 && (
          <p className="mt-2.5 text-[10.5px] leading-relaxed text-muted">
            This cell has {String(detail.verdictFiles.length)} verdict files (
            <span className="font-mono">{detail.verdictFiles.join(', ')}</span>). The API serves one
            — it prefers <span className="font-mono">&#123;VERSION&#125;_VERDICT.md</span> and
            otherwise takes the first alphabetically. The others are named here rather than
            silently dropped.
          </p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card label="Pre-registration">
          {detail.preRegistration == null || detail.preRegistration === '' ? (
            <EmptyNote
              title="No pre-registration"
              detail="This cell has a verdict but no committed-in-advance question. That is the thing the practice exists to prevent — a result with no promise to measure it against."
            />
          ) : (
            <Markdown source={detail.preRegistration} />
          )}
        </Card>
        <Card label="Verdict">
          {detail.verdict == null || detail.verdict === '' ? (
            <EmptyNote
              title="No verdict yet"
              detail="The question was registered; nothing has been written back. A run that never reported is indistinguishable from one that was never run."
            />
          ) : (
            <Markdown source={detail.verdict} />
          )}
        </Card>
      </div>
    </div>
  );
}

export function VictoriaJournal(props: UseCaseViewProps) {
  const journal = useVictoriaJournal();
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const detail = useVictoriaJournalEntry(selected);

  const shown = useMemo(() => {
    const sorted = sortJournal(journal.data ?? []);
    const q = filter.trim().toLowerCase();
    return q ? sorted.filter((e) => e.version.toLowerCase().includes(q)) : sorted;
  }, [journal.data, filter]);

  return (
    <ViewFrame
      title="Journal"
      subtitle="The training log: each version's pre-registration beside the verdict it earned. Written by hand into omega/nodes/victoria/training_log/ and served raw."
      actions={
        <input
          value={filter}
          onChange={(e) => { setFilter(e.target.value); }}
          placeholder="filter versions…"
          aria-label="Filter journal versions"
          className="w-52 rounded-md border border-line bg-control px-2.5 py-1.5 font-mono text-[10.5px] text-ink placeholder:text-ghost focus:border-edge focus:outline-none"
        />
      }
    >
      <div className="flex flex-col gap-4">
        {/* The selected cell sits ABOVE the index, the way the Runs ledger puts
            the selected run above its rows: the index is 118 rows long, and a
            detail pane underneath it would open a document the operator has to
            scroll past the whole log to reach. */}
        {selected !== null &&
          (detail.error ? (
            <Card>
              <ErrorNote error={detail.error} what={`loading ${selected}`} />
            </Card>
          ) : detail.loading || detail.data === null ? (
            <Card>
              <LoadingNote what={`loading ${selected}`} />
            </Card>
          ) : (
            <JournalEntry
              detail={detail.data}
              onOpenGates={(version) => { openGatesFor(version, props.onOpenView); }}
            />
          ))}

        <Async state={journal} what="loading the training log">
          {(entries) =>
            entries.length === 0 ? (
              <Card>
                <EmptyNote
                  title="No training-log entries"
                  detail="The API found no version-stemmed markdown in omega/nodes/victoria/training_log/. Standing docs (README, CAMPAIGN_STATUS) are excluded by the handler."
                />
              </Card>
            ) : (
              <Card
                label={`${String(shown.length)} of ${String(entries.length)} cells`}
                right={<span className="font-mono text-[9.5px] text-faint">/api/v1/training/log</span>}
              >
                {shown.length === 0 ? (
                  <EmptyNote title="No cell matches that filter" />
                ) : (
                  <JournalList
                    entries={shown}
                    selected={selected}
                    onSelect={(v) => { setSelected(v === selected ? null : v); }}
                  />
                )}
              </Card>
            )
          }
        </Async>
      </div>
    </ViewFrame>
  );
}
