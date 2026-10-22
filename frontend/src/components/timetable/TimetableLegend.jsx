import { Lock, Sparkles } from "lucide-react";

/**
 * Theory (steel) / Lab-Practical (sage) legend, matching the Jinja
 * timetable view. Text labels carry the meaning; color is secondary.
 *
 * Phase 6R: the read-only lane cells now carry fixed/specialization
 * state, so the legend names those badges too, plus a multi-period note.
 * (The editor keeps its own extended legend with selection states.)
 */
export function TimetableLegend() {
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
        Specialization (moves only as a cohort)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block rounded border border-line bg-muted/40 px-1 py-px font-semibold" aria-hidden="true">
          × 2 periods
        </span>
        Multi-period block (spans its periods)
      </span>
    </div>
  );
}
