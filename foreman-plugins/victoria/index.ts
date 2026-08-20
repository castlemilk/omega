/**
 * The Victoria use-case shell — UC-3, the first real domain plugin.
 *
 * Victoria is omega's autonomous crypto quant system. An objective carrying
 * `useCase: 'victoria'` gets ten domain tabs alongside the core chrome, all
 * reading the omega Go API on :8080 through the shell's own typed client in
 * `./client.ts`.
 *
 * This module is the manifest and nothing else. It **must not fetch**: a
 * registered shell that no objective has selected has to cost zero requests, so
 * everything here is data, the client is only constructed (not called), and
 * every request originates in a view's hook. `registry.ts` never learns an
 * endpoint.
 */
import type { UseCaseShell } from '@omega-harness/usecase-kit';
import { OMEGA_SOURCE } from './client.js';
import { VictoriaOverview } from './views/Overview.js';
import { VictoriaRuns } from './views/Runs.js';
import { VictoriaLive } from './views/Live.js';
import { VictoriaTrades } from './views/Trades.js';
import { VictoriaEquity } from './views/Equity.js';
import { VictoriaSignals } from './views/Signals.js';
import { VictoriaGates } from './views/Gates.js';
import { VictoriaConviction } from './views/Conviction.js';
import { VictoriaForensics } from './views/Forensics.js';
import { VictoriaJournal } from './views/Journal.js';

/**
 * The accent.
 *
 * `projects/victoria.yaml` in the omega repo declares `metadata.color:
 * "#00ff00"`. That is pure sRGB green — on Foreman's near-black canvas it
 * vibrates against the text ramp and reads as a terminal error colour rather
 * than a desk. So the hue is kept and the value is brought onto the palette's
 * own green (`ok` is #4ec97a), landing on a saturated trading green that is
 * recognisably Victoria's colour and legible next to `ink`. Changing the YAML
 * upstream is the way to change this; it is not read at runtime because the
 * harness has no dependency on the omega repo's files.
 */
export const VICTORIA_ACCENT = '#3fd97d';

export const victoriaUseCase: UseCaseShell = {
  id: 'victoria',
  name: 'Victoria — market trading',
  // Hardcoded, and deliberately: `./package.json` declares `"version":
  // "0.1.0"`, but a manifest is a pure export that a browser bundle imports —
  // it has no filesystem to read the file from, and giving it one would make
  // registration cost I/O. Bump both together; `manifest-cost.test.ts` is the
  // test that keeps this module data-only.
  version: '0.1.0',
  description:
    'Market trading over the omega engine — training runs and their gates, ' +
    'live desk state, per-trade and equity detail, signal and conviction ' +
    'breakdowns, run-to-run forensics, and the training journal.',
  accent: VICTORIA_ACCENT,
  // Only 'harness' is renamed. A Victoria harness really is a desk agent, and
  // the word survives contact with the rest of the chrome ("spawn a desk
  // agent", "3 desk agents working"). 'pulse' and 'objective' are left alone —
  // no trading word improves on them, and renaming for the sake of it makes the
  // app harder to talk about across two objectives in the same project.
  vocabulary: { harness: 'desk agent' },
  views: [
    { id: 'victoria-overview', label: 'Overview', order: 10, component: VictoriaOverview },
    { id: 'victoria-runs', label: 'Runs', order: 20, component: VictoriaRuns },
    { id: 'victoria-live', label: 'Live', order: 30, component: VictoriaLive },
    { id: 'victoria-trades', label: 'Trades', order: 40, component: VictoriaTrades },
    { id: 'victoria-equity', label: 'Equity', order: 50, component: VictoriaEquity },
    { id: 'victoria-signals', label: 'Signals', order: 60, component: VictoriaSignals },
    // Phase 2. The order is the order a run is actually read in: did it ship
    // (Gates), why did it trade what it traded (Conviction), what changed
    // against the run before it (Forensics), and what did we say we were
    // testing (Journal) — the narrative last, because it is the thing that
    // links back to the first.
    { id: 'victoria-gates', label: 'Gates', order: 70, component: VictoriaGates },
    { id: 'victoria-conviction', label: 'Conviction', order: 80, component: VictoriaConviction },
    { id: 'victoria-forensics', label: 'Forensics', order: 90, component: VictoriaForensics },
    { id: 'victoria-journal', label: 'Journal', order: 100, component: VictoriaJournal },
  ],
  dataSources: [OMEGA_SOURCE],
};
