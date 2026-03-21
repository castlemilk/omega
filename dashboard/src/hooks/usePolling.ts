import { useEffect, useRef, useState } from "react";

/**
 * Calls `fetcher` immediately and then on every `intervalMs` tick.
 * The fetcher reference must be stable (wrap in useCallback at call site).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5000,
): { data: T | null; error: string | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const result = await fetcher();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchOnce();
    timerRef.current = setInterval(fetchOnce, intervalMs);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { data, error, loading };
}
