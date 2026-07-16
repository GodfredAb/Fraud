import { useEffect, useRef, useState } from "react";

/**
 * Polls `fetchFn` every `intervalMs`, exposing the latest data plus a
 * lastUpdated timestamp so the UI can show how live the view actually is.
 * A failed poll keeps the previous data on screen (surfaced via `error`)
 * rather than blanking the dashboard - a transient network hiccup
 * shouldn't nuke what's already rendered.
 */
export function usePolling(fetchFn, intervalMs, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const result = await fetchFnRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
          setLastUpdated(new Date());
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    }

    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, lastUpdated };
}
