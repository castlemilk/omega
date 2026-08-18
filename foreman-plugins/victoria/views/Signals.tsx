/**
 * Signals — what the strategy currently believes, and how much of it is one idea.
 *
 * `GetSignals` gives the latest per-signal snapshot: information coefficient,
 * weight, half-life, conviction, Brier score and trend, plus the composite and
 * its direction. `/api/v1/signals/correlation` gives the rolling pairwise
 * correlation matrix.
 *
 * The two belong on one page because they answer one question. Twelve signals
 * each contributing a weighted vote sounds diversified; if eight of them
 * correlate at 0.9 it is one signal with eight names and the composite's
 * confidence is fictional. The heat grid is there to make that visible.
 *
 * An empty correlation matrix is a *legitimate* 200 — the handler answers with
 * empty arrays and the version it auto-detected when
 * `/tmp/{version}_signal_correlation.json` is absent, which it is unless a run
 * has written one. That is an empty state, not an error, and it says so.
 */
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { HeatGrid } from '../charts.js';
import type { Signal } from '../client.js';
import { ratio } from '../format.js';
import { useVictoriaSignals } from '../hooks.js';
import { Async, Card, EmptyNote, Num, Stat, Table, Txt, ViewFrame } from './chrome.js';

/** Trend arrows, from the proto's free-text `trend` field. */
function trendMark(trend: string | undefined): { glyph: string; tone: string } {
  switch ((trend ?? '').toLowerCase()) {
    case 'up':
    case 'rising':
      return { glyph: '↑', tone: 'text-ok' };
    case 'down':
    case 'falling':
      return { glyph: '↓', tone: 'text-danger' };
    case 'flat':
    case 'stable':
      return { glyph: '→', tone: 'text-ink3' };
    default:
      return { glyph: '—', tone: 'text-faint' };
  }
}

/** Direction colours follow the desk's long/short convention, not the chrome's. */
function directionTone(direction: string | undefined): string {
  switch ((direction ?? '').toUpperCase()) {
    case 'LONG':
      return 'text-ok';
    case 'SHORT':
      return 'text-danger';
    default:
      return 'text-ink3';
  }
}

function SignalTable({ signals }: { signals: readonly Signal[] }) {
  return (
    <Table head={['Signal', 'Value', 'Avg IC', 'Weight', 'Conviction', 'Brier', 'Half-life', 'Trend']}>
      {signals.map((s, i) => {
        const trend = trendMark(s.trend);
        return (
          <tr key={s.name ?? String(i)} className="border-b border-hair last:border-0">
            <Txt className="font-mono font-medium text-ink">
              <span className="flex items-center gap-2">
                <span
                  className="inline-block h-2 w-2 flex-none rounded-full"
                  style={{ background: s.color !== undefined && s.color !== '' ? s.color : 'var(--uc-accent)' }}
                />
                {s.name ?? '—'}
              </span>
            </Txt>
            <Num className="text-ink2">{ratio(s.currentValue, 4)}</Num>
            <Num className="text-ink2">{ratio(s.avgIc, 4)}</Num>
            <Num className="text-ink3">{ratio(s.weight, 3)}</Num>
            <Num className="text-ink2">{ratio(s.conviction, 3)}</Num>
            <Num className="text-ink3">{ratio(s.brierScore, 3)}</Num>
            <Num className="text-ink3">{s.halfLife ? String(s.halfLife) : '—'}</Num>
            <Num className={trend.tone}>{trend.glyph}</Num>
          </tr>
        );
      })}
    </Table>
  );
}

export function VictoriaSignals(_props: UseCaseViewProps) {
  const state = useVictoriaSignals();

  return (
    <ViewFrame
      title="Signals"
      subtitle="The latest sub-signal snapshot and how correlated those signals are with each other — a composite built from signals that all agree is one signal wearing twelve hats."
    >
      <Async state={state} what="loading signals">
        {({ snapshot, correlation }) => {
          const signals = snapshot.signals ?? [];
          return (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <Stat label="Composite" value={ratio(snapshot.compositeScore, 4)} />
                <Stat
                  label="Direction"
                  value={snapshot.compositeDirection ?? '—'}
                  tone={directionTone(snapshot.compositeDirection)}
                />
                <Stat label="OOS Sharpe" value={ratio(snapshot.oosSharpe)} />
                <Stat
                  label="Signals"
                  value={String(signals.length)}
                  hint={`${String(correlation.n_observations)} correlation obs`}
                />
              </div>

              <Card
                label="Sub-signals"
                right={<span className="font-mono text-[9.5px] text-faint">VictoriaService/GetSignals</span>}
              >
                {signals.length === 0 ? (
                  <EmptyNote
                    title="No signal snapshot"
                    detail="GetSignals returned no rows. Signals are written to the victoria tables as the strategy computes them during a run."
                  />
                ) : (
                  <SignalTable signals={signals} />
                )}
              </Card>

              <Card
                label="Signal correlation"
                right={
                  <span className="font-mono text-[9.5px] text-faint">
                    {correlation.version ? `${correlation.version} · ` : ''}
                    {String(correlation.n_observations)} obs
                  </span>
                }
              >
                {correlation.signals.length === 0 ? (
                  <EmptyNote
                    title="No correlation matrix"
                    detail={
                      <>
                        The API answered 200 with an empty matrix
                        {correlation.version ? (
                          <>
                            {' '}for <span className="font-mono">{correlation.version}</span>
                          </>
                        ) : null}
                        {' '}— strategy.py&apos;s SignalCorrelationMonitor writes{' '}
                        <span className="font-mono">/tmp/&#123;version&#125;_signal_correlation.json</span>{' '}
                        during a run, and that file is not present. This is an empty
                        state, not a failure.
                      </>
                    }
                  />
                ) : (
                  <div className="flex flex-col gap-3">
                    <HeatGrid labels={correlation.signals} matrix={correlation.matrix} />
                    <div className="flex items-center gap-3 font-mono text-[9.5px] text-faint">
                      <span>−1</span>
                      {[-4, -3, -2, -1, 0, 1, 2, 3, 4].map((b) => (
                        <span
                          key={b}
                          className="h-3 w-5 rounded-[2px]"
                          style={{
                            background: `rgba(${b < 0 ? '91,157,255' : '232,150,60'},${String(
                              [0.06, 0.18, 0.34, 0.52, 0.72][Math.abs(b)],
                            )})`,
                          }}
                        />
                      ))}
                      <span>+1</span>
                    </div>
                  </div>
                )}
              </Card>

              {signals.length > 0 && (
                <p className="text-[10.5px] leading-relaxed text-muted">
                  Weighted conviction is the composite these feed; the filter pipeline that
                  turns it into a trade (time filter → agreement ratio → weighted conviction →
                  regime/vol gate) is not exposed by any endpoint yet. The conviction funnel is
                  phase-2 work.
                </p>
              )}
            </div>
          );
        }}
      </Async>
    </ViewFrame>
  );
}
