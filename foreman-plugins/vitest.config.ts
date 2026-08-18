import { defineConfig } from 'vitest/config';

/**
 * The shells' own test run — no harness, no browser, no DOM.
 *
 * These tests are the reason the shells are testable outside the app at all:
 * they import the shell modules and the kit, and nothing else. Views that need
 * rendering are rendered with `renderToStaticMarkup`, so there is no jsdom or
 * happy-dom to install and no test environment to keep in step with the
 * harness's. `environment` is therefore left at `node`.
 *
 * `jsx: 'automatic'` is stated rather than inherited: esbuild would take it
 * from `tsconfig.json` today, and stating it means a tsconfig change cannot
 * silently switch these files to the classic runtime and start failing on the
 * missing `React` binding.
 */
export default defineConfig({
  esbuild: {
    jsx: 'automatic',
  },
  test: {
    include: ['victoria/**/*.test.{ts,tsx}', 'polymarket/**/*.test.{ts,tsx}'],
  },
});
