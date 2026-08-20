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
 *
 * ── The direction an empty snapshot claims ───────────────────────────────────
 * `GetSignals` on an unseeded database answers `{"compositeDirection":"SHORT"}`
 * and nothing else (see `client.test.ts`). That is not a short position: it is
 * the sign of a composite the strategy never computed, taken by a `> 0 ? LONG :
 * SHORT` upstream where 0 falls to SHORT. Rendering it put a bearish call on the
 * board of a system that had never had an opinion. `snapshotIsAbsent` is the
 * discriminator that stops it, and `snapshotTiles` is where all four tiles get
 * their text so the rule is asserted once rather than inferred from markup.
 */
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { HeatGrid } from '../charts.js';
import type { Signal, SignalsSnapshot } from '../client.js';
import { ratio } from '../format.js';
import type { SignalsData } from '../hooks.js';
import { useVictoriaSignals } from '../hooks.js';
import { Async, Card, EmptyNote, Num, Stat, Table, Txt, ViewFrame } from './chrome.js';

/**
 * Did the strategy actually compute this snapshot?
 *
 * The wire cannot tell a zero apart from an absence, for a number: proto3 JSON
 * omits zero-valued fields, so a genuine composite of 0.0 arrives byte-identical
 * to a missing one. The discriminator therefore cannot be any single number — it
 * is whether the message carries evidence of a computation at all: some signals,
 * or a number that survived the omit-zero rule.
 *
 * `compositeDirection` is deliberately NOT evidence. It is a string, so proto3
 * sends it whatever it holds, and it is precisely the field the server fills in
 * from a score it never had.
 */
export function snapshotIsAbsent(snapshot: SignalsSnapshot): boolean {
  const hasSignals = (snapshot.signals?.length ?? 0) > 0;
  return !hasSignals && snapshot.compositeScore == null && snapshot.oosSharpe == null;
}

/** The four headline tiles' text — one place, so the absence rule is assertable. */
export interface SnapshotTiles {
  composite: string;
  direction: string;
  oosSharpe: string;
  signals: string;
}

/**
 * An absent snapshot reads as four em dashes; a present one reads its numbers,
 * INCLUDING a real zero. Once the message is known to be populated, a number
 * that is missing from it is a number proto3 elided because it was 0 — so
 * `?? 0` there is not a default, it is the decode.
 */
export function snapshotTiles(snapshot: SignalsSnapshot): SnapshotTiles {
  if (snapshotIsAbsent(snapshot)) {
    return { composite: '—', direction: '—', oosSharpe: '—', signals: '—' };
  }
  const direction = snapshot.compositeDirection ?? '';
  return {
    composite: ratio(snapshot.compositeScore ?? 0, 4),
    direction: direction === '' ? '—' : direction,
    oosSharpe: ratio(snapshot.oosSharpe ?? 0),
    signals: String(snapshot.signals?.length ?? 0),
  };
}

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

/** The whole view minus the fetch, so both snapshot states render on a fixture. */
export function SignalsPanel({ snapshot, correlation }: SignalsData) {
  const signals = snapshot.signals ?? [];
  const absent = snapshotIsAbsent(snapshot);
  const tiles = snapshotTiles(snapshot);
  const claimedDirection = snapshot.compositeDirection ?? '';
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label="Composite" value={tiles.composite} />
        <Stat
          label="Direction"
          value={tiles.direction}
          tone={directionTone(absent ? undefined : snapshot.compositeDirection)}
        />
        <Stat label="OOS Sharpe" value={tiles.oosSharpe} />
        <Stat
          label="Signals"
          value={tiles.signals}
          hint={
            absent
              ? 'no snapshot to count'
              : `${String(correlation.n_observations)} correlation obs`
          }
        />
      </div>

      {absent && (
        <p className="text-[10.5px] leading-relaxed text-muted">
          GetSignals answered with an empty snapshot — no signals, no composite,
          no OOS Sharpe — so every tile above reads an em dash rather than a
          number nothing measured.
          {claimedDirection !== '' ? (
            <>
              {' '}The response does carry a{' '}
              <span className="font-mono">compositeDirection</span>, and it is
              deliberately not shown: a direction is the sign of a composite, and
              there is no composite here to take the sign of. It is what the server
              emits when the score it derived the direction from was never computed —
              a <span className="font-mono">&gt; 0</span> test that a missing zero
              loses.
            </>
          ) : null}{' '}
          Signals are written to the victoria tables as the strategy computes them
          during a run.
        </p>
      )}

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
          regime/vol gate) is on the Conviction tab, drawn from the per-cycle decision
          traces a run writes.
        </p>
      )}
    </div>
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
        {(data) => <SignalsPanel {...data} />}
      </Async>
    </ViewFrame>
  );
}
