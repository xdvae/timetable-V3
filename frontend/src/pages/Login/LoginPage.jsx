import { Link } from "react-router";
import { CalendarRange } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card.jsx";

/**
 * Standalone sign-in shell (no sidebar). The actual sign-in form ships in
 * the auth phase; this placeholder only proves the public route renders.
 */
export function LoginPage() {
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
          <p className="text-sm text-muted-foreground">
            The sign-in form ships in the auth phase. It will authenticate against the existing
            Flask session backend — no new credentials, no tokens.
          </p>
          <Link to="/" className="mt-4 inline-block text-sm text-steel underline-offset-4 hover:underline">
            Back to dashboard
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
