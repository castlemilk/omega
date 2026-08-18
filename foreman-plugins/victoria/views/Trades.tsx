/**
 * Trades — the trade blotter.
 *
 * Two sources, because neither is complete and joining them would be a fiction:
 *
 *   - `/api/v1/training/trade-details` — the training JSONL written by omega's
 *     `run_training.py`. Carries the decision context: conviction, conviction
 *     score, regime, hold cycles, the filters applied and the full signal
 *     waterfall. Carries **no prices**.
 *   - `VictoriaService/GetTrades` — the `victoria_trades` table. Carries entry,
 *     exit, slippage and duration. Carries **no decision context**.
 *
 * Neither shares a key the other can be joined on, so the view renders whichever
 * has rows — preferring trade-details, since conviction and regime are the
 * reason to look at a blotter rather than a PnL total — and labels which one it
 * drew. Guessing a join would silently attribute one trade's conviction to
 * another trade's fill.
 *
 * MAE/MFE and `sit_out_reason` are in neither source: MAE/MFE is not recorded at
 * all, and `sit_out_reason` is a per-*cycle* field on the progress record, not a
 * per-trade one. Both are named in the phase-2 list rather than shown empty.
 */
import { useMemo } from 'react';
import { clock, Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import type { RpcTrade, TradeDetail } from '../client.js';
import { pct, pnlClass, price, ratio, regimeColor, sideColor, signedUsd } from '../format.js';
import { TRADE_DETAILS_SOURCE, TRADE_RPC_SOURCE, useVictoriaTrades } from '../hooks.js';
import { Async, Card, EmptyNote, ErrorNote, Num, Stat, Table, Txt, ViewFrame } from './chrome.js';

export interface RegimeSummary {
  regime: string;
  trades: number;
  pnl: number;
  wins: number;
}

/**
 * PnL grouped by regime.
 *
 * Regime parity is one of Victoria's six hard gates — a version that makes money
 * overall while bleeding in crisis fails, so the per-regime split is the number
 * that matters, not the total. Rows with no regime label are bucketed under
 * `unknown` rather than dropped, because silently excluding them would make the
 * regime PnLs stop summing to the blotter's total.
 */
export function summariseByRegime(rows: readonly TradeDetail[]): RegimeSummary[] {
  const acc = new Map<string, RegimeSummary>();
  for (const row of rows) {
    const regime = row.regime ?? 'unknown';
    const entry = acc.get(regime) ?? { regime, trades: 0, pnl: 0, wins: 0 };
    const pnl = row.pnl ?? 0;
    entry.trades += 1;
    entry.pnl += pnl;
    if (pnl > 0) entry.wins += 1;
    acc.set(regime, entry);
  }
  return [...acc.values()].sort((a, b) => b.trades - a.trades);
}

function RegimeStrip({ rows }: { rows: readonly TradeDetail[] }) {
  const summary = useMemo(() => summariseByRegime(rows), [rows]);
  if (summary.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
      {summary.map((s) => (
        <Stat
          key={s.regime}
          label={s.regime}
          value={signedUsd(s.pnl)}
          tone={pnlClass(s.pnl)}
          hint={`${String(s.trades)} trades · ${pct(s.trades > 0 ? s.wins / s.trades : 0, 0)} win`}
        >
          <div className="h-[2px] w-full rounded-sm" style={{ background: regimeColor(s.regime) }} />
        </Stat>
      ))}
    </div>
  );
}

function DetailTable({ rows }: { rows: readonly TradeDetail[] }) {
  return (
    <Table head={['Symbol', 'Side', 'Size', 'PnL', 'Conviction', 'Score', 'Regime', 'Held', 'Filters', 'Cycle']}>
      {rows.map((t, i) => (
        <tr key={`${t.symbol ?? '?'}-${String(t.cycle ?? 0)}-${String(i)}`} className="border-b border-hair last:border-0">
          <Txt className="font-mono font-medium text-ink">{t.symbol ?? '—'}</Txt>
          <Num>
            <Pill color={sideColor(t.side)}>{(t.side ?? '—').toUpperCase()}</Pill>
          </Num>
          <Num className="text-ink3">{price(t.size)}</Num>
          <Num className={pnlClass(t.pnl)}>{signedUsd(t.pnl)}</Num>
          <Num className="text-ink2">{t.conviction !== undefined && t.conviction !== '' ? t.conviction : '—'}</Num>
          <Num className="text-ink3">{ratio(t.conviction_score, 3)}</Num>
          <Num>
            <Pill color={regimeColor(t.regime)}>{t.regime ?? '—'}</Pill>
          </Num>
          <Num className="text-ink3">{t.hold_cycles == null ? '—' : String(t.hold_cycles)}</Num>
          <Num className="max-w-[180px] truncate text-ink3" >
            {(t.filters_applied ?? []).length > 0 ? (t.filters_applied ?? []).join(', ') : '—'}
          </Num>
          <Num className="text-faint">{t.cycle == null ? '—' : `#${String(t.cycle)}`}</Num>
        </tr>
      ))}
    </Table>
  );
}

function RpcTable({ rows }: { rows: readonly RpcTrade[] }) {
  return (
    <Table head={['Time', 'Symbol', 'Side', 'Size', 'Entry', 'Exit', 'PnL', 'Slippage', 'Duration']}>
      {rows.map((t, i) => (
        <tr key={`${t.sym ?? '?'}-${t.ts ?? String(i)}`} className="border-b border-hair last:border-0">
          <Txt className="font-mono text-faint">{clock(t.ts)}</Txt>
          <Txt className="font-mono font-medium text-ink">{t.sym ?? '—'}</Txt>
          <Num>
            <Pill color={sideColor(t.side)}>{(t.side ?? '—').toUpperCase()}</Pill>
          </Num>
          <Num className="text-ink3">{price(t.size)}</Num>
          <Num className="text-ink3">{price(t.entry)}</Num>
          <Num className="text-ink2">{price(t.exitPrice)}</Num>
          <Num className={pnlClass(t.pnl)}>{signedUsd(t.pnl)}</Num>
          <Num className="text-ink3">{ratio(t.slippage, 4)}</Num>
          <Num className="text-ink3">{t.duration !== undefined && t.duration !== '' ? t.duration : '—'}</Num>
        </tr>
      ))}
    </Table>
  );
}

export function VictoriaTrades(_props: UseCaseViewProps) {
  const state = useVictoriaTrades();

  return (
    <ViewFrame
      title="Trades"
      subtitle="Closed trades, with the decision context behind them where the training run recorded it."
    >
      <Async state={state} what="loading trades">
        {({ details, rpc, failures }) => {
          // A source that failed is not a source that is empty. Claiming
          // "neither has rows" over a 500 sends the operator looking for a
          // seeding problem that isn't there, so the failure is named — with
          // its status and body excerpt, via the shared ErrorNote — and the
          // empty state only claims what it can actually see.
          const failureNotes = failures.map((f) => (
            <ErrorNote key={f.source} error={f.error} what={`${f.source} failed`} />
          ));

          if (details.length === 0 && rpc.length === 0) {
            const surviving = failures.length === 1
              ? failures[0].source === TRADE_DETAILS_SOURCE
                ? 'The victoria_trades table returned no rows, and the other source failed:'
                : "The training run's trade-details JSONL returned no rows, and the other source failed:"
              : null;
            return (
              <Card>
                <div className="flex flex-col gap-3">
                  <EmptyNote
                    title={failures.length > 0 ? 'No trades to show' : 'No trades'}
                    detail={
                      surviving ??
                      "Neither the training run's trade-details JSONL nor the victoria_trades table has rows. Both fill in during a paper or live run."
                    }
                  />
                  {failureNotes}
                </div>
              </Card>
            );
          }

          const useDetails = details.length > 0;
          return (
            <div className="flex flex-col gap-4">
              {failureNotes}
              {useDetails && <RegimeStrip rows={details} />}
              <Card
                label={`${String(useDetails ? details.length : rpc.length)} trades`}
                right={
                  <span className="font-mono text-[9.5px] text-faint">
                    {useDetails ? TRADE_DETAILS_SOURCE : TRADE_RPC_SOURCE}
                  </span>
                }
              >
                {useDetails ? <DetailTable rows={details} /> : <RpcTable rows={rpc} />}
              </Card>
              {useDetails && rpc.length > 0 && (
                <p className="font-mono text-[9.5px] text-faint">
                  {String(rpc.length)} rows also present in victoria_trades with fill prices;
                  the two sources share no join key, so they are not merged.
                </p>
              )}
            </div>
          );
        }}
      </Async>
    </ViewFrame>
  );
}
