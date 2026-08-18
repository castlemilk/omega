/**
 * Trading-specific formatting.
 *
 * Foreman's `ui/format.ts` already covers the generic cases and this file does
 * not duplicate them — `money`, `percent` and `compactCount` stay there. What
 * lives here is what only a trading desk needs, and what would be wrong
 * elsewhere:
 *
 *   - a PnL figure must carry its sign explicitly, because "+$12" and "$12"
 *     mean different things on a desk and only one of them is a profit;
 *   - `percent` clamps to 0..1, which is right for a progress meter and wrong
 *     for a return that can exceed 100% or go negative;
 *   - a missing number must read as an em dash, not 0.00 — the omega API omits
 *     zero-valued fields, so "absent" and "zero" arrive identically on the wire
 *     and only the caller knows which it is.
 */

/** A number the API may have omitted. */
export type Maybe = number | null | undefined;

function ok(v: Maybe): v is number {
  return v != null && Number.isFinite(v);
}

/** "$1,240.50" — grouped, two decimals. Absent renders as an em dash. */
export function usd(value: Maybe): string {
  if (!ok(value)) return '—';
  const abs = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? '-' : ''}$${abs}`;
}

/** "+$36.80" / "-$225.89" — PnL, always signed. */
export function signedUsd(value: Maybe): string {
  if (!ok(value)) return '—';
  return `${value > 0 ? '+' : ''}${usd(value)}`;
}

/** 0.4032 -> "40.3%". Unclamped and signed-safe, unlike `ui/format.percent`. */
export function pct(fraction: Maybe, digits = 1): string {
  if (!ok(fraction)) return '—';
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** 0.1477 -> "+14.8%", for deltas where direction is the point. */
export function signedPct(fraction: Maybe, digits = 1): string {
  if (!ok(fraction)) return '—';
  return `${fraction > 0 ? '+' : ''}${pct(fraction, digits)}`;
}

/** "1.171" — Sharpe, profit factor, Calmar. Absent (or a 0 that means absent) is an em dash. */
export function ratio(value: Maybe, digits = 2): string {
  if (!ok(value)) return '—';
  return value.toFixed(digits);
}

/** A price, at the precision a sub-dollar alt actually needs. */
export function price(value: Maybe): string {
  if (!ok(value)) return '—';
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 0 : abs >= 1 ? 2 : 5;
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** "+38" / "-4" — signed integer counts, for trade-count deltas. */
export function signedCount(value: Maybe): string {
  if (!ok(value)) return '—';
  return `${value > 0 ? '+' : ''}${String(Math.round(value))}`;
}

/** Foreman token colour for a PnL figure. Flat/absent stays neutral. */
export function pnlClass(value: Maybe): string {
  if (!ok(value) || value === 0) return 'text-ink3';
  return value > 0 ? 'text-ok' : 'text-danger';
}

/**
 * Regime → the chrome's semantic colours.
 *
 * The labels in Victoria's data are `crisis`, `high_vol` and `normal` (NOT
 * bull/bear/chop — that mapping is a documented trap in the omega repo). Anything
 * unrecognised, including the `unknown` the early cycles of a run emit, stays
 * neutral rather than being guessed into a risk colour.
 */
export function regimeColor(regime: string | null | undefined): string {
  switch ((regime ?? '').toLowerCase()) {
    case 'crisis':
      return '#e5675b'; // danger
    case 'high_vol':
      return '#e5c04a'; // warn
    case 'normal':
      return '#4ec97a'; // ok
    default:
      return '#6b6b74'; // muted
  }
}

/** A side as its desk colour: long is ok-green, short is danger-red. */
export function sideColor(side: string | null | undefined): string {
  const s = (side ?? '').toLowerCase();
  if (s === 'long' || s === 'buy') return '#4ec97a';
  if (s === 'short' || s === 'sell') return '#e5675b';
  return '#6b6b74';
}
