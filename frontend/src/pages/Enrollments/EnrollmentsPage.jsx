import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Layers, UsersRound } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getEnrollmentSections, getEnrollments } from "@/services/api/enrollments.js";

export function EnrollmentsPage() {
  const { data, error, isLoading, retry } = useApi(getEnrollments);

  if (isLoading && !data) {
    return (
      <Page
        title="Enrollments & Sections"
        subtitle="Cohorts with auto-generated sections and lab groups."
      >
        <PageLoading rows={6} label="Loading enrollments…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Enrollments & Sections"
        subtitle="Cohorts with auto-generated sections and lab groups."
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const enrollments = data.enrollments ?? [];

  return (
    <Page
      title="Enrollments & Sections"
      subtitle={
        enrollments.length === 0
          ? "Cohorts with auto-generated sections and lab groups."
          : `${enrollments.length} ${enrollments.length === 1 ? "enrollment" : "enrollments"} · program → enrollment → section → lab group`
      }
    >
      {enrollments.length === 0 ? (
        <EmptyState
          icon={UsersRound}
          title="No enrollments yet"
          description="Enrollments added in the backend will appear here with their program, year, and student count."
        />
      ) : (
        <Panel accent="steel" title="All enrollments">
          <Table aria-label="Enrollments">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Program</TableHead>
                <TableHead scope="col">Year</TableHead>
                <TableHead scope="col">Total Students</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {enrollments.map((enrollment) => (
                <TableRow key={enrollment.id}>
                  <TableCell className="font-medium text-ink">{enrollment.program_name}</TableCell>
                  <TableCell>{enrollment.year_label}</TableCell>
                  <TableCell className="tabular-nums">
                    {enrollment.total_students} students
                  </TableCell>
                  <TableCell className="text-right">
                    <Button asChild variant="outline" size="sm">
                      <Link
                        to={`/enrollments/${enrollment.id}/sections`}
                        aria-label={`View sections for ${enrollment.program_name} ${enrollment.year_label}`}
                      >
                        <Layers aria-hidden="true" />
                        View Sections
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Panel>
      )}
    </Page>
  );
}

export function SectionsPage() {
  const { eid } = useParams();
  const fetcher = useCallback(() => getEnrollmentSections(eid), [eid]);
  const { data, error, isLoading, retry } = useApi(fetcher);

  if (isLoading && !data) {
    return (
      <Page
        title="Sections"
        subtitle="Auto-generated sections and lab groups for one enrollment."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections" },
        ]}
      >
        <PageLoading rows={5} label="Loading sections…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Sections"
        subtitle="Auto-generated sections and lab groups for one enrollment."
        breadcrumbs={[
          { label: "Enrollments", to: "/enrollments" },
          { label: "Sections" },
        ]}
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const enrollment = data.enrollment ?? {};
  const sections = data.sections ?? [];
  const labGroupCount = sections.reduce(
    (total, section) => total + (section.lab_groups?.length ?? 0),
    0
  );
  const contextLabel = `${enrollment.program_name ?? "?"} · ${enrollment.year_label ?? "?"}`;

  return (
    <Page
      title={`Sections — ${contextLabel}`}
      subtitle={
        sections.length === 0
          ? "Auto-generated sections and lab groups for one enrollment."
          : `${sections.length} ${sections.length === 1 ? "section" : "sections"} · ${labGroupCount} lab ${labGroupCount === 1 ? "group" : "groups"} · ${enrollment.total_students ?? 0} students total`
      }
      breadcrumbs={[
        { label: "Enrollments", to: "/enrollments" },
        { label: contextLabel },
      ]}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link to="/enrollments">
            <ArrowLeft aria-hidden="true" />
            Back to Enrollments
          </Link>
        </Button>
      }
    >
      <div className="space-y-5">
        <Panel
          accent="brass"
          title="Enrollment"
          description="Program, year, and total students for this cohort."
        >
          <dl className="grid gap-3 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Program</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink">
                {enrollment.program_name ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Year</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink">
                {enrollment.year_label ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Total students</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink tabular-nums">
                {enrollment.total_students ?? "—"}
              </dd>
            </div>
          </dl>
        </Panel>

        {sections.length === 0 ? (
          <EmptyState
            icon={Layers}
            title="No sections for this enrollment"
            description="Sections are auto-generated when the enrollment is created in the backend."
          />
        ) : (
          <div className="grid gap-5 xl:grid-cols-2">
            {sections.map((section) => (
              <Panel
                key={section.id}
                accent="steel"
                title={section.name}
                description={`${section.student_count} students · ${section.lab_groups?.length ?? 0} lab ${(section.lab_groups?.length ?? 0) === 1 ? "group" : "groups"}`}
              >
                {(section.lab_groups?.length ?? 0) === 0 ? (
                  <p className="text-sm text-muted-foreground">No lab groups in this section.</p>
                ) : (
                  <Table aria-label={`Lab groups in ${section.name}`}>
                    <TableHeader>
                      <TableRow>
                        <TableHead scope="col">Lab Group</TableHead>
                        <TableHead scope="col">Students</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(section.lab_groups ?? []).map((group) => (
                        <TableRow key={group.id}>
                          <TableCell>
                            <Badge variant="secondary">{group.name}</Badge>
                          </TableCell>
                          <TableCell className="tabular-nums">
                            {group.student_count} students
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </Panel>
            ))}
          </div>
        )}
      </div>
    </Page>
  );
}
