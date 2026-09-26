import { useMemo, useState } from "react";
import { Link } from "react-router";
import {
  ArrowLeft,
  CalendarDays,
  CircleCheck,
  Info,
  LoaderCircle,
  Lock,
  MoveRight,
  Sparkles,
} from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog.jsx";
import { Label } from "@/components/ui/label.jsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select.jsx";
import { FailureList, MutationError } from "@/components/feedback/mutation.jsx";
import { getFailures } from "@/lib/failures.js";
import { emitOnSuccess, MOVE_DOMAINS } from "@/lib/propagation.js";
import { cn } from "@/lib/utils";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { getRooms } from "@/services/api/rooms.js";
import {
  getScheduledClasses,
  moveScheduledClass,
  validateMove,
} from "@/services/api/schedule.js";

/**
 * Interactive timetable editor (Phase 6O).
 *
 * Interaction model: click a class → move dialog (current placement,
 * destination day/start-period/room selectors) → Validate Move (backend
 * dry-run, nothing mutates) → Apply Move (backend mutation with the exact
 * validated payload) → authoritative schedule refetch.
 *
 * The frontend is an interaction layer only: every hard rule (room,
 * faculty, section, hierarchy, HN1/H12, geometry, locks, specialization
 * sync) is validated server-side. Local checks cover required fields and
 * integer syntax. This page never calls POST /api/schedule/run and never
 * patches the timetable optimistically — the refetched schedule is the
 * only source of truth.
 */

/** Bulk read for the editor: display-ready classes + destination rooms. */
function fetchEditorData() {
  return Promise.all([getScheduledClasses(), getRooms()]).then(
    ([schedule, rooms]) => ({
      classes: schedule.classes ?? [],
      days: schedule.days ?? [],
      periods: schedule.periods ?? [],
      hasSchedule: schedule.has_schedule ?? false,
      rooms: rooms ?? [],
    })
  );
}

function groupLabel(cls) {
  return cls.specialization ?? cls.lab_group ?? cls.section ?? "?";
}

function isLocked(cls) {
  return Boolean(cls.is_locked) || cls.locked_block_id != null;
}

/** Fail-safe: a row carrying a specialization slot link is spec-linked. */
function isSpecialization(cls) {
  return cls.specialization_id != null || cls.slot_id != null;
}

function isMovable(cls) {
  return !isLocked(cls) && !isSpecialization(cls);
}

function placementLabel(cls, periods) {
  const time = periods[cls.start_period] ?? `Period ${cls.start_period}`;
  const plural = cls.length === 1 ? "period" : "periods";
  return `${cls.day} · P${cls.start_period} (${time}) × ${cls.length} ${plural}`;
}

function covers(start, length) {
  return Array.from({ length }, (_, i) => start + i);
}

/** Other classes overlapping the given footprint (informational only). */
function findOverlaps(classes, excludeId, day, start, length) {
  const want = new Set(covers(start, length));
  return (classes ?? []).filter((other) => {
    if (other.id === excludeId || other.day !== day) return false;
    return covers(other.start_period, other.length).some((p) => want.has(p));
  });
}

/**
 * Legend: text and icons always carry the meaning — color is secondary.
 * Extends the read-only timetable legend with editor states.
 */
function EditorLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground" aria-label="Legend">
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] bg-steel" aria-hidden="true" />
        Theory
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] bg-sage" aria-hidden="true" />
        Lab / Practical
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Lock className="size-3" aria-hidden="true" />
        Fixed (locked, cannot move)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Sparkles className="size-3" aria-hidden="true" />
        Specialization (backend moves only as a cohort)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] border-2 border-brass bg-transparent" aria-hidden="true" />
        Selected
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] bg-brass/30" aria-hidden="true" />
        Destination footprint
      </span>
    </div>
  );
}

function ClassBadges({ cls }) {
  const practical = cls.session_type === "practical";
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      <Badge variant={practical ? "lab" : "theory"}>{practical ? "Lab" : "Theory"}</Badge>
      {isLocked(cls) ? (
        <Badge variant="danger">
          <Lock aria-hidden="true" />
          Fixed
        </Badge>
      ) : null}
      {isSpecialization(cls) ? (
        <Badge variant="secondary">
          <Sparkles aria-hidden="true" />
          Spec
        </Badge>
      ) : null}
      {cls.length > 1 ? <Badge variant="outline">× {cls.length} periods</Badge> : null}
    </span>
  );
}

