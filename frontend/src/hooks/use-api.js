import { useCallback, useEffect, useState } from "react";

/**
 * Shared GET-on-mount hook for read-only API pages.
 * Returns { data, error, isLoading, retry }. State updates happen only in
 * promise callbacks with a cancellation guard, so unmounted pages never
 * set state. Pass a stable service function (e.g. getRooms).
 */
export function useApi(fetcher) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setError(null);
    setIsLoading(true);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetcher().then(
      (result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
        setIsLoading(false);
      },
      (err) => {
        if (cancelled) return;
        setError(err);
        setIsLoading(false);
      }
    );
    return () => {
      cancelled = true;
    };
  }, [attempt, fetcher]);

  return { data, error, isLoading, retry };
}
