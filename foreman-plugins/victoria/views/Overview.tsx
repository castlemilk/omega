/**
 * Overview — the desk at a glance.
 *
 * Portfolio value, cash, exposure and day PnL across the top; open positions
 * below; a compact equity sparkline beside the headline.
 *
 * The empty state is the one that matters here. A fresh checkout has no
 * `victoria_*` rows, so every one of these RPCs answers `{}` — and a zeroed
 * portfolio drawn as though it were real ("$0.00, 0 positions, flat") is a lie
 * that reads as a working desk with nothing on it. So an empty portfolio says
 * so, in words, and names what would fill it.
 */
import { Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { Sparkline } from '../charts.js';
import type { Portfolio, Position } from '../client.js';
import { pct, pnlClass, price, ratio, sideColor, signedUsd, usd } from '../format.js';
import { useVictoriaOverview } from '../hooks.js';
import { Async, Card, EmptyNote, Num, Stat, Table, Txt, ViewFrame } from './chrome.js';

/**
 * Whether the desk has anything at all.
 *
 * Deliberately generous: any one of a value, a position or a realised PnL means
 * there IS a book, and the view should render it. Only the complete absence of
 * all three is the "no live portfolio" state.
 */
function hasBook(portfolio: Portfolio, positions: Position[]): boolean {
  return (
    positions.length > 0 ||
    (portfolio.portfolioValue ?? 0) !== 0 ||
    (portfolio.totalPnl ?? 0) !== 0 ||
    (portfolio.realisedPnl ?? 0) !== 0
  );
}

/** Cash is the allocation slice the omega dashboard calls "USDT Cash". */
function cashOf(portfolio: Portfolio): number | null {
  const slice = (portfolio.allocation ?? []).find((a) =>
    (a.name ?? '').toLowerCase().includes('cash'),
  );
  return slice?.value ?? null;
}

export function VictoriaOverview({ onOpenView }: UseCaseViewProps) {
  const state = useVictoriaOverview();

  return (
    <ViewFrame
      title="Overview"
      subtitle="The live book, straight off the omega API's VictoriaService — portfolio, open risk and today's PnL."
    >
      <Async state={state} what="loading portfolio">
        {({ portfolio, pnl, positions, equity }) => {
          if (!hasBook(portfolio, positions)) {
            return (
              <Card>
                <EmptyNote
                  title="No live portfolio"
                  detail={
                    <>
                      Victoria writes these tables during paper and live runs; this
                      database has none yet, so the API answered with an empty book
                      rather than failing. Completed training runs are still
                      readable —{' '}
                      <button
                        type="button"
                        className="underline decoration-dotted underline-offset-2 hover:text-ink2"
                        onClick={() => { onOpenView('victoria-runs'); }}
                      >
                        open the run ledger
                      </button>
                      .
                    </>
                  }
                />
              </Card>
            );
          }

          const exposure = positions.reduce((sum, p) => sum + Math.abs(p.notional ?? 0), 0);
          const cash = cashOf(portfolio);
          const equitySeries = (equity.points ?? [])
            .map((p) => p.omega ?? 0)
            .filter((v) => Number.isFinite(v));

          return (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <Stat
                  label="Portfolio value"
                  value={usd(portfolio.portfolioValue)}
                  hint={`return ${pct(portfolio.totalReturn)}`}
                />
                <Stat label="Cash" value={cash === null ? '—' : usd(cash)} hint="unallocated" />
                <Stat
                  label="Exposure"
                  value={usd(exposure)}
                  hint={`${String(positions.length)} position${positions.length === 1 ? '' : 's'}`}
                />
                <Stat
                  label="Unrealised PnL"
                  value={signedUsd(pnl.unrealisedPnl ?? portfolio.unrealisedPnl)}
                  tone={pnlClass(pnl.unrealisedPnl ?? portfolio.unrealisedPnl)}
                  hint={`realised ${signedUsd(pnl.realisedPnl ?? portfolio.realisedPnl)}`}
                />
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
                <Card
                  label="Open positions"
                  right={
                    <span className="font-mono text-[9.5px] text-faint">
                      VictoriaService/GetPositions
                    </span>
                  }
                >
                  {positions.length === 0 ? (
                    <EmptyNote
                      title="Flat"
                      detail="The book has a value but no open positions — everything is in cash."
                    />
                  ) : (
                    <Table head={['Symbol', 'Side', 'Size', 'Entry', 'Mark', 'uPnL', '%', 'Notional', 'Lev', 'VaR95']}>
                      {positions.map((p, i) => (
                        <tr key={`${p.sym ?? '?'}-${String(i)}`} className="border-b border-hair last:border-0">
                          <Txt className="font-mono font-medium text-ink">{p.sym ?? '—'}</Txt>
                          <Num>
                            <Pill color={sideColor(p.side)}>{(p.side ?? '—').toUpperCase()}</Pill>
                          </Num>
                          <Num className="text-ink2">{price(p.size)}</Num>
                          <Num className="text-ink3">{price(p.entry)}</Num>
                          <Num className="text-ink2">{price(p.mark)}</Num>
                          <Num className={pnlClass(p.upnl)}>{signedUsd(p.upnl)}</Num>
                          <Num className={pnlClass(p.pct)}>{pct(p.pct)}</Num>
                          <Num className="text-ink3">{usd(p.notional)}</Num>
                          <Num className="text-ink3">{ratio(p.leverage, 1)}×</Num>
                          <Num className="text-ink3">{usd(p.var95)}</Num>
                        </tr>
                      ))}
                    </Table>
                  )}
                </Card>

                <div className="flex flex-col gap-4">
                  <Card
                    label="Equity"
                    right={
                      <button
                        type="button"
                        className="font-mono text-[9.5px] text-faint underline decoration-dotted underline-offset-2 hover:text-ink3"
                        onClick={() => { onOpenView('victoria-equity'); }}
                      >
                        full curve →
                      </button>
                    }
                  >
                    {equitySeries.length < 2 ? (
                      <EmptyNote title="No equity curve yet" />
                    ) : (
                      <div className="flex flex-col gap-2">
                        <Sparkline
                          values={equitySeries}
                          width={280}
                          height={54}
                          color="var(--uc-accent)"
                          label="equity curve"
                        />
                        <div className="font-mono text-[9.5px] text-faint">
                          {String(equitySeries.length)} points · last {usd(equitySeries[equitySeries.length - 1])}
                        </div>
                      </div>
                    )}
                  </Card>

                  <Card label="Risk">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[10.5px]">
                      {[
                        ['Sharpe', ratio(pnl.sharpe ?? portfolio.sharpe)],
                        ['Sortino', ratio(pnl.sortino)],
                        ['Max DD', pct(pnl.maxDd)],
                        ['Calmar', ratio(pnl.calmar)],
                        ['Win rate', pct(pnl.winRate ?? portfolio.winRate)],
                        ['Profit factor', ratio(pnl.profitFactor ?? portfolio.profitFactor)],
                        ['VaR 95', usd(pnl.var95)],
                        ['CVaR 95', usd(pnl.cvar95)],
                      ].map(([label, value]) => (
                        <div key={label} className="flex items-baseline justify-between gap-2">
                          <span className="text-faint">{label}</span>
                          <span className="tabular-nums text-ink2">{value}</span>
                        </div>
                      ))}
                    </div>
                  </Card>
                </div>
              </div>
            </div>
          );
        }}
      </Async>
    </ViewFrame>
  );
}