/**
 * One scheduled class as a keyboard-focusable button. Locked and
 * specialization classes are selectable for details but never enter move
 * mode — the dialog explains why and offers no destination controls.
 */
function ClassCardButton({ cls, periods, selected, onSelect }) {
  const locked = isLocked(cls);
  const spec = !locked && isSpecialization(cls);
  return (
    <button
      type="button"
      onClick={() => onSelect(cls)}
      aria-pressed={selected}
      aria-label={`${locked ? "Fixed class" : spec ? "Specialization class" : "Movable class"}: ${cls.subject}, ${cls.faculty}, ${groupLabel(cls)}, Room ${cls.room}, ${placementLabel(cls, periods)}. Activate to ${locked || spec ? "view details" : "move"}.`}
      className={cn(
        "w-full rounded-md border p-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
        cls.session_type === "practical"
          ? "border-sage/40 bg-sage-tint/40 hover:bg-sage-tint"
          : "border-steel/30 bg-steel-tint/40 hover:bg-steel-tint",
        selected && "border-brass ring-2 ring-brass",
        locked && "border-dashed opacity-90"
      )}
    >
      <span className="block text-[0.8rem] leading-snug font-semibold text-ink">
        {locked ? (
          <Lock className="mr-1 inline size-3" aria-hidden="true" />
        ) : spec ? (
          <Sparkles className="mr-1 inline size-3" aria-hidden="true" />
        ) : null}
        {cls.subject}
      </span>
      <ClassBadges cls={cls} />
      <span className="mt-1 block truncate text-xs text-ink">{cls.faculty}</span>
      <span className="block truncate text-xs text-muted-foreground">
        {groupLabel(cls)} | Room {cls.room}
      </span>
    </button>
  );
}

/**
 * Day × period grid derived from the backend/config schedule structure
 * (never hardcoded). Rows are periods, columns are working days. A class
 * starts in its start-period cell; the tail periods it covers render a
 * slim continuation strip so a multi-period block visibly occupies its
 * whole footprint while keeping single-ScheduledClass semantics.
 */
