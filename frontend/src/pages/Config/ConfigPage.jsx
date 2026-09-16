import { Fragment } from "react";
import { Coffee } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getConfig } from "@/services/api/config.js";

function Definition({ term, children }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-[220px_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{term}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

function PeriodList({ periods, breakAfter }) {
  if (!periods || periods.length === 0) {
    return <p className="text-sm text-muted-foreground">No periods configured.</p>;
  }
  return (
    <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line">
      {periods.map((period, index) => {
        const [start, end] = String(period).split("-");
        const showBreakAfter = Number.isInteger(breakAfter) && breakAfter > 0 && index === breakAfter - 1;
        return (
          <Fragment key={`${period}-${index}`}>
            <li className="flex items-center gap-4 bg-panel px-4 py-2.5 text-sm">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground tabular-nums">
                {index + 1}
              </span>
              <span className="font-medium text-ink tabular-nums">{start?.trim()}</span>
              <span className="text-muted-foreground" aria-hidden="true">–</span>
              <span className="text-muted-foreground tabular-nums">{(end ?? "").trim()}</span>
              <span className="sr-only">
                Period {index + 1}, {period}
              </span>
            </li>
            {showBreakAfter ? (
              <li className="flex items-center gap-2 bg-brass/10 px-4 py-2 text-xs font-medium text-brass-dark">
                <Coffee className="size-3.5" aria-hidden="true" />
                Lunch break — no class may span across it
              </li>
            ) : null}
          </Fragment>
        );
      })}
    </ol>
  );
}

export function ConfigPage() {
  const { data: config, error, isLoading, retry } = useApi(getConfig);

  if (isLoading && !config) {
    return (
      <Page title="Configuration" subtitle="Scheduling configuration for this institution.">
        <PageLoading rows={6} label="Loading configuration…" />
      </Page>
    );
  }

  if (error && !config) {
    return (
      <Page title="Configuration" subtitle="Scheduling configuration for this institution.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const days = config.days ?? [];
  const periods = config.periods_list ?? [];

  return (
    <Page title="Configuration" subtitle={config.session_name || "Scheduling configuration for this institution."}>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-5">
          <Panel accent="steel" title="Session / General">
            <dl className="divide-y divide-line">
              <Definition term="Session name">{config.session_name || "—"}</Definition>
            </dl>
          </Panel>

          <Panel accent="steel" title="Capacity" description="How cohorts are split into sections and lab groups.">
            <dl className="divide-y divide-line">
              <Definition term="Max section size">
                {config.max_section_size} students
              </Definition>
              <Definition term="Max lab group size">
                {config.max_lab_group_size} students
              </Definition>
            </dl>
          </Panel>

          <Panel accent="steel" title="Scheduling Rules">
            <dl className="divide-y divide-line">
              <Definition term="Max consecutive teaching periods">
                {config.max_consecutive_teaching} periods
              </Definition>
              <Definition term="Lunch break">
                {config.break_after_periods
                  ? `After period ${config.break_after_periods}`
                  : "No lunch break configured"}
              </Definition>
            </dl>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel accent="sage" title="Working Days">
            {days.length === 0 ? (
              <p className="text-sm text-muted-foreground">No working days configured.</p>
            ) : (
              <ul className="flex flex-wrap gap-2" aria-label="Working days">
                {days.map((day) => (
                  <li key={day}>
                    <Badge variant="secondary">{day}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel
            accent="sage"
            title="Periods"
            description={`${periods.length} periods per day, in order.`}
          >
            <PeriodList periods={periods} breakAfter={config.break_after_periods} />
          </Panel>
        </div>
      </div>
    </Page>
  );
}
