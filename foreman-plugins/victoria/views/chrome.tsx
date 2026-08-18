/**
 * The furniture every Victoria view shares.
 *
 * Six views that each invent their own loading spinner, error box and empty
 * state is six chances to swallow a `DataSourceError` or to render an empty
 * table that looks identical to a dead backend. So the three states are decided
 * once, here, and every view goes through `<Async>`.
 */
import type { ReactNode } from 'react';
import { Panel, SectionLabel } from '@omega-harness/usecase-kit/ui';
import { DataSourceError } from '@omega-harness/usecase-kit';
import type { Async as AsyncState } from '../hooks.js';

/** A view's outer frame: scrolls, breathes, and carries the page heading. */
export function ViewFrame({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas px-6 py-5">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
            {subtitle != null && (
              <p className="max-w-[70ch] text-[11.5px] leading-relaxed text-muted">{subtitle}</p>
            )}
          </div>
          {actions}
        </div>
        {children}
      </div>
    </div>
  );
}

/** A titled panel with consistent padding. */
export function Card({
  label,
  right,
  children,
  className = '',
}: {
  label?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Panel className={className}>
      {(label != null || right != null) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          {label != null ? <SectionLabel>{label}</SectionLabel> : <span />}
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </Panel>
  );
}

/**
 * A failed request, rendered rather than swallowed.
 *
 * The status and the body excerpt both make it to the screen: "Omega API:
 * GET /api/v1/training/progress failed: 500 failed to parse progress file" is
 * an actionable sentence, and it is exactly what `DataSourceError` already
 * carries. Reducing it to "failed to load" throws that away and sends the
 * operator to devtools, which is what the whole seam exists to avoid.
 */
export function ErrorNote({ error, what }: { error: Error; what?: string }) {
  const isSource = error instanceof DataSourceError;
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-danger/30 bg-danger/10 px-3.5 py-3">
      <div className="font-mono text-[10px] font-semibold uppercase tracking-[.08em] text-danger">
        {what ?? 'request failed'}
        {isSource ? ` · HTTP ${String(error.status)}` : ''}
      </div>
      <div className="break-words font-mono text-[10.5px] leading-relaxed text-danger-tint">
        {isSource && error.bodyExcerpt !== '' ? error.bodyExcerpt : error.message}
      </div>
    </div>
  );
}

/** Nothing to show, said honestly — and saying *why* there is nothing. */
export function EmptyNote({ title, detail }: { title: string; detail?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-9 text-center">
      <div className="text-[12px] font-medium text-ink3">{title}</div>
      {detail != null && (
        <div className="max-w-[56ch] text-[11px] leading-relaxed text-muted">{detail}</div>
      )}
    </div>
  );
}

export function LoadingNote({ what = 'loading' }: { what?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-9 font-mono text-[10.5px] text-faint">
      <span
        className="inline-block h-1.5 w-1.5 animate-bp rounded-full"
        style={{ background: 'var(--uc-accent)' }}
      />
      {what}…
    </div>
  );
}

/**
 * Render one of loading / error / data.
 *
 * `data` still being null after a successful load renders the loading state
 * rather than crashing the view — it is a transient the reducer allows, not a
 * case worth a fourth branch.
 */
export function Async<T>({
  state,
  what,
  children,
}: {
  state: AsyncState<T>;
  what?: string;
  children: (data: T) => ReactNode;
}) {
  if (state.error) return <ErrorNote error={state.error} what={what} />;
  if (state.loading || state.data === null) return <LoadingNote what={what} />;
  return <>{children(state.data)}</>;
}

/** A headline number with its label. The workhorse of the Overview strip. */
export function Stat({
  label,
  value,
  tone = 'text-ink',
  hint,
  children,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-md border border-line bg-card px-3.5 py-3">
      <SectionLabel>{label}</SectionLabel>
      <div className={`truncate font-mono text-[17px] font-semibold tabular-nums ${tone}`}>
        {value}
      </div>
      {hint != null && <div className="truncate font-mono text-[9.5px] text-faint">{hint}</div>}
      {children}
    </div>
  );
}

/** A dense table shell — every Victoria table is this shape. */
export function Table({
  head,
  children,
}: {
  head: readonly string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-line">
            {head.map((h, i) => (
              <th
                key={h}
                className={`whitespace-nowrap px-2.5 py-2 font-mono text-[9.5px] font-semibold uppercase tracking-[.08em] text-faint ${
                  i === 0 ? 'text-left' : 'text-right'
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** A numeric cell: mono, tabular, right-aligned so columns line up. */
export function Num({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <td className={`whitespace-nowrap px-2.5 py-1.5 text-right font-mono tabular-nums ${className}`}>
      {children}
    </td>
  );
}

/** A text cell, left-aligned. */
export function Txt({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <td className={`whitespace-nowrap px-2.5 py-1.5 text-left ${className}`}>{children}</td>;
}
