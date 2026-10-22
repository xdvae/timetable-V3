import { BookOpenCheck, UsersRound } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getOverview } from "@/services/api/overview.js";

function SectionCard({ section }) {
  const labGroups = section.lab_groups ?? [];
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-ink">{section.name}</p>
        <Badge variant="secondary" className="tabular-nums">
          {section.student_count} students
        </Badge>
      </div>
      {labGroups.length === 0 ? (
        <p className="text-xs text-muted-foreground">No lab groups.</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Lab groups in ${section.name}`}>
          {labGroups.map((group) => (
            <li key={group.id}>
              <Badge variant="outline" className="tabular-nums">
                {group.name} — {group.student_count}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SectionsTab({ enrollments }) {
  if (enrollments.length === 0) {
    return <p className="text-sm text-muted-foreground">No enrollments yet.</p>;
  }
  return (
    <div className="space-y-5">
      {enrollments.map((enrollment) => {
        const sections = enrollment.sections ?? [];
        return (
          <Panel
            key={enrollment.id}
            accent="steel"
            title={`${enrollment.program_name} · ${enrollment.year_label}`}
            description={`${enrollment.total_students} students · ${sections.length} ${sections.length === 1 ? "section" : "sections"}`}
          >
            {sections.length === 0 ? (
              <p className="text-sm text-muted-foreground">No sections in this enrollment.</p>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {sections.map((section) => (
                  <SectionCard key={section.id} section={section} />
                ))}
              </div>
            )}
          </Panel>
        );
      })}
    </div>
  );
}

function LoadBadge({ load, max }) {
  const overMax = max != null && load > max;
  return (
    <Badge variant={overMax ? "danger" : "secondary"} className="tabular-nums">
      {load}
      {max != null ? `/${max}` : ""} hrs/wk{overMax ? " (over max)" : ""}
    </Badge>
  );
}

function FacultyCard({ member }) {
  const assignments = member.assignments ?? [];
  return (
    <Panel
      accent="sage"
      title={member.name}
      description={member.faculty_type || "regular"}
      actions={<LoadBadge load={member.weekly_load ?? 0} max={member.weekly_max_hours} />}
    >
      {assignments.length === 0 ? (
        <p className="text-sm text-muted-foreground">No assignments yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {assignments.map((assignment) => (
            <li key={assignment.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="flex min-w-0 items-center gap-2">
                <Badge variant={assignment.session_type === "practical" ? "lab" : "theory"}>
                  {assignment.session_type === "practical" ? "Lab" : "Th"}
                </Badge>
                <span className="truncate">
                  {assignment.subject_name}{" "}
                  <span className="text-muted-foreground">— {assignment.group}</span>
                </span>
              </span>
              <span className="shrink-0 text-muted-foreground tabular-nums">
                {assignment.periods_per_week} hrs/wk
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function FacultyTab({ faculty }) {
  if (faculty.length === 0) {
    return <p className="text-sm text-muted-foreground">No faculty yet.</p>;
  }
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      {faculty.map((member) => (
        <FacultyCard key={member.id} member={member} />
      ))}
    </div>
  );
}

export function OverviewPage() {
  const { data, error, isLoading, retry } = useApi(getOverview, ["overview"]);

  if (isLoading && !data) {
    return (
      <Page title="Overview" subtitle="Sections and lab groups at a glance, and who's teaching what.">
        <PageLoading rows={6} label="Loading overview…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page title="Overview" subtitle="Sections and lab groups at a glance, and who's teaching what.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const enrollments = data.enrollments ?? [];
  const faculty = data.faculty ?? [];

  return (
    <Page title="Overview" subtitle="Sections and lab groups at a glance, and who's teaching what.">
      <Tabs defaultValue="sections">
        <TabsList aria-label="Overview views">
          <TabsTrigger value="sections">
            <UsersRound aria-hidden="true" />
            Sections &amp; Groups
          </TabsTrigger>
          <TabsTrigger value="faculty">
            <BookOpenCheck aria-hidden="true" />
            Faculty Workload
          </TabsTrigger>
        </TabsList>
        <TabsContent value="sections">
          <SectionsTab enrollments={enrollments} />
        </TabsContent>
        <TabsContent value="faculty">
          <FacultyTab faculty={faculty} />
        </TabsContent>
      </Tabs>
    </Page>
  );
}
