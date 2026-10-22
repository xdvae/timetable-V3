import { useCallback, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

import { ToastContext } from "@/hooks/use-toast.js";
import { cn } from "@/lib/utils";

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const STYLES = {
  success: "border-sage/40 bg-sage-tint text-ink",
  error: "border-signal/40 bg-signal-tint text-ink",
  warning: "border-brass/50 bg-brass/10 text-ink",
  info: "border-steel/40 bg-steel-tint text-ink",
};

const ICON_STYLES = {
  success: "text-sage",
  error: "text-signal",
  warning: "text-brass-dark",
  info: "text-steel",
};

let toastId = 0;

/**
 * Reusable notification mechanism (replaces Flask flash messages).
 * Pages call notify()/success()/error()/warning()/info() — no fake
 * notifications are emitted anywhere by default.
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback(
    (message, { type = "info", title, duration = 5000 } = {}) => {
      const id = ++toastId;
      setToasts((prev) => [...prev.slice(-3), { id, message, type, title }]);
      if (duration > 0) {
        timers.current.set(id, setTimeout(() => dismiss(id), duration));
      }
      return id;
    },
    [dismiss]
  );

  const value = useMemo(
    () => ({
      notify,
      dismiss,
      success: (message, opts) => notify(message, { ...opts, type: "success" }),
      error: (message, opts) => notify(message, { ...opts, type: "error" }),
      warning: (message, opts) => notify(message, { ...opts, type: "warning" }),
      info: (message, opts) => notify(message, { ...opts, type: "info" }),
    }),
    [notify, dismiss]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-[100] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2"
      >
        {toasts.map((toast) => {
          const Icon = ICONS[toast.type] ?? Info;
          return (
            <div
              key={toast.id}
              role={toast.type === "error" ? "alert" : "status"}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-lg border p-3 shadow-lg",
                STYLES[toast.type] ?? STYLES.info
              )}
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", ICON_STYLES[toast.type] ?? ICON_STYLES.info)} />
              <div className="min-w-0 flex-1 text-sm">
                {toast.title ? <p className="font-semibold">{toast.title}</p> : null}
                <p className="break-words">{toast.message}</p>
              </div>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                aria-label="Dismiss notification"
                className="rounded p-0.5 opacity-70 outline-none transition-opacity hover:opacity-100 focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
