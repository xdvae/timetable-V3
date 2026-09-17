import { Badge } from "@/components/ui/badge.jsx";
import { cn } from "@/lib/utils";

/**
 * One scheduled class block. Visual treatment reuses the backend's own
 * `css_class` (cell-theory / cell-practical, defined in index.css) so the
 * steel-theory / sage-lab semantics match the Jinja UI exactly. Theory/Lab
 * is always a text badge as well — never color alone. Unknown values arrive
 * from the backend already rendered as "?" and are passed through.
 */
export function TimetableClassBlock({ classInfo, className }) {
  const isPractical = classInfo.session_type === "practical";
  const label = `${classInfo.subject}, ${classInfo.kind}, ${classInfo.faculty}, ${classInfo.group}, Room ${classInfo.room}, ${classInfo.day} periods ${classInfo.start_period + 1} to ${classInfo.start_period + classInfo.length}`;
  return (
    <div
      className={cn(classInfo.css_class, "h-full min-h-[4.5rem] p-2 text-left", className)}
      role="img"
      aria-label={label}
    >
      <p className="text-[0.8rem] leading-snug font-semibold text-ink">{classInfo.subject}</p>
      <p className="mt-1">
        <Badge variant={isPractical ? "lab" : "theory"}>{classInfo.kind}</Badge>
      </p>
      <p className="mt-1 truncate text-xs text-ink">{classInfo.faculty}</p>
      <p className="truncate text-xs text-muted-foreground">
        {classInfo.group} | Room {classInfo.room}
      </p>
    </div>
  );
}
