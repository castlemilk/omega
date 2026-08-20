/**
 * The Polymarket use-case shell — UC-4, the second domain, and the one that
 * proves the seam is a seam rather than Victoria's plumbing with a registry
 * bolted on.
 *
 * It is deliberately a **stub**, and the shape of the stub is the point. A
 * use-case shell is not allowed to require a backend: Polymarket has real nodes
 * (`omega/nodes/polymarket/` — weather ensembles, CLOB pricing, edge detection,
 * vol arb) and a real project definition, but nothing serves any of it over
 * HTTP. `cmd/omega-api` and `internal/handler` in the omega repo register no
 * Connect service and no REST route for polymarket (checked 2026-08-18), so:
 *
 *   - `dataSources` is absent, not a hopeful entry pointing at :8080. The chrome
 *     therefore shows no health dot for this shell, which is correct — there is
 *     no backend whose health could be reported.
 *   - There is one view, and it renders the configuration plus a named phase-2
 *     list rather than a plausible dashboard of zeroes.
 *
 * Like Victoria's, this module is the manifest and nothing else: data only, no
 * client constructed, no fetch. Registered by the roster in `../index.ts`.
 */
import type { UseCaseShell } from '@omega-harness/usecase-kit';
import { PolymarketPipeline } from './views/Pipeline.js';

/**
 * The accent.
 *
 * `projects/polymarket.yaml` carries no `metadata.color` (unlike
 * `victoria.yaml`, which declares `#00ff00`), so there is nothing upstream to
 * bring onto the palette. This is Foreman's own `violet` token
 * (`tailwind.config.js`), picked because it is the one accent in the palette
 * that no status colour uses — green, amber and red all mean something on a
 * harness, and a domain accent that collides with a status reads as an alarm.
 * It also sits far from Victoria's green, so two objectives open side by side
 * are told apart by colour alone.
 */
export const POLYMARKET_ACCENT = '#a67ff0';

export const polymarketUseCase: UseCaseShell = {
  id: 'polymarket',
  // `projects/polymarket.yaml` declares `name: Polymarket` and
  // `domain: prediction_markets`; the shell name is both, in Victoria's
  // "<name> — <what it is>" form.
  name: 'Polymarket — prediction markets',
  // Same rule as Victoria's: the string `./package.json` carries, hardcoded,
  // because the manifest never touches a filesystem.
  version: '0.1.0',
  // Honest, because the Plugins surface is where someone decides whether to
  // start an objective on this shell. The nodes exist in the omega repo; what
  // does not exist is anything serving them over HTTP, so the one tab shows the
  // configuration and the named phase-2 list and claims nothing else.
  description:
    'Prediction markets — a stub. The omega nodes exist but nothing serves ' +
    'them over HTTP yet, so the single tab shows the configuration and what ' +
    'phase 2 would add, and the shell declares no backend.',
  accent: POLYMARKET_ACCENT,
  // No vocabulary. Victoria renames 'harness' to 'desk agent' because a
  // Victoria harness genuinely is one and the word survives everywhere the
  // chrome uses it. Nothing in prediction markets improves on harness, pulse or
  // objective, and renaming for symmetry with Victoria would make the app
  // harder to talk about across two objectives in one project.
  views: [{ id: 'polymarket-pipeline', label: 'Pipeline', order: 10, component: PolymarketPipeline }],
  // dataSources: intentionally omitted — see the module comment.
};

