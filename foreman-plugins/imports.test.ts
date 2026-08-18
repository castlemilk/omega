import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The seam, asserted rather than assumed.
 *
 * A shell is supposed to depend on exactly one thing from the Foreman harness:
 * `@omega-harness/usecase-kit`. The harness has an ESLint rule saying so, but
 * that rule only reaches files inside the harness repo — it cannot see this
 * one. And the constraint is NOT enforced by the module system either: the
 * harness is checked out as a child of this repo (`omega/harness/`), so
 * `../../harness/apps/web/src/foreman/usecases/core.js` is a real, resolvable
 * path from any file here. `tsc` would follow it, Vite's dev server would serve
 * it (these directories are already in its `server.fs.allow`), and Rollup would
 * bundle it. Nothing would complain.
 *
 * This test is the thing that complains. It reads every non-test source file
 * under the shell directories, pulls out every import specifier, and fails the
 * file if a specifier reaches into the harness by path or names any package
 * other than React and the kit. A shell that stops satisfying it has stopped
 * being portable — which is the whole point of it living over here.
 *
 * Test files are excluded on purpose: they legitimately import `vitest` and
 * `react-dom/server`, neither of which is ever bundled into the app.
 */

const ROOT = dirname(fileURLToPath(import.meta.url));

/** The shell directories, i.e. the workspaces this package publishes to the harness. */
const SHELL_DIRS = ['victoria', 'polymarket'];

/**
 * Every bare specifier a shell is allowed to name.
 *
 * React and react-dom because views are React components, and the kit because
 * it is the contract. Anything else — a UI library, a date helper, the
 * harness's own package names — is a dependency the harness would have to know
 * about, and the design is that it knows about none.
 */
const ALLOWED_BARE = [
  'react',
  'react-dom',
  '@omega-harness/usecase-kit',
  '@omega-harness/usecase-kit/ui',
];

/**
 * `from '…'`, side-effect `import '…'`, and dynamic `import('…')` in one pass.
 * Deliberately loose: over-capturing a string that is not a specifier can only
 * make this stricter, never blinder.
 */
const SPECIFIER = /(?:\bfrom|\bimport)\s*\(?\s*['"]([^'"]+)['"]/g;

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'dist') continue;
      out.push(...sourceFiles(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry.name)) continue;
    if (/\.test\.tsx?$/.test(entry.name)) continue;
    out.push(full);
  }
  return out.sort();
}

function specifiersOf(source: string): string[] {
  return [...source.matchAll(SPECIFIER)].map((m) => m[1]);
}

/**
 * A specifier is fine if it names one of the allowed packages, or stays inside
 * the shell without reaching into the harness checkout.
 *
 * The allow-list is checked FIRST and the ordering is load-bearing: the kit's
 * own name, `@omega-harness/usecase-kit`, contains the substring `harness/`, so
 * the path check would otherwise reject the one dependency a shell is supposed
 * to have.
 */
function isOffending(spec: string): boolean {
  if (ALLOWED_BARE.includes(spec)) return false;
  // Any other bare specifier is a dependency the harness would have to know
  // about, and the design is that it knows about none.
  if (!spec.startsWith('.')) return true;
  // A relative path that climbs into the harness checkout — the failure this
  // whole file exists for, and the one the module system happily allows.
  return spec.includes('harness/');
}

const FILES = SHELL_DIRS.flatMap((d) => sourceFiles(join(ROOT, d)));

describe('the shells depend on the kit and nothing else', () => {
  it('found source files to check — an empty scan must not pass', () => {
    // Without this, a rename of a shell directory turns the whole guard into a
    // no-op that reports success.
    expect(FILES.length).toBeGreaterThan(10);
  });

  for (const file of FILES) {
    const rel = relative(ROOT, file);
    it(`${rel} imports only React and @omega-harness/usecase-kit`, () => {
      const offenders = specifiersOf(readFileSync(file, 'utf8')).filter(isOffending);
      // Asserted as an object so a failure names the file as well as the
      // specifier — the diff is the whole error message.
      expect({ file: rel, offenders }).toEqual({ file: rel, offenders: [] });
    });
  }
});
