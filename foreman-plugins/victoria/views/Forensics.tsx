/**
 * Forensics — why one run beat another.
 *
 * `omega/tools/forensics/run_diff.py` diffs two training runs and writes
 * `data/{baseline}-{target}-forensics.json`: ranked hypotheses with their
 * evidence, per-symbol PnL deltas, a conviction histogram for each side, the
 * per-regime breakdown, and every trade the baseline took that the target did
 * not. This view is that document, ordered so the answer comes first.
 *
 * ── The quirk that shapes this whole file ────────────────────────────────────
 * The report's internal keys are **not** the versions being compared. Every
 * paired report in the omega data directory — `v93-v94`, `v48-v50`, `v35-v48` —
 * keys `baselines`, `conviction_histogram` and `regime_breakdown` on the literal
 * strings `v35` and `v48`, because those are the tool's own hard-coded labels
 * (the same class of bug as the gate module's `v48_summary`/`v49_summary`). The
 * real names live in `baselines[key].version`: open `v93-v94-forensics.json` and
 * `baselines.v35.version` is `"v93"`.
 *
 * So nothing here indexes by the filename pair. The two keys are taken from the
 * object's own insertion order — JSON.parse preserves it for non-numeric keys,
 * and the writer emits baseline first — and every label shown to the operator is
 * read out of `.version`, with the raw key disclosed beside it so the mismatch
 * is visible rather than papered over.
 */
import { useState } from 'react';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { GroupedBarChart } from '../charts.js';
import type { ForensicsEntry, ForensicsReport } from '../client.js';
import { pct, pnlClass, ratio, regimeColor, signedUsd, usd } from '../format.js';
import { useVictoriaForensics, useVictoriaForensicsList } from '../hooks.js';
import { Async, Card, EmptyNote, Num, Stat, Table, Txt, ViewFrame } from './chrome.js';

/**
 * The report's two side keys, baseline first, or null when it carries neither.
 *
 * Insertion order is the contract — see the header. `conviction_histogram` is
 * the fallback source because a report can in principle carry histograms
 * without summaries, and either one alone still names the two sides.
 */
export function reportKeys(report: ForensicsReport): [string, string] | null {
  const keys = Object.keys(report.baselines ?? {});
  const fallback = Object.keys(report.conviction_histogram ?? {});
  const use = keys.length >= 2 ? keys : fallback;
  if (use.length < 2) return null;
  return [use[0], use[1]];
}

/** The version a side really is, falling back to the tool's internal key. */
export function sideLabel(report: ForensicsReport, key: string): string {
  return report.baselines?.[key]?.version ?? key;
}

export interface SymbolDelta {
  symbol: string;
  delta: number;
}

/**
 * Per-symbol PnL deltas, biggest movers first.
 *
 * Sorted by magnitude, not by value: the question is what produced the
 * difference, and a −$60 symbol and a +$60 symbol are equally answers to it.
 */
