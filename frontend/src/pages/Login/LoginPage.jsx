import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { CalendarRange, CircleAlert, Eye, EyeOff, LoaderCircle } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Button } from "@/components/ui/button.jsx";
import { Input } from "@/components/ui/input.jsx";
import { Label } from "@/components/ui/label.jsx";
import { useAuth } from "@/hooks/use-auth.js";

/**
 * Standalone sign-in page (no sidebar). Authenticates against the existing
 * Flask-Login session backend via POST /api/login — no tokens, no
 * localStorage, the session cookie is the session.
 *
 * Contract (api_routes.api_login):
 * - request JSON: { username, password } (optional ?next= query)
 * - success 200: { ok, username, redirect? } (or { ok, username, message }
 *   when already signed in)
 * - failure 401: { error: "Incorrect username or password." }
 */
function safeNextPath(raw) {
  if (typeof raw !== "string" || !raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

export function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeNextPath(searchParams.get("next") || "/");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (status === "in") {
    return <Navigate to={next} replace />;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const data = await login(username.trim(), password, next);
      // Username is retained on failure only; clear the password either way.
      setPassword("");
      const target = safeNextPath(data?.redirect || next);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err);
      // Keep the entered username so it can be corrected/resubmitted;
      // clear the password after a failed attempt.
      setPassword("");
    } finally {
      setIsSubmitting(false);
    }
  }

  const loadingAuth = status === "loading";

  return (
    <div className="flex min-h-svh items-center justify-center bg-paper p-4">
      <Card className="w-full max-w-[380px] border-l-[3px] border-l-brass py-8">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CalendarRange className="size-6 text-brass" aria-hidden="true" />
            <CardTitle className="font-display text-2xl">UniSchedule</CardTitle>
          </div>
          <CardDescription>Sign in to manage your institution&apos;s schedule.</CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <Alert variant="destructive" className="mb-4">
              <CircleAlert aria-hidden="true" />
              <AlertTitle>Sign-in failed</AlertTitle>
              <AlertDescription>{error.message || "Incorrect username or password."}</AlertDescription>
            </Alert>
          ) : null}
          <form onSubmit={handleSubmit} className="grid gap-4">
            <div>
              <Label htmlFor="login-username">Username</Label>
              <Input
                id="login-username"
                type="text"
                required
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isSubmitting || loadingAuth}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor="login-password">Password</Label>
              <div className="relative mt-1.5">
                <Input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isSubmitting || loadingAuth}
                  className="pr-10"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setShowPassword((s) => !s)}
                  disabled={isSubmitting || loadingAuth}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="absolute top-1/2 right-1 h-7 w-7 -translate-y-1/2"
                >
                  {showPassword ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
                </Button>
              </div>
            </div>
            <Button type="submit" disabled={isSubmitting || loadingAuth} className="w-full">
              {isSubmitting ? (
                <>
                  <LoaderCircle className="animate-spin" aria-hidden="true" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
