import { createContext, useContext } from "react";

export const ToastContext = createContext(null);

/** Access the toast notifier. Must be used within a ToastProvider. */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider.");
  return ctx;
}