function EditorGrid({ days, periods, classes, selectedId, onSelect }) {
  const starters = useMemo(() => {
    const map = new Map();
    for (const cls of classes) {
      const key = `${cls.day}|${cls.start_period}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(cls);
    }
    return map;
  }, [classes]);

  const tails = useMemo(() => {
    const map = new Map();
    for (const cls of classes) {
      for (const p of covers(cls.start_period, cls.length).slice(1)) {
        const key = `${cls.day}|${p}`;
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(cls);
      }
    }
    return map;
  }, [classes]);

  const selectedFootprint = useMemo(() => {
    const sel = classes.find((c) => c.id === selectedId);
    if (!sel) return new Set();
    return new Set(covers(sel.start_period, sel.length).map((p) => `${sel.day}|${p}`));
  }, [classes, selectedId]);

  const columns = `110px repeat(${days.length}, minmax(150px, 1fr))`;
  const minWidth = `calc(110px + ${days.length} * 150px)`;

  return (
    <div className="overflow-x-auto rounded-lg border border-line" role="grid" aria-label="Editable timetable grid">
      <div className="grid gap-px bg-line" style={{ gridTemplateColumns: columns, minWidth }} role="row">
        <div role="columnheader" className="sticky left-0 bg-muted px-2 py-2 text-xs font-semibold text-ink">
          Period / Day
        </div>
        {days.map((day) => (
          <div
            key={day}
            role="columnheader"
            className="bg-muted px-2 py-2 text-center text-xs font-semibold text-ink"
          >
            {day}
          </div>
        ))}
      </div>
      {periods.map((label, period) => (
        <div
          key={period}
          role="row"
          aria-label={`Period ${period}`}
          className="grid gap-px border-t border-line bg-line"
          style={{ gridTemplateColumns: columns, minWidth }}
        >
          <div
            role="rowheader"
            className="sticky left-0 bg-steel-tint px-2 py-2 text-xs font-semibold text-ink tabular-nums"
          >
            P{period}
            <span className="block text-[0.65rem] font-normal whitespace-normal">{label}</span>
          </div>
          {days.map((day) => {
            const key = `${day}|${period}`;
            const cards = starters.get(key) ?? [];
            const continuations = tails.get(key) ?? [];
            const isDest = selectedFootprint.has(key);
            return (
              <div
                key={key}
                role="gridcell"
                aria-label={`${day} period ${period}${cards.length === 0 ? ": no class starts here" : `: ${cards.length} class${cards.length === 1 ? "" : "es"}`}`}
                className={cn("min-h-[5rem] space-y-1.5 bg-panel p-1.5", isDest && "bg-brass/15")}
              >
                {cards.map((cls) => (
                  <ClassCardButton
                    key={cls.id}
                    cls={cls}
                    periods={periods}
                    selected={cls.id === selectedId}
                    onSelect={onSelect}
                  />
                ))}
                {continuations.map((cls) => (
                  <div
                    key={`tail-${cls.id}`}
                    aria-hidden="true"
                    title={`Continued: ${cls.subject} (${cls.length} periods from P${cls.start_period})`}
                    className={cn(
                      "rounded-sm border-l-4 px-1.5 py-0.5 text-[0.65rem] text-muted-foreground",
                      cls.session_type === "practical"
                        ? "border-sage bg-sage-tint/50"
                        : "border-steel bg-steel-tint/50"
                    )}
                  >
                    ↳ {cls.subject} (cont.)
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/**
 * Mini destination-footprint strip: every period of the destination day,
 * with the covered footprint highlighted and other overlapping classes
 * named. Informational only — the backend decides validity.
 */
function FootprintPreview({ day, start, length, periods, overlaps }) {
  const covered = new Set(covers(start, length));
  const overflow = start + length > periods.length;
  return (
    <div>
      <p className="text-xs font-medium text-ink">
        Destination footprint — {day}, {length} {length === 1 ? "period" : "periods"} from P{start}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1" role="img" aria-label={`Periods ${covers(start, length).join(", ")} highlighted on ${day}`}>
        {periods.map((label, period) => {
          const hit = covered.has(period);
          const occupied = hit && overlaps.some((o) => covers(o.start_period, o.length).includes(period));
          return (
            <span
              key={period}
              title={`P${period} · ${label}`}
              className={cn(
                "rounded border px-1.5 py-1 text-[0.65rem] tabular-nums",
                hit
                  ? occupied
                    ? "border-signal/60 bg-signal-tint font-semibold text-signal"
                    : "border-brass bg-brass/25 font-semibold text-ink"
                  : "border-line bg-muted/40 text-muted-foreground"
              )}
            >
              P{period}
            </span>
          );
        })}
      </div>
      {overflow ? (
        <p className="mt-1 text-xs font-medium text-signal" role="alert">
          This footprint extends past the last configured period — the backend will reject it.
          Pick an earlier start period.
        </p>
      ) : overlaps.length > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Informational: {overlaps.length} other {overlaps.length === 1 ? "class overlaps" : "classes overlap"} this
          footprint ({overlaps.map((o) => `${o.subject} · ${groupLabel(o)} · Room ${o.room}`).join("; ")}). Only the
          backend validation below decides whether the move is allowed.
        </p>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">
          No other class starts or continues in this footprint.
        </p>
      )}
    </div>
  );
}

function CurrentPlacement({ cls, periods }) {
  const rows = [
    ["Subject", cls.subject],
    ["Faculty", cls.faculty],
    ["Section / group", groupLabel(cls)],
    ["Room", cls.room],
    ["Day", cls.day],
    ["Start period", `P${cls.start_period} (${periods[cls.start_period] ?? "?"})`],
    ["Duration", `${cls.length} ${cls.length === 1 ? "period" : "periods"} (cannot be resized here)`],
  ];
  if (cls.specialization) rows.push(["Specialization", cls.specialization]);
  if (isLocked(cls)) rows.push(["Fixed block", `Locked (block ${cls.locked_block_id ?? "—"})`]);
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted-foreground">{term}</dt>
          <dd className="font-medium text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Move dialog: validate-before-apply against the backend, then an
 * authoritative refetch. The exact validated payload is stored and reused
 * for the mutation; any destination change resets validation.
 */
function MoveDialog({ cls, days, periods, rooms, classes, open, onOpenChange, onApplied, onStale }) {
  const toast = useToast();
  const [destDay, setDestDay] = useState(cls.day);
  const [destStart, setDestStart] = useState(String(cls.start_period));
  const [destRoom, setDestRoom] = useState(String(cls.room_id));
  const [phase, setPhase] = useState("idle");
  const [validData, setValidData] = useState(null);
  const [validatedPayload, setValidatedPayload] = useState(null);
  const validation = useMutation((payload) => validateMove(cls.id, payload));
  const apply = useMutation((payload) => moveScheduledClass(cls.id, payload));

  const startInt = Number(destStart);
  const roomInt = Number(destRoom);
  const localError = !Number.isInteger(startInt)
    ? "Start period must be a whole number."
    : !Number.isInteger(roomInt)
      ? "A destination room is required."
      : null;
  const busy = validation.isSubmitting || apply.isSubmitting;
  const canValidate = !busy && localError === null && destDay !== "";

  const destinationPayload =
    localError === null && destDay !== ""
      ? { day: destDay, start_period: startInt, room_id: roomInt }
      : null;

  const overlapDay = destinationPayload?.day;
  const overlapStart = destinationPayload?.start_period;
  const overlaps = useMemo(
    () =>
      overlapDay != null && overlapStart != null
        ? findOverlaps(classes, cls.id, overlapDay, overlapStart, cls.length)
        : [],
    [classes, cls.id, cls.length, overlapDay, overlapStart]
  );
  const validationFailures = getFailures(validation.error);
  const applyFailures = getFailures(apply.error);
  const destRoomName = rooms.find((r) => String(r.id) === destRoom)?.name ?? `Room ${destRoom}`;
  const roomChanged = String(cls.room_id) !== destRoom;

  function handleDestinationChange(setter) {
    return (value) => {
      setter(value);
      // The validated payload no longer matches: force re-validation.
      setPhase("idle");
      setValidData(null);
      setValidatedPayload(null);
      validation.reset();
      apply.reset();
    };
  }

  async function handleValidate() {
    if (!canValidate || !destinationPayload) return;
    apply.reset();
    const result = await validation.execute(destinationPayload);
    if (result.ok) {
      if (result.data.noop) {
        setPhase("noop");
      } else {
        setPhase("valid");
      }
      setValidData(result.data);
      // Snapshot the exact payload the backend approved.
      setValidatedPayload({ ...destinationPayload });
      if (!result.data.noop) {
        toast.success("Move is valid. Review and apply it when ready.", { title: "Validation passed" });
      }
    } else if (result.error) {
      setPhase("invalid");
      setValidData(null);
      setValidatedPayload(null);
      toast.error(result.error.message || "This move is not valid.", { title: "Validation failed" });
    }
  }

  async function handleApply() {
    if (phase !== "valid" || !validatedPayload || busy) return;
    const result = await apply.execute(validatedPayload);
    if (result.ok) {
      if (result.data.noop) {
        toast.success("No changes needed — the class is already there.");
      } else {
        toast.success(result.data.message || "Class moved.", { title: "Move applied" });
      }
      onApplied();
      // Phase 6P: placement changed. A true noop writes nothing and emits
      // nothing; validation and apply-failures never reach here.
      emitOnSuccess(result, MOVE_DOMAINS);
    } else if (result.error) {
      // Possible stale schedule (another mutation landed in between):
      // surface the authoritative error and recover via refetch.
      toast.error(result.error.message || "The move could not be applied.", { title: "Apply failed" });
      onStale();
    }
  }

  const showInvalid = phase === "invalid" && validationFailures.length > 0;
  const showApplyInvalid = apply.error && applyFailures.length > 0;

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Move — {cls.subject}</DialogTitle>
          <DialogDescription>
            Validate the destination with the backend first, then apply. Nothing moves until you apply.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <section aria-label="Current placement">
            <h3 className="mb-1.5 text-sm font-semibold text-ink">Current</h3>
            <CurrentPlacement cls={cls} periods={periods} />
          </section>

          <section aria-label="Destination" className="space-y-3">
            <h3 className="text-sm font-semibold text-ink">Destination</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <Label htmlFor="move-day">Day</Label>
                <Select value={destDay} onValueChange={handleDestinationChange(setDestDay)} disabled={busy}>
                  <SelectTrigger id="move-day" className="mt-1.5">
                    <SelectValue placeholder="Select a day" />
                  </SelectTrigger>
                  <SelectContent>
                    {days.map((d) => (
                      <SelectItem key={d} value={d}>
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="move-start">Start period</Label>
                <Select value={destStart} onValueChange={handleDestinationChange(setDestStart)} disabled={busy}>
                  <SelectTrigger id="move-start" className="mt-1.5">
                    <SelectValue placeholder="Select a period" />
                  </SelectTrigger>
                  <SelectContent>
                    {periods.map((label, index) => (
                      <SelectItem key={index} value={String(index)}>
                        P{index} · {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="move-room">Room</Label>
                <Select value={destRoom} onValueChange={handleDestinationChange(setDestRoom)} disabled={busy}>
                  <SelectTrigger id="move-room" className="mt-1.5">
                    <SelectValue placeholder="Select a room" />
                  </SelectTrigger>
                  <SelectContent>
                    {rooms.map((room) => (
                      <SelectItem key={room.id} value={String(room.id)}>
                        {room.name} · {room.room_type} · {room.capacity} seats
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {localError ? (
              <p className="text-xs font-medium text-signal" role="alert">
                {localError}
              </p>
            ) : null}
            {destinationPayload ? (
              <FootprintPreview
                day={destinationPayload.day}
                start={destinationPayload.start_period}
                length={cls.length}
                periods={periods}
                overlaps={overlaps}
              />
            ) : null}
          </section>

          <section aria-label="Validation" aria-live="polite" className="space-y-3">
            {phase === "idle" ? (
              <MutationError error={validation.error && validationFailures.length === 0 ? validation.error : null} />
            ) : null}
            {showInvalid ? <FailureList failures={validationFailures} title="Move is not valid — nothing was changed" /> : null}
            {phase === "valid" && validData ? (
              <Alert variant="success">
                <CircleCheck aria-hidden="true" />
                <AlertTitle>Move is valid</AlertTitle>
                <AlertDescription>
                  <p className="flex flex-wrap items-center gap-1 font-medium">
                    {cls.day} · P{cls.start_period}
                    <MoveRight className="size-4" aria-hidden="true" />
                    {validatedPayload.day} · P{validatedPayload.start_period}
                    {roomChanged ? (
                      <span>
                        · Room {cls.room} <MoveRight className="inline size-4" aria-hidden="true" /> {destRoomName}
                      </span>
                    ) : (
                      <span>· Room {cls.room} (unchanged)</span>
                    )}
                    <span>· {cls.length} {cls.length === 1 ? "period" : "periods"}</span>
                  </p>
                  <p className="mt-1 text-xs">
                    Approved by the backend dry-run. Applying sends this exact destination — change anything and
                    validation runs again.
                  </p>
                </AlertDescription>
              </Alert>
            ) : null}
            {phase === "noop" ? (
              <Alert variant="info">
                <Info aria-hidden="true" />
                <AlertTitle>No changes needed</AlertTitle>
                <AlertDescription>
                  {validData?.message || "The class is already at the requested day, period, and room."}
                </AlertDescription>
              </Alert>
            ) : null}
            {showApplyInvalid ? (
              <FailureList failures={applyFailures} title="Apply failed — schedule refetched, nothing assumed" />
            ) : apply.error && !showApplyInvalid ? (
              <MutationError error={apply.error} />
            ) : null}
          </section>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          {phase === "valid" ? (
            <Button onClick={handleApply} disabled={busy}>
              {apply.isSubmitting ? (
                <>
                  <LoaderCircle className="animate-spin" aria-hidden="true" />
                  Applying…
                </>
              ) : (
                "Apply Move"
              )}
            </Button>
          ) : (
            <Button onClick={handleValidate} disabled={!canValidate}>
              {validation.isSubmitting ? (
                <>
                  <LoaderCircle className="animate-spin" aria-hidden="true" />
                  Validating…
                </>
              ) : (
                "Validate Move"
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Details-only dialog for locked / specialization classes: no move mode. */
function DetailsDialog({ cls, periods, open, onOpenChange }) {
  const locked = isLocked(cls);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {locked ? <Lock aria-hidden="true" /> : <Sparkles aria-hidden="true" />}
            {cls.subject}
          </DialogTitle>
          <DialogDescription>
            {locked
              ? "This class cannot be manually moved."
              : "This class belongs to a specialization cohort."}
          </DialogDescription>
        </DialogHeader>
        <CurrentPlacement cls={cls} periods={periods} />
        {locked ? (
          <Alert variant="warning">
            <Lock aria-hidden="true" />
            <AlertTitle>Fixed by a locked scheduling constraint</AlertTitle>
            <AlertDescription>
              This class is pinned by an interdepartment / fixed-block constraint (locked block{" "}
              {cls.locked_block_id ?? "—"}). The timetable editor never moves it, and the backend rejects any
              direct move request for it.
            </AlertDescription>
          </Alert>
        ) : (
          <Alert variant="info">
            <Sparkles aria-hidden="true" />
            <AlertTitle>Synchronized specialization placement</AlertTitle>
            <AlertDescription>
              {cls.specialization ? (
                <p>
                  Part of specialization <strong>{cls.specialization}</strong>: the cohort shares one synchronized
                  time window.
                </p>
              ) : null}
              <p className="mt-1">
                Moving one session independently would break cohort synchronization, so the backend prohibits it.
                Specialization timing is managed through the specializations workflow, not here.
              </p>
            </AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function TimetableEditorPage() {
  const query = useApi(fetchEditorData, ["schedule", "rooms"]);
  const [selectedId, setSelectedId] = useState(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [groupFilter, setGroupFilter] = useState("all");
  const [facultyFilter, setFacultyFilter] = useState("all");

  const remoteData = query.data;
  const classes = useMemo(() => remoteData?.classes ?? [], [remoteData]);
  const days = useMemo(() => remoteData?.days ?? [], [remoteData]);
  const periods = useMemo(() => remoteData?.periods ?? [], [remoteData]);
  const rooms = useMemo(() => remoteData?.rooms ?? [], [remoteData]);

  const selected = classes.find((c) => c.id === selectedId) ?? null;

  const groupOptions = useMemo(
    () => [...new Set(classes.map(groupLabel))].sort((a, b) => a.localeCompare(b)),
    [classes]
  );
  const facultyOptions = useMemo(
    () => [...new Set(classes.map((c) => c.faculty))].sort((a, b) => a.localeCompare(b)),
    [classes]
  );
  const visible = useMemo(
    () =>
      classes.filter(
        (c) =>
          (groupFilter === "all" || groupLabel(c) === groupFilter) &&
          (facultyFilter === "all" || c.faculty === facultyFilter)
      ),
    [classes, groupFilter, facultyFilter]
  );

  function handleSelect(cls) {
    setSelectedId(cls.id);
    if (isMovable(cls)) {
      setDetailsOpen(false);
      setMoveOpen(true);
    } else {
      setMoveOpen(false);
      setDetailsOpen(true);
    }
  }

  function closeDialogs() {
    setMoveOpen(false);
    setDetailsOpen(false);
  }

  /** Successful apply: close, clear stale selection, authoritative refetch. */
  function handleApplied() {
    closeDialogs();
    setSelectedId(null);
    query.retry();
  }

  function clearSelection() {
    closeDialogs();
    setSelectedId(null);
  }

  if (query.isLoading && !query.data) {
    return (
      <Page
        title="Timetable Editor"
        subtitle="Move classes with backend validation — nothing regenerates the timetable."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Editor" }]}
      >
        <PageLoading rows={8} label="Loading timetable editor…" />
      </Page>
    );
  }

  if (!query.data) {
    return (
      <Page
        title="Timetable Editor"
        subtitle="Move classes with backend validation — nothing regenerates the timetable."
        breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Editor" }]}
      >
        <QueryError error={query.error} onRetry={query.retry} />
      </Page>
    );
  }

  const empty = classes.length === 0;

  return (
    <Page
      title="Timetable Editor"
      subtitle="Select a class, validate the destination with the backend, then apply. The timetable is never regenerated here."
      breadcrumbs={[{ label: "Timetable", to: "/timetable" }, { label: "Editor" }]}
      actions={
        selected ? (
          <Button variant="outline" size="sm" onClick={clearSelection}>
            Clear selection
          </Button>
        ) : null
      }
    >
      <div className="space-y-4">
        <EditorLegend />
        {empty ? (
          <EmptyState
            icon={CalendarDays}
            title="No timetable to edit yet"
            description="No scheduled classes exist. Generate a timetable first — the editor never runs the scheduler itself."
            action={
              <Button asChild className="mt-2">
                <Link to="/timetable">Go to timetable generation</Link>
              </Button>
            }
          />
        ) : (
          <>
            <Panel
              accent="steel"
              title="View controls"
              description="Filters only change what the grid shows — every move is still validated against the full schedule by the backend."
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div>
                  <Label htmlFor="editor-group-filter">Section / group</Label>
                  <Select value={groupFilter} onValueChange={setGroupFilter}>
                    <SelectTrigger id="editor-group-filter" className="mt-1.5">
                      <SelectValue placeholder="All groups" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All groups</SelectItem>
                      {groupOptions.map((g) => (
                        <SelectItem key={g} value={g}>
                          {g}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label htmlFor="editor-faculty-filter">Faculty</Label>
                  <Select value={facultyFilter} onValueChange={setFacultyFilter}>
                    <SelectTrigger id="editor-faculty-filter" className="mt-1.5">
                      <SelectValue placeholder="All faculty" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All faculty</SelectItem>
                      {facultyOptions.map((f) => (
                        <SelectItem key={f} value={f}>
                          {f}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <p className="text-sm text-muted-foreground" role="status">
                    Showing {visible.length} of {classes.length}{" "}
                    {classes.length === 1 ? "class" : "classes"}
                    {days.length > 0 && periods.length > 0 ? (
                      <>
                        {" "}· {days.length} days × {periods.length} periods
                      </>
                    ) : null}
                  </p>
                </div>
              </div>
            </Panel>
            {visible.length === 0 ? (
              <EmptyState
                icon={CalendarDays}
                title="No classes match these filters"
                description="Loosen the section/group or faculty filter to see classes again."
              />
            ) : (
              <EditorGrid
                days={days}
                periods={periods}
                classes={visible}
                selectedId={selectedId}
                onSelect={handleSelect}
              />
            )}
            <p className="text-xs text-muted-foreground">
              Click a class to {`move it (movable classes) or inspect it (fixed and specialization classes)`}.
              Multi-period blocks show as one card plus continuation strips — the whole block always moves together,
              and block length cannot be changed here.
            </p>
            <div>
              <Button asChild variant="outline" size="sm">
                <Link to="/timetable">
                  <ArrowLeft aria-hidden="true" />
                  Back
                </Link>
              </Button>
            </div>
          </>
        )}
      </div>

      {selected && isMovable(selected) ? (
        <MoveDialog
          key={selected.id}
          cls={selected}
          days={days}
          periods={periods}
          rooms={rooms}
          classes={classes}
          open={moveOpen}
          onOpenChange={(open) => {
            if (!open) clearSelection();
            else setMoveOpen(true);
          }}
          onApplied={handleApplied}
          onStale={query.retry}
        />
      ) : null}
      {selected && !isMovable(selected) ? (
        <DetailsDialog
          cls={selected}
          periods={periods}
          open={detailsOpen}
          onOpenChange={(open) => {
            if (!open) clearSelection();
            else setDetailsOpen(true);
          }}
        />
      ) : null}
    </Page>
  );
}
