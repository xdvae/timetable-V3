import { TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog.jsx";
import { FAILURE_LABELS, failureContext } from "@/lib/failures.js";

/** Field-level backend validation message, wired for aria-describedby. */
export function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="mt-1 text-xs font-medium text-signal">
      {message}
    </p>
  );
}

/** General (non-field) mutation failure. Unknown backend fields land here too. */
export function MutationError({ error }) {
  if (!error) return null;
  return (
    <Alert variant="destructive">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>Something went wrong</AlertTitle>
      <AlertDescription>{error.message || "The operation could not be completed."}</AlertDescription>
    </Alert>
  );
}

/**
 * Compact list of structured backend validation failures. Shows the
 * backend message verbatim with a code-derived label; technical context
 * (day/period/class IDs) stays secondary. Only fields that exist are shown.
 */
export function FailureList({ failures, title }) {
  if (!failures || failures.length === 0) return null;
  return (
    <Alert variant="destructive">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>{title ?? "Cannot complete this change"}</AlertTitle>
      <AlertDescription>
        <ul className="grid gap-2">
          {failures.map((failure, index) => {
            const context = failureContext(failure.details);
            return (
              <li key={index}>
                <p className="font-medium">{FAILURE_LABELS[failure.code] ?? "Validation failed"}</p>
                {failure.message ? <p>{failure.message}</p> : null}
                {context ? <p className="text-xs opacity-80">{context}</p> : null}
              </li>
            );
          })}
        </ul>
      </AlertDescription>
    </Alert>
  );
}

/** Soft weekly-load notice (never a blocker). Rendered when exceeded. */
export function LoadWarning({ warning }) {
  if (!warning?.exceeded) return null;
  return (
    <Alert variant="warning">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>Weekly load warning</AlertTitle>
      <AlertDescription>{warning.message || "This change exceeds the faculty's weekly hour limit."}</AlertDescription>
    </Alert>
  );
}

/**
 * Required confirmation for every destructive delete. Uses the shadcn Dialog
 * primitive (never window.confirm). Backend dependency/conflict messages are
 * shown verbatim inside the dialog; the record stays visible on failure.
 */
export function DeleteConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Delete",
  onConfirm,
  isConfirming = false,
  error = null,
}) {
  return (
    <Dialog open={open} onOpenChange={isConfirming ? undefined : onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {error ? (
          <Alert variant="destructive">
            <TriangleAlert aria-hidden="true" />
            <AlertTitle>Delete failed</AlertTitle>
            <AlertDescription>{error.message || "The record could not be deleted."}</AlertDescription>
          </Alert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isConfirming}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isConfirming}>
            {isConfirming ? "Deleting…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
