import { useCallback, useEffect, useMemo, useState } from "react";

import { subscribeInvalidation } from "@/lib/invalidation.js";

function resolveDomains(arg) {
  if (!arg) return [];
  const raw = Array.isArray(arg) ? arg : arg.invalidateOn;
  if (!Array.isArray(raw)) return [];
  return raw.filter((domain) => typeof domain === "string" && domain !== "");
}

/**
 * Shared GET-on-mount hook for read-only API pages.
 * Returns { data, error, isLoading, retry }. State updates happen only in
 * promise callbacks with a cancellation guard, so unmounted pages never
 * set state. Pass a stable service function (e.g. getRooms).
 *
 * Phase 6P: pass resource domains to refetch when a successful authoritative
 * mutation elsewhere emits them, e.g. `useApi(getRooms, ["rooms"])` or
 * `useApi(getRooms, { invalidateOn: ["rooms"] })`. The subscription calls
 * the same `retry()` used for manual refresh, so loading/error behavior is
 * unchanged. Subscriptions are cleaned up on unmount (no refetch after
 * unmount), deduplicated per domain set (one GET per emission even when
 * several subscribed domains match), and emit synchronously in the same
 * tick as the emitter's own local retry, letting React batch both into a
 * single render/GET. This hook stores no shared state and creates no cache.
 */
export function useApi(fetcher, invalidateOn) {
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

  // Phase 6P subscription: stable string key so inline array literals do not
  // resubscribe every render; the effect re-runs only when the domain set
  // actually changes (`retry` is a stable callback, so it never retriggers).
  const domainsKey = useMemo(() => {
    const unique = [...new Set(resolveDomains(invalidateOn))].sort();
    return unique.join("\0");
  }, [invalidateOn]);
  useEffect(() => {
    if (domainsKey === "") return undefined;
    const domains = domainsKey.split("\0");
    return subscribeInvalidation(domains, () => {
      retry();
    });
  }, [domainsKey, retry]);

  return { data, error, isLoading, retry };
}
