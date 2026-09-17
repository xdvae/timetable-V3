import { ClipboardCheck } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Badge } from "@/components/ui/badge.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getAssignments } from "@/services/api/assignments.js";

function SessionTypeBadge({ sessionType }) {
  const isPractical = sessionType === "practical";
  return <Badge variant={isPractical ? "lab" : "theory"}>{isPractical ? "Lab" : "Theory"}</Badge>;
}

export function AssignmentsPage() {
  const { data, error, isLoading, retry } = useApi(getAssignments);

  if (isLoading && !data) {
    return (
      <Page
        title="Teaching Assignments"
        subtitle="Who teaches what, to which section or lab group."
      >
        <PageLoading rows={6} label="Loading teaching assignments…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page
        title="Teaching Assignments"
        subtitle="Who teaches what, to which section or lab group."
      >
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const assignments = data.assignments ?? [];

  return (
    <Page
      title="Teaching Assignments"
      subtitle={
        assignments.length === 0
          ? "Who teaches what, to which section or lab group."
          : `${assignments.length} ${assignments.length === 1 ? "assignment" : "assignments"} · the main input to timetable generation`
      }
    >
      {assignments.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title="No teaching assignments yet"
          description="Assignments added in the backend will appear here: faculty, subject, group, session type, and weekly periods."
        />
      ) : (
        <Panel accent="steel" title="All teaching assignments">
          <Table aria-label="Teaching assignments">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Faculty</TableHead>
                <TableHead scope="col">Subject</TableHead>
                <TableHead scope="col">Group / Section</TableHead>
                <TableHead scope="col">Session Type</TableHead>
                <TableHead scope="col">Periods / Week</TableHead>
                <TableHead scope="col">Block Length</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.map((assignment) => (
                <TableRow key={assignment.id}>
                  <TableCell className="font-medium text-ink">{assignment.faculty_name}</TableCell>
                  <TableCell>{assignment.subject_name}</TableCell>
                  <TableCell>{assignment.group}</TableCell>
                  <TableCell>
                    <SessionTypeBadge sessionType={assignment.session_type} />
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {assignment.periods_per_week} / week
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {assignment.block_length} {assignment.block_length === 1 ? "period" : "periods"}
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
