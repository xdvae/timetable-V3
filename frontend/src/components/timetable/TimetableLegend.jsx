/**
 * Theory (steel) / Lab-Practical (sage) legend, matching the Jinja
 * timetable view. Text labels carry the meaning; color is secondary.
 */
export function TimetableLegend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground" aria-label="Legend">
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] bg-steel" aria-hidden="true" />
        Theory
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block size-3 rounded-[3px] bg-sage" aria-hidden="true" />
        Lab / Practical
      </span>
    </div>
  );
}
