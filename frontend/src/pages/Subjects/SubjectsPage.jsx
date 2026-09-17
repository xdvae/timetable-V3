import { BookOpen } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { EmptyState, PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.jsx";
import { useApi } from "@/hooks/use-api.js";
import { getSubjects } from "@/services/api/subjects.js";

function Hours({ value, unit }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">—</span>;
  }
  return <span className="tabular-nums">{`${value} ${unit}`}</span>;
}

export function SubjectsPage() {
  const { data, error, isLoading, retry } = useApi(getSubjects);

  if (isLoading && !data) {
    return (
      <Page title="Subjects" subtitle="Subject catalog with default weekly hours.">
        <PageLoading rows={6} label="Loading subjects…" />
      </Page>
    );
  }

  if (error && !data) {
    return (
      <Page title="Subjects" subtitle="Subject catalog with default weekly hours.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  const subjects = data.subjects ?? [];

  return (
    <Page
      title="Subjects"
      subtitle={
        subjects.length === 0
          ? "Subject catalog with default weekly hours."
          : `${subjects.length} ${subjects.length === 1 ? "subject" : "subjects"} · program / year → subject → teaching assignment`
      }
    >
      {subjects.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="No subjects yet"
          description="Subjects added in the backend will appear here with credits and weekly theory/practical hours."
        />
      ) : (
        <Panel accent="steel" title="All subjects">
          <Table aria-label="Subjects">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Code</TableHead>
                <TableHead scope="col">Name</TableHead>
                <TableHead scope="col">Program / Year</TableHead>
                <TableHead scope="col">Credits</TableHead>
                <TableHead scope="col">Theory</TableHead>
                <TableHead scope="col">Practical</TableHead>
                <TableHead scope="col">Block</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {subjects.map((subject) => (
                <TableRow key={subject.id}>
                  <TableCell className="font-medium text-ink">
                    {subject.code || <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>{subject.name}</TableCell>
                  <TableCell>{`${subject.program_name ?? "?"} · ${subject.year_label ?? "?"}`}</TableCell>
                  <TableCell className="tabular-nums">
                    {subject.credits ?? <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>
                    <Hours value={subject.theory_hours_per_week} unit="hrs/wk" />
                  </TableCell>
                  <TableCell>
                    <Hours value={subject.practical_hours_per_week} unit="hrs/wk" />
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {subject.practical_block_length != null ? (
                      `${subject.practical_block_length} periods`
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
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