export function symbolDeltas(report: ForensicsReport): SymbolDelta[] {
  const per = report.signal_contribution_delta_proxy?.per_symbol ?? {};
  return Object.entries(per)
    .map(([symbol, delta]) => ({ symbol, delta }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.symbol.localeCompare(b.symbol));
}

export interface RegimeRow {
  regime: string;
  baseline?: number;
  candidate?: number;
  delta?: number;
}

/**
 * The per-regime breakdown.
 *
 * The inner field names are built out of the report’s own keys (`v35_pnl`, `v48_pnl`),
 * so they are derived rather than written down — hard-coding `v48_pnl` would
 * work on every report in the repo today and break the moment the tool is run
 * with differently-named inputs.
 */
export function regimeRows(report: ForensicsReport, keys: [string, string] | null): RegimeRow[] {
  const breakdown = report.regime_breakdown ?? {};
  return Object.entries(breakdown).map(([regime, values]) => ({
    regime,
    baseline: keys ? values[`${keys[0]}_pnl`] : undefined,
    candidate: keys ? values[`${keys[1]}_pnl`] : undefined,
    delta: values.delta,
  }));
}

/** The three histogram measures worth comparing side by side. */
export function histogramGroups(
  report: ForensicsReport,
  keys: [string, string] | null,
): { label: string; values: number[] }[] {
  if (!keys) return [];
  const a = report.conviction_histogram?.[keys[0]];
  const b = report.conviction_histogram?.[keys[1]];
  if (!a || !b) return [];
  return [
    { label: 'trade band', values: [a.trade_band_count ?? 0, b.trade_band_count ?? 0] },
    { label: 'hold band', values: [a.hold_band_count ?? 0, b.hold_band_count ?? 0] },
  ];
}

export interface HistogramRow {
  label: string;
  kind: 'ratio' | 'pct';
  baseline?: number;
  candidate?: number;
}

/** The histogram measures worth reading as numbers rather than as bars. */
export function histogramRows(
  report: ForensicsReport,
  keys: [string, string] | null,
): HistogramRow[] {
  const a = keys ? report.conviction_histogram?.[keys[0]] : undefined;
  const b = keys ? report.conviction_histogram?.[keys[1]] : undefined;
  if (!a && !b) return [];
  return [
    { label: 'hold threshold', kind: 'ratio', baseline: a?.hold_threshold, candidate: b?.hold_threshold },
    { label: 'mean conviction', kind: 'ratio', baseline: a?.mean_conviction, candidate: b?.mean_conviction },
    { label: 'max conviction', kind: 'ratio', baseline: a?.max_conviction, candidate: b?.max_conviction },
    { label: 'trade band share', kind: 'pct', baseline: a?.trade_band_pct, candidate: b?.trade_band_pct },
  ];
}

function HypothesisCard({
  rank,
  claim,
  confidence,
  evidence,
}: {
  rank?: number;
  claim?: string;
  confidence?: number;
  evidence?: string[];
}) {
  return (
    <div className="flex gap-3 rounded-md border border-line bg-card px-3.5 py-3">
      <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-control font-mono text-[10px] text-ink2">
        {rank ?? '?'}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <p className="text-[11.5px] leading-relaxed text-ink2">{claim ?? '(no claim recorded)'}</p>
        <div className="flex flex-wrap items-center gap-3 font-mono text-[9.5px] text-faint">
          <span>confidence {ratio(confidence, 3)}</span>
          {(evidence ?? []).map((ref) => (
            <span key={ref} className="rounded-[3px] bg-cardAlt px-1.5 py-0.5 text-ink3">
              {ref}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The report, separated from the fetch so it renders on a fixture. */
export function ForensicsReportView({
  report,
  file,
}: {
  report: ForensicsReport;
  file: string;
}) {
  const keys = reportKeys(report);
  const baselineKey = keys?.[0];
  const targetKey = keys?.[1];
  const baseline = baselineKey != null ? report.baselines?.[baselineKey] : undefined;
  const candidate = targetKey != null ? report.baselines?.[targetKey] : undefined;
  const baselineName = baselineKey != null ? sideLabel(report, baselineKey) : 'baseline';
  const targetName = targetKey != null ? sideLabel(report, targetKey) : 'target';
  const symbols = symbolDeltas(report);
  const regimes = regimeRows(report, keys);
  const groups = histogramGroups(report, keys);
  const hypotheses = [...(report.hypotheses ?? [])].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const skipped = report.skipped_trades ?? [];
  const pnlDelta =
    typeof baseline?.pnl === 'number' && typeof candidate?.pnl === 'number'
      ? candidate.pnl - baseline.pnl
      : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label={`${baselineName} PnL`} value={usd(baseline?.pnl)} tone={pnlClass(baseline?.pnl)} hint={`${String(baseline?.trades ?? '—')} trades`} />
        <Stat label={`${targetName} PnL`} value={usd(candidate?.pnl)} tone={pnlClass(candidate?.pnl)} hint={`${String(candidate?.trades ?? '—')} trades`} />
        <Stat label="PnL delta" value={signedUsd(pnlDelta)} tone={pnlClass(pnlDelta)} />
        <Stat
          label="Skipped trades"
          value={String(skipped.length)}
          hint="baseline entries the target never took"
        />
      </div>

      {keys && (baseline?.version !== undefined || candidate?.version !== undefined) && (
        <p className="font-mono text-[9.5px] leading-relaxed text-faint">
          The report keys its two sides as <span className="text-ink3">{keys[0]}</span> and{' '}
          <span className="text-ink3">{keys[1]}</span> — run_diff.py&apos;s own hard-coded labels,
          which are not the versions compared. The real labels above come from each side&apos;s{' '}
          <span className="text-ink3">version</span> field. Source file:{' '}
          <span className="text-ink3">{file}</span>
          {report.generated_at != null ? ` · generated ${report.generated_at}` : ''}
        </p>
      )}

      <Card label={`Ranked hypotheses (${String(hypotheses.length)})`}>
        {hypotheses.length === 0 ? (
          <EmptyNote
            title="No hypotheses in this report"
            detail="run_diff.py emits hypotheses only when it finds evidence to rank; an empty list is a real answer."
          />
        ) : (
          <div className="flex flex-col gap-2.5">
            {hypotheses.map((h, i) => (
              <HypothesisCard
                key={i}
                rank={h.rank}
                claim={h.claim}
                confidence={h.confidence}
                evidence={h.evidence_refs}
              />
            ))}
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          label="Per-symbol PnL delta"
          right={<span className="font-mono text-[9.5px] text-faint">largest movers first</span>}
        >
          {symbols.length === 0 ? (
            <EmptyNote title="No per-symbol deltas" />
          ) : (
            <div className="flex flex-col gap-2">
              <Table head={['Symbol', 'Δ PnL']}>
                {symbols.map((s) => (
                  <tr key={s.symbol} className="border-b border-hair last:border-0">
                    <Txt className="font-mono font-medium text-ink">{s.symbol}</Txt>
                    <Num className={pnlClass(s.delta)}>{signedUsd(s.delta)}</Num>
                  </tr>
                ))}
              </Table>
              {report.signal_contribution_delta_proxy?.note != null && (
                <p className="text-[10px] leading-relaxed text-muted">
                  {report.signal_contribution_delta_proxy.note}
                </p>
              )}
            </div>
          )}
        </Card>

        <Card label="Conviction histogram">
          {groups.length === 0 ? (
            <EmptyNote title="No conviction histogram in this report" />
          ) : (
            <div className="flex flex-col gap-3">
              <GroupedBarChart
                groups={groups}
                seriesLabels={[baselineName, targetName]}
                seriesColors={['#5b9dff', '#e8963c']}
                formatValue={(v) => String(v)}
              />
              <Table head={['Measure', baselineName, targetName]}>
                {histogramRows(report, keys).map((row) => (
                  <tr key={row.label} className="border-b border-hair last:border-0">
                    <Txt className="font-mono text-ink3">{row.label}</Txt>
                    <Num className="text-ink2">
                      {row.kind === 'pct' ? pct(row.baseline, 2) : ratio(row.baseline, 4)}
                    </Num>
                    <Num className="text-ink2">
                      {row.kind === 'pct' ? pct(row.candidate, 2) : ratio(row.candidate, 4)}
                    </Num>
                  </tr>
                ))}
              </Table>
            </div>
          )}
        </Card>
      </div>

      <Card label="Per-regime breakdown">
        {regimes.length === 0 ? (
          <EmptyNote title="No regime breakdown in this report" />
        ) : (
          <Table head={['Regime', baselineName, targetName, 'Δ']}>
            {regimes.map((r) => (
              <tr key={r.regime} className="border-b border-hair last:border-0">
                <Txt className="font-mono text-ink2">
                  <span className="flex items-center gap-2">
                    <span
                      className="inline-block h-2 w-2 flex-none rounded-full"
                      style={{ background: regimeColor(r.regime) }}
                    />
                    {r.regime}
                  </span>
                </Txt>
                <Num className={pnlClass(r.baseline)}>{usd(r.baseline)}</Num>
                <Num className={pnlClass(r.candidate)}>{usd(r.candidate)}</Num>
                <Num className={pnlClass(r.delta)}>{signedUsd(r.delta)}</Num>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card label={`Skipped trades (${String(skipped.length)})`}>
        {skipped.length === 0 ? (
          <EmptyNote title="No skipped trades recorded" />
        ) : (
          <details>
            <summary className="cursor-pointer font-mono text-[10.5px] text-ink3 hover:text-ink">
              {String(skipped.length)} baseline entries the target never took — expand
            </summary>
            <div className="mt-3">
              <Table head={['Cycle', 'Symbol', 'Side', 'Baseline PnL', 'Conviction', 'Regime', 'Reason']}>
                {skipped.map((s, i) => (
                  <tr key={i} className="border-b border-hair last:border-0">
                    <Txt className="font-mono text-ink3">{String(s.cycle ?? '—')}</Txt>
                    <Txt className="font-mono text-ink2">{s.symbol ?? '—'}</Txt>
                    <Txt className="font-mono text-ink3">{s.side ?? '—'}</Txt>
                    <Num className={pnlClass(s.baseline_pnl)}>{signedUsd(s.baseline_pnl)}</Num>
                    <Num className="text-ink3">{ratio(s.baseline_conviction, 4)}</Num>
                    <Txt className="font-mono text-ink3">{s.baseline_regime ?? '—'}</Txt>
                    <Txt className="font-mono text-faint">{s.reason ?? '—'}</Txt>
                  </tr>
                ))}
              </Table>
            </div>
          </details>
        )}
      </Card>
    </div>
  );
}

/** The picker: every paired report the API found, plus the ones it could not pair. */
export function ForensicsList({
  entries,
  unpaired,
  selected,
  onSelect,
}: {
  entries: readonly ForensicsEntry[];
  unpaired: readonly string[];
  selected: string | null;
  onSelect: (entry: ForensicsEntry) => void;
}) {
  return (
    <Card
      label={`${String(entries.length)} forensics report${entries.length === 1 ? '' : 's'}`}
      right={<span className="font-mono text-[9.5px] text-faint">/api/v1/training/forensics</span>}
    >
      {entries.length === 0 ? (
        <EmptyNote
          title="No forensics reports"
          detail="omega/tools/forensics/run_diff.py writes data/{baseline}-{target}-forensics.json. None are present."
        />
      ) : (
        <div className="flex flex-col gap-3">
          <Table head={['Baseline → target', 'File', 'Size', 'Modified']}>
            {entries.map((e) => (
              <tr
                key={e.file}
                onClick={() => { onSelect(e); }}
                className={`cursor-pointer border-b border-hair last:border-0 hover:bg-cardAlt ${
                  e.file === selected ? 'bg-cardAlt' : ''
                }`}
              >
                <Txt className="font-mono font-medium text-ink">
                  {e.baseline} <span className="text-ghost">→</span> {e.target}
                </Txt>
                <Txt className="font-mono text-ink3">{e.file}</Txt>
                <Num className="text-ink3">{`${(e.size_bytes / 1024).toFixed(1)} KB`}</Num>
                <Num className="text-faint">{e.modified_at}</Num>
              </tr>
            ))}
          </Table>
          {unpaired.length > 0 && (
            <p className="text-[10.5px] leading-relaxed text-muted">
              {String(unpaired.length)} file{unpaired.length === 1 ? '' : 's'} in the data directory
              end in <span className="font-mono">forensics.json</span> without the{' '}
              <span className="font-mono">&#123;baseline&#125;-&#123;target&#125;</span> naming and
              are not openable here:{' '}
              <span className="font-mono text-ink3">{unpaired.join(', ')}</span>. They are different
              documents — <span className="font-mono">v240_universe_forensics.json</span> is a
              universe-selection sweep, not a run diff.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

export function VictoriaForensics(_props: UseCaseViewProps) {
  const list = useVictoriaForensicsList();
  const [pair, setPair] = useState<{ baseline: string; target: string; file: string } | null>(null);
  const report = useVictoriaForensics(pair?.baseline ?? null, pair?.target ?? null);

  return (
    <ViewFrame
      title="Forensics"
      subtitle="Two runs, diffed: ranked hypotheses first, then the per-symbol and per-regime evidence they were ranked from. Produced by omega/tools/forensics/run_diff.py, not computed here."
    >
      <div className="flex flex-col gap-4">
        <Async state={list} what="loading forensics reports">
          {(data) => (
            <ForensicsList
              entries={data.forensics}
              unpaired={data.unpaired}
              selected={pair?.file ?? null}
              onSelect={(e) => {
                setPair(
                  pair?.file === e.file
                    ? null
                    : { baseline: e.baseline, target: e.target, file: e.file },
                );
              }}
            />
          )}
        </Async>

        {pair !== null && (
          <Async state={report} what={`loading ${pair.file}`}>
            {(data) =>
              data === null ? (
                <Card>
                  <EmptyNote title="No report selected" />
                </Card>
              ) : (
                <ForensicsReportView report={data.forensics} file={data.file} />
              )
            }
          </Async>
        )}
      </div>
    </ViewFrame>
  );
}
