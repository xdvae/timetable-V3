import { useRef, useState } from "react";
import { Link } from "react-router";
import { CircleAlert, CircleCheck, Download, FileUp, Upload } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Button } from "@/components/ui/button.jsx";
import { Input } from "@/components/ui/input.jsx";
import { Label } from "@/components/ui/label.jsx";
import { useToast } from "@/hooks/use-toast.js";
import { importRoomsCsv, importWorkloadCsv } from "@/services/api/import.js";

const MAX_SHOWN_ERRORS = 10;

function isCsvFile(file) {
  return file != null && /\.csv$/i.test(file.name || "");
}

/**
 * One CSV upload card. Parsing/validation/import semantics stay entirely in
 * the backend (csv_import.py); this only picks a .csv file, POSTs it as
 * multipart FormData, and renders the backend's own messages + row errors.
 */
function ImportCard({ inputId, title, description, columns, upload, successTitle, sampleHref, sampleLabel }) {
  const toast = useToast();
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [isImporting, setIsImporting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  function handleSelect(event) {
    const picked = event.target.files?.[0] ?? null;
    setResult(null);
    setError(null);
    if (picked && !isCsvFile(picked)) {
      toast.warning(`"${picked.name}" is not a .csv file. Choose a CSV file exported with the columns below.`, {
        title: "Invalid file type",
      });
      event.target.value = "";
      setFile(null);
      return;
    }
    setFile(picked);
  }

  async function handleUpload() {
    if (!file) {
      toast.warning("Choose a CSV file first.", { title: "No file selected" });
      return;
    }
    setIsImporting(true);
    setResult(null);
    setError(null);
    try {
      const response = await upload(file);
      setResult(response);
      if (response.errors?.length > 0) {
        toast.warning(response.message, { title: successTitle });
      } else {
        toast.success(response.message, { title: successTitle });
      }
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err);
      toast.error(err?.message || "Import failed.", { title: "Import failed" });
    } finally {
      setIsImporting(false);
    }
  }

  const rowErrors = result?.errors ?? [];
  const hiddenErrorCount = Math.max(0, rowErrors.length - MAX_SHOWN_ERRORS);

  return (
    <Panel accent="steel" title={title} description={description}>
      {sampleHref ? (
        <div className="mb-4">
          <Button asChild variant="outline" size="sm">
            <a href={sampleHref}>
              <Download aria-hidden="true" />
              {sampleLabel}
            </a>
          </Button>
        </div>
      ) : null}
      <p className="mb-4 text-xs text-muted-foreground">
        Columns: <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.72rem]">{columns}</code>
      </p>
      <div className="grid gap-2">
        <Label htmlFor={inputId}>CSV file</Label>
        <Input
          ref={inputRef}
          id={inputId}
          type="file"
          accept=".csv"
          disabled={isImporting}
          onChange={handleSelect}
        />
        {file ? (
          <p className="text-xs text-muted-foreground">
            Selected: <span className="font-medium text-ink">{file.name}</span>
          </p>
        ) : null}
        <div>
          <Button onClick={handleUpload} disabled={!file || isImporting}>
            <Upload aria-hidden="true" />
            {isImporting ? "Uploading…" : `Upload ${title}`}
          </Button>
        </div>
      </div>

      {result ? (
        <Alert variant={rowErrors.length > 0 ? "warning" : "success"} className="mt-4">
          <CircleCheck aria-hidden="true" />
          <AlertTitle>{successTitle}</AlertTitle>
          <AlertDescription>
            <p>{result.message}</p>
            {rowErrors.length > 0 ? (
              <>
                <p className="mt-2 font-medium">
                  Some rows had problems ({rowErrors.length}):
                </p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 font-mono text-xs">
                  {rowErrors.slice(0, MAX_SHOWN_ERRORS).map((rowError, index) => (
                    <li key={`${index}-${rowError}`}>{rowError}</li>
                  ))}
                </ul>
                {hiddenErrorCount > 0 ? (
                  <p className="mt-1 text-xs">…and {hiddenErrorCount} more rows with problems.</p>
                ) : null}
              </>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {error ? (
        <Alert variant="destructive" className="mt-4">
          <CircleAlert aria-hidden="true" />
          <AlertTitle>Import failed</AlertTitle>
          <AlertDescription>
            <p>{error.message || "Something went wrong while importing."}</p>
            {error.fieldErrors?.file ? <p className="mt-1">{error.fieldErrors.file}</p> : null}
          </AlertDescription>
        </Alert>
      ) : null}
    </Panel>
  );
}

export function ImportPage() {
  return (
    <Page
      title="Import CSV"
      subtitle="Two files: one for rooms, one for the full teaching workload (faculty + subjects + sections in one sheet, like a Faculty Load Sheet). Sections, lab groups, subjects, faculty and programs are all created automatically from the workload file."
    >
      <div className="grid gap-5 xl:grid-cols-2">
        <ImportCard
          inputId="rooms-csv"
          title="Rooms CSV"
          description="Theory rooms and labs with capacity. Existing rooms are matched by name and updated in place."
          columns="name, room_type (theory/lab), capacity, equipment_count (optional, labs only)"
          upload={importRoomsCsv}
          successTitle="Rooms import finished"
          sampleHref="/import/sample/rooms"
          sampleLabel="Download sample rooms CSV"
        />
        <ImportCard
          inputId="workload-csv"
          title="Workload CSV"
          description="One row = one (section, subject, faculty) teaching assignment. Practical rows fan out into one assignment per auto-generated lab group."
          columns="program, year_label, section, total_students, faculty_name, faculty_type, subject_code, subject_name, session_type (theory/practical), credits, periods_per_week, block_length"
          upload={importWorkloadCsv}
          successTitle="Workload import finished"
          sampleHref="/import/sample/workload"
          sampleLabel="Download sample workload CSV"
        />
      </div>

      <div className="mt-5">
        <Panel accent="brass" title="Notes">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
            <li>
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">section</code> should be an
              exact section name with its real student count in{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">total_students</code> —
              sections are created exactly as given, not auto-split.
            </li>
            <li>
              Lab groups are auto-generated per section using the{" "}
              <Link to="/config" className="text-steel underline-offset-4 hover:underline">
                Config
              </Link>{" "}
              max lab group size, the first time that section is seen.
            </li>
            <li>
              Re-uploading is safe — existing rooms/faculty/subjects/sections/assignments are matched by
              name and not duplicated (rooms are updated in place).
            </li>
            <li>
              After importing both files, go to{" "}
              <Link to="/timetable" className="text-steel underline-offset-4 hover:underline">
                Timetable
              </Link>{" "}
              and click Generate.
            </li>
          </ul>
          <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
            <FileUp className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            Only .csv files are accepted. Files are validated row-by-row on the server; any row problems
            are listed above without blocking the valid rows.
          </p>
        </Panel>
      </div>
    </Page>
  );
}
