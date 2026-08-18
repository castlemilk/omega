import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * The same guard as `../victoria/manifest-cost.test.ts`, and in its own file for
 * the same reason: a static import of the manifest at the top of the file it
 * used to live in meant the module had already executed before `fetch` was
 * stubbed, so the dynamic import returned the cache and the assertion could not
 * fail. Polymarket declares no data source at all, which makes this cheap to
 * hold — and worth asserting, because "no backend yet" is exactly the state in
 * which someone adds a speculative fetch.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the Polymarket manifest costs nothing', () => {
  it('opens no request and no stream when the shell is merely registered', async () => {
    vi.resetModules();
    const fetchSpy = vi.fn();
    const eventSourceSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    // A mock function records `new EventSource(...)` just as well as a class.
    vi.stubGlobal('EventSource', eventSourceSpy);

    const module = await import('./index.js');

    expect(module.polymarketUseCase.id).toBe('polymarket');
    expect(module.polymarketUseCase.dataSources).toBeUndefined();
    expect(fetchSpy).toHaveBeenCalledTimes(0);
    expect(eventSourceSpy).toHaveBeenCalledTimes(0);
  });
});
