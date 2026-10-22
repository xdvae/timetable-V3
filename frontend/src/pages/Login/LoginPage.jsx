import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { CalendarRange, LoaderCircle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth.js";

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
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (status === "in") {
    return <Navigate to={next} replace />;
  }

  const handleSignIn = async (e) => {
    if (e) e.preventDefault();
    if (isSubmitting) return;

    const trimmed = username.trim();
    if (!trimmed || !password) {
      setError("Please enter both email/username and password.");
      return;
    }

    setError("");
    setIsSubmitting(true);

    try {
      const data = await login(trimmed, password, next);
      setPassword("");
      const target = safeNextPath(data?.redirect || next);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err?.message || "Incorrect username or password.");
      setPassword("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const loadingAuth = status === "loading";

  return (
    <div className="min-h-screen min-h-svh flex flex-col items-center justify-center bg-[#f3f5f8] relative overflow-hidden w-full p-4 font-sans selection:bg-brass/20 selection:text-ink">
      {/* Centered card */}
      <div className="relative z-10 w-full max-w-sm rounded-3xl bg-white shadow-[0_12px_40px_rgba(22,35,63,0.08)] border border-[#dfe4ed] p-8 flex flex-col items-center">
        {/* App branding header */}
        <div className="flex flex-col items-center text-center mb-6">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-brass/15 text-brass border border-brass/25 shadow-xs mb-3">
            <CalendarRange className="size-6 text-brass" aria-hidden="true" />
          </div>
          <h1 className="font-display text-2xl font-bold text-ink tracking-tight leading-tight">
            UniSchedule
          </h1>
          <p className="mt-1 text-xs text-ink-soft">
            University scheduling
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSignIn} className="flex flex-col w-full gap-4">
          <div className="w-full flex flex-col gap-3">
            <input
              id="auth-username"
              placeholder="Email or username"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              disabled={isSubmitting || loadingAuth}
              className="w-full px-5 py-3.5 rounded-xl bg-[#f8fafc] text-ink placeholder:text-[#8a96b5] text-sm border border-[#dfe4ed] focus:outline-none focus:ring-2 focus:ring-brass/40 focus:border-brass transition"
              onChange={(e) => {
                setUsername(e.target.value);
                if (error) setError("");
              }}
            />
            <input
              id="auth-password"
              placeholder="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              disabled={isSubmitting || loadingAuth}
              className="w-full px-5 py-3.5 rounded-xl bg-[#f8fafc] text-ink placeholder:text-[#8a96b5] text-sm border border-[#dfe4ed] focus:outline-none focus:ring-2 focus:ring-brass/40 focus:border-brass transition"
              onChange={(e) => {
                setPassword(e.target.value);
                if (error) setError("");
              }}
            />
            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5 text-left">
                {error}
              </div>
            )}
          </div>

          <button
            type="submit"
            disabled={isSubmitting || loadingAuth}
            className="w-full mt-1 bg-[#16233f] hover:bg-[#22355e] text-white font-medium px-5 py-3.5 rounded-full shadow-md active:scale-[0.99] transition text-sm flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <LoaderCircle className="w-4 h-4 animate-spin" aria-hidden="true" />
                Signing in…
              </>
            ) : (
              "Sign in"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

export default LoginPage;
