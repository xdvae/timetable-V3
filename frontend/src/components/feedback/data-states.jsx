import { Inbox, TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Button } from "@/components/ui/button.jsx";
import { Skeleton } from "@/components/ui/skeleton.jsx";

/** Loading placeholder for API-backed pages: skeletons, never an empty table. */
export function PageLoading({ rows = 5, label = "Loading…" }) {
  return (
    <div className="space-y-3" role="status" aria-label={label}>
      <span className="sr-only">{label}</span>
      <Skeleton className="h-10 w-full" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

/** Human-readable API failure with a retry action. */
export function QueryError({ error, onRetry }) {
  const status = error?.status;
  const hint =
    status === 401
      ? "Your session may have expired. Reload the page to sign in again."
      : status === 0
        ? "The server could not be reached."
        : null;
  return (
    <Alert variant="destructive">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>Couldn&apos;t load this page</AlertTitle>
      <AlertDescription>
        <p>{error?.message || "Something went wrong while loading data."}</p>
        {hint ? <p className="mt-1">{hint}</p> : null}
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-3">
            Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

/** Proper empty-collection state: one calm panel, not repeated row text. */
export function EmptyState({ icon: Icon = Inbox, title, description, action }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line bg-panel px-6 py-12 text-center">
      <span className="flex size-10 items-center justify-center rounded-full bg-muted">
        <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
      </span>
      <p className="font-display text-lg font-semibold text-ink">{title}</p>
      {description ? <p className="max-w-md text-sm text-muted-foreground">{description}</p> : null}
      {action}
    </div>
  );
}
