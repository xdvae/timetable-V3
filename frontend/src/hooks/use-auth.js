import { createContext, useContext } from "react";

export const AuthContext = createContext(null);

/** Access session auth state. Must be used within an AuthProvider. */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider.");
  return ctx;
}
