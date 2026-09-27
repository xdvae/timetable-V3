import { Lock, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge.jsx";
import { cn } from "@/lib/utils";

/**
 * One scheduled class block. Visual treatment reuses the backend's own
 * `css_class` (cell-theory / cell-practical, defined in index.css) so the
 * steel-theory / sage-lab semantics match the Jinja UI exactly. Theory/Lab
 * is always a text badge as well — never color alone. Unknown values arrive
 * from the backend already rendered as "?" and are passed through.
 *
 * Phase 6R: duration (multi-period), Fixed (locked), and Specialization
 * state render as text badges too (never color alone), so the read-only
 * timetable answers "how long / movable / which cohort?" at a glance.
 * Truncated lines carry `title` fallbacks so no text is permanently
 * inaccessible at narrow widths.
 */
export function TimetableClassBlock({ classInfo, className }) {
  const isPractical = classInfo.session_type === "practical";
  const locked = Boolean(classInfo.is_locked) || classInfo.locked_block_id != null;
  const spec =
    !locked && (classInfo.specialization_id != null || classInfo.specialization != null);
  const length = Number.isInteger(classInfo.length) ? classInfo.length : 1;
  const multi = length > 1;
  const specName = typeof classInfo.specialization === "string" ? classInfo.specialization : null;
  const label =
    `${classInfo.subject}, ${classInfo.kind}, ${classInfo.faculty}, ${classInfo.group}, ` +
    `Room ${classInfo.room}, ${classInfo.day} periods ${classInfo.start_period + 1} to ` +
    `${classInfo.start_period + length}` +
    (multi ? ` (spans ${length} periods)` : "") +
    (locked ? " (fixed block, cannot be moved)" : "") +
    (spec ? ` (specialization${specName ? ` ${specName}` : ""}, moves only as a cohort)` : "");
  const groupRoom = `${classInfo.group} | Room ${classInfo.room}`;
  return (
    <div
      className={cn(classInfo.css_class, "h-full min-h-[4.5rem] p-2 text-left", className)}
      role="img"
      aria-label={label}
    >
      <p className="text-sm leading-snug font-semibold text-ink" title={String(classInfo.subject)}>
        {classInfo.subject}
      </p>
      <p className="mt-1 flex flex-wrap gap-1">
        <Badge variant={isPractical ? "lab" : "theory"}>{classInfo.kind}</Badge>
        {multi ? <Badge variant="outline">× {length} periods</Badge> : null}
        {locked ? (
          <Badge variant="danger">
            <Lock aria-hidden="true" />
            Fixed
          </Badge>
        ) : null}
        {spec ? (
          <Badge variant="secondary" title={specName ?? undefined}>
            <Sparkles aria-hidden="true" />
            {specName ? `Spec · ${specName}` : "Spec"}
          </Badge>
        ) : null}
      </p>
      <p className="mt-1 truncate text-xs text-ink" title={String(classInfo.faculty)}>
        {classInfo.faculty}
      </p>
      <p className="truncate text-xs text-muted-foreground" title={groupRoom}>
        {groupRoom}
      </p>
    </div>
  );
}
