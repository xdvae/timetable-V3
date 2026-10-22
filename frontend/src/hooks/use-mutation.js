import { useCallback, useState } from "react";

import { normalizeFieldErrors } from "@/lib/failures.js";

/**
 * Shared mutation runner for thin Flask-mutation clients.
 * The backend stays authoritative: this only tracks submitting state and
 * surfaces the backend's own error envelope ({ error, field_errors }).
 * Field errors are normalized so every consumer sees { field: message }
 * of safe strings. Returns { execute, isSubmitting, error, fieldErrors, reset }.
 */
export function useMutation(mutateFn) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});

  const reset = useCallback(() => {
    setError(null);
    setFieldErrors({});
  }, []);

  const execute = useCallback(
    async (args) => {
      setIsSubmitting(true);
      setError(null);
      setFieldErrors({});
      try {
        const data = await mutateFn(args);
        setIsSubmitting(false);
        return { ok: true, data };
      } catch (err) {
        setIsSubmitting(false);
        setError(err);
        setFieldErrors(normalizeFieldErrors(err?.fieldErrors));
        return { ok: false, error: err };
      }
    },
    [mutateFn]
  );

  return { execute, isSubmitting, error, fieldErrors, reset };
}
