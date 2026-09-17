import { School } from "lucide-react";

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
import { getPrograms } from "@/services/api/programs.js";

export function ProgramsPage() {
  const { data: programs, error, isLoading, retry } = useApi(getPrograms);

  if (isLoading && !programs) {
    return (
      <Page title="Programs" subtitle="Degree programs, e.g. BCA, B.Tech CSE.">
        <PageLoading rows={5} label="Loading programs…" />
      </Page>
    );
  }

  if (error && !programs) {
    return (
      <Page title="Programs" subtitle="Degree programs, e.g. BCA, B.Tech CSE.">
        <QueryError error={error} onRetry={retry} />
      </Page>
    );
  }

  return (
    <Page
      title="Programs"
      subtitle={
        programs.length === 0
          ? "Degree programs, e.g. BCA, B.Tech CSE."
          : `${programs.length} ${programs.length === 1 ? "program" : "programs"} · enrollments live under each program`
      }
    >
      {programs.length === 0 ? (
        <EmptyState
          icon={School}
          title="No programs yet"
          description="Programs added in the backend will appear here with their department."
        />
      ) : (
        <Panel accent="steel" title="All programs">
          <Table aria-label="Programs">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Name</TableHead>
                <TableHead scope="col">Department</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {programs.map((program) => (
                <TableRow key={program.id}>
                  <TableCell className="font-medium text-ink">{program.name}</TableCell>
                  <TableCell>
                    {program.department || <span className="text-muted-foreground">—</span>}
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
