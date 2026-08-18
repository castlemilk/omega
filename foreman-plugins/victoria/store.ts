/**
 * Victoria's own cross-view state — one version, shared by four views.
 *
 * ── Why this exists ──────────────────────────────────────────────────────────
 * The guest contract cannot carry it. `UseCaseViewProps.onOpenView` takes a view
 * id and nothing else (`onOpenView: (viewId: string) => void`, see the kit's
 * `shell.ts`), so "open the Gates board **for V270**" has no channel — and
 * widening that signature is a real Foreman API decision, not a shell's to make.
 * Nor can React context help: Foreman renders exactly one domain view at a time,
 * so the four views never share a mounted ancestor to hang a provider on.
 *
 * What is left is a module-level store *inside the plugin*, which is allowed
 * precisely because it is inside the plugin: it is one module-scoped variable in
 * the shell's own bundle, invisible to the harness, and it dies with the shell.
 * `useSyncExternalStore` rather than a hand-rolled `useState` + effect so a
 * subscriber that mounts after a write reads the current value on its first
 * render rather than flashing the old one.
 *
 * It holds ONE thing on purpose. A shell-local store is a slope: the moment it
 * grows a second unrelated field it has become a private state manager the
 * Foreman error rail and refresh cycle know nothing about. If a second piece of
 * cross-view state is ever needed, that is the point to ask for a real
 * `onOpenView(viewId, params)` upstream instead.
 */
import { useSyncExternalStore } from 'react';

let focusVersion: string | null = null;
const listeners = new Set<() => void>();

/** The version another view asked to be shown, or null. */
export function getFocusVersion(): string | null {
  return focusVersion;
}

/**
 * Ask the version-scoped views to show `version`.
 *
 * Writing the same value is a no-op rather than a notification, so a view that
 * re-announces its own selection on every render cannot loop.
 */
export function setFocusVersion(version: string | null): void {
  if (version === focusVersion) return;
  focusVersion = version;
  for (const listener of listeners) listener();
}

export function subscribeFocusVersion(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Read the focused version reactively.
 *
 * The third argument is the server snapshot. It is not decoration: these views
 * are rendered with `renderToStaticMarkup` in the shells' own tests, and React
 * 18 throws `Missing getServerSnapshot` without it.
 */
export function useFocusVersion(): string | null {
  return useSyncExternalStore(subscribeFocusVersion, getFocusVersion, getFocusVersion);
}

/** Test-only reset, so one test's focus cannot leak into the next. */
export function resetFocusVersion(): void {
  focusVersion = null;
  listeners.clear();
}
