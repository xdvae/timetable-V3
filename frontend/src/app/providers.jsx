import { AuthProvider } from "./auth.jsx";
import { ToastProvider } from "@/components/feedback/toast.jsx";

/** Global providers: notifications (outer) → session auth (inner). */
export function Providers({ children }) {
  return (
    <ToastProvider>
      <AuthProvider>{children}</AuthProvider>
    </ToastProvider>
  );
}
