import { TimetableClassBlock } from "./TimetableClassBlock.jsx";
import { cn } from "@/lib/utils";

const DAY_COL = "120px";
const PERIOD_MIN = "132px";

/**
 * Day × period grid rendered with native CSS Grid (no calendar library,
 * no colspans, no pixel positioning). The backend already computes lanes:
 * each lane is one grid row for that day, multi-period blocks span columns
 * via `gridColumn`, and parallel sessions stack as separate rows under the
 * same day label — the same semantics as the Jinja timetable.
 */
export function TimetableGrid({ periods, dayRows, labelledBy }) {
  const periodCount = periods.length;
  const columns = `${DAY_COL} repeat(${periodCount}, minmax(${PERIOD_MIN}, 1fr))`;
  const minWidth = `calc(${DAY_COL} + ${periodCount} * ${PERIOD_MIN})`;

  return (
    <div className="overflow-x-auto rounded-lg border border-line" role="grid" aria-labelledby={labelledBy}>
      {/* Period header */}
      <div className="grid gap-px bg-line" style={{ gridTemplateColumns: columns, minWidth }}>
        <div
          role="columnheader"
          className="bg-muted px-2 py-2 text-xs font-semibold text-ink"
        >
          Day / Time
        </div>
        {periods.map((period, index) => (
          <div
            key={`${period}-${index}`}
            role="columnheader"
            className="bg-muted px-2 py-2 text-center text-xs font-semibold whitespace-normal text-ink tabular-nums"
          >
            {period}
          </div>
        ))}
      </div>

      {/* One block per day; the day label spans that day's lanes. */}
      {dayRows.map((row) => (
        <div
          key={row.day}
          role="row"
          className="grid gap-px border-t border-line bg-line"
          style={{ gridTemplateColumns: columns, minWidth }}
          aria-label={row.day}
        >
          <div
            role="rowheader"
            className="flex items-center bg-steel-tint px-2 py-2 text-sm font-semibold text-ink"
            style={{ gridRow: `1 / span ${row.lanes.length}` }}
          >
            {row.day}
          </div>
          {row.lanes.map((lane, laneIndex) => (
            <LaneCells key={laneIndex} lane={lane} laneIndex={laneIndex} day={row.day} />
          ))}
        </div>
      ))}
    </div>
  );
}

function LaneCells({ lane, laneIndex, day }) {
  return (
    <>
      {lane.map((cell, cellIndex) => {
        // Lane cells tile the period range contiguously (server-side
        // guarantee), so each cell starts after the previous colspans.
        const start = 2 + lane.slice(0, cellIndex).reduce((sum, prior) => sum + prior.colspan, 0);
        if (cell.empty) {
          return (
            <div
              key={cellIndex}
              role="gridcell"
              aria-label={`${day} lane ${laneIndex + 1} period ${start - 1}: no class`}
              className="min-h-[4.5rem] bg-panel"
              style={{ gridColumn: `${start} / span ${cell.colspan}`, gridRow: laneIndex + 1 }}
            />
          );
        }
        return (
          <div
            key={cellIndex}
            role="gridcell"
            className={cn("min-h-[4.5rem] bg-panel")}
            style={{ gridColumn: `${start} / span ${cell.colspan}`, gridRow: laneIndex + 1 }}
          >
            <TimetableClassBlock classInfo={cell.class} />
          </div>
        );
      })}
    </>
  );
}
