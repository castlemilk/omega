import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * A registered-but-inactive shell must cost zero requests.
 *
 * This lives in its own file, and that is the whole point. The same assertion
 * used to sit in `shell.test.ts` next to a *static* `import ... from
 * './index.js'` at the top of that file — so by the time the test stubbed
 * `fetch`, the manifest had already executed, and `await import('./index.js')`
 * only handed back the cached module. A module-scope fetch would have fired
 * before the spy existed and the guard would have passed anyway.
 *
 * So: no static import of anything that pulls the manifest in, `vi.resetModules`
 * before the dynamic one, and the transports stubbed first. The import below is
 * the manifest genuinely executing — it and its whole graph (client, views) —
 * with the spies watching.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the Victoria manifest costs nothing until a view mounts', () => {
  it('opens no request and no stream when the shell is merely registered', async () => {
    vi.resetModules();
    const fetchSpy = vi.fn();
    const eventSourceSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    // A mock function records `new EventSource(...)` just as well as a class.
    vi.stubGlobal('EventSource', eventSourceSpy);

    const module = await import('./index.js');

    // Proof the import really ran, so a silently-failed import can't pass this.
    expect(module.victoriaUseCase.id).toBe('victoria');
    expect(module.victoriaUseCase.dataSources?.[0].id).toBe('omega-api');
    expect(fetchSpy).toHaveBeenCalledTimes(0);
    expect(eventSourceSpy).toHaveBeenCalledTimes(0);
  });
});
