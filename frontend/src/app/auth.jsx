import { useCallback, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router";

import { login as apiLogin, logout as apiLogout, me as apiMe } from "@/services/api/auth.js";
import { ApiError } from "@/services/api/client.js";
import { Skeleton } from "@/components/ui/skeleton.jsx";
import { AuthContext } from "@/hooks/use-auth.js";
import { useAuth } from "@/hooks/use-auth.js";

/**
 * Authentication foundation over the existing Flask-Login session cookie.
 * - No JWT, no localStorage tokens, no fake auth.
 * - `user` is null when signed out; `{ username }` when signed in.
 * - `refresh()` re-checks GET /api/me (used on app start).
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | in | out

  const refresh = useCallback(async () => {
    try {
      const data = await apiMe();
      setUser({ username: data.username });
      setStatus("in");
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.isAuth) {
        setUser(null);
        setStatus("out");
        return false;
      }
      // Network/server failure: stay in loading so the shell can show an
      // error state instead of wrongly routing to /login.
      setStatus("error");
      return false;
    }
  }, []);

  // Initial session check. State updates live in promise callbacks (async
  // context), with a cancellation flag — the documented data-fetch pattern.
  useEffect(() => {
    let cancelled = false;
    apiMe().then(
      (data) => {
        if (cancelled) return;
        setUser({ username: data.username });
        setStatus("in");
      },
      (err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.isAuth) {
          setUser(null);
          setStatus("out");
        } else {
          setStatus("error");
        }
      }
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username, password, next) => {
    const data = await apiLogin(username, password, next);
    setUser({ username: data.username });
    setStatus("in");
    return data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
      setStatus("out");
    }
  }, []);

  const value = { user, status, isLoading: status === "loading", login, logout, refresh };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Route guard: signed-out users go to /login with ?next= preserved so the
 * future login page can send them back where they were headed.
 */
export function RequireAuth({ children }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex min-h-svh items-center justify-center bg-paper p-6" aria-busy="true" aria-label="Loading">
        <div className="w-full max-w-sm space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex min-h-svh items-center justify-center bg-paper p-6">
        <p className="max-w-sm text-center text-sm text-muted-foreground">
          Could not reach the server. Check your connection and reload the page.
        </p>
      </div>
    );
  }

  if (status !== "in") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return children;
}
