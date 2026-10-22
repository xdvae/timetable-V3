import { useRef, useState } from "react";
import { Link } from "react-router";
import { CircleAlert, CircleCheck, Download, FileUp, Upload } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert.jsx";
import { Button } from "@/components/ui/button.jsx";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer.jsx";
import { Input } from "@/components/ui/input.jsx";
import { Label } from "@/components/ui/label.jsx";
import { useToast } from "@/hooks/use-toast.js";
import { getImportRowErrors, safeMessage } from "@/lib/failures.js";
import { emitOnSuccess, IMPORT_WORKLOAD_DOMAINS, ROOMS_DOMAINS } from "@/lib/propagation.js";
import { importRoomsCsv, importWorkloadCsv } from "@/services/api/import.js";

const MAX_SHOWN_ERRORS = 10;

function isCsvFile(file) {
  return file != null && /\.csv$/i.test(file.name || "");
}

function DrawerInfoCard({ title, badge, children }) {
  return (
    <div className="rounded-2xl border border-border/80 bg-muted/20 p-4 transition-colors hover:border-border">
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        {badge ? (
          <span className="rounded-full bg-brass/15 px-2.5 py-0.5 text-[11px] font-medium text-brass-dark">
            {badge}
          </span>
        ) : null}
      </div>
      <div className="text-xs text-muted-foreground leading-relaxed space-y-1.5">
        {children}
      </div>
    </div>
  );
}

function ImportInfoDrawer() {
  const [open, setOpen] = useState(false);

  return (
    <Drawer open={open} onOpenChange={setOpen} direction="right">
      <DrawerTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="rounded-full gap-2 px-3.5 py-1.5 text-xs font-medium border-[#dfe4ed] hover:border-brass/40 hover:bg-brass/5 text-ink shadow-2xs transition-all cursor-pointer"
        >
          <div className="flex size-4 items-center justify-center rounded-full bg-brass/20 text-brass text-[10px] font-bold">
            i
          </div>
          <span>Information</span>
        </Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>CSV Import Specifications</DrawerTitle>
          <DrawerDescription>
            Required columns, formatting rules, and auto-generation guidelines for uploading data.
          </DrawerDescription>
        </DrawerHeader>
        <div className="flex-1 overflow-y-auto p-6 space-y-3.5">
          <DrawerInfoCard title="Rooms CSV Columns" badge="4 fields">
            <p className="mb-2">Theory classrooms and laboratories with their seating and equipment capacities:</p>
            <div className="rounded-lg bg-muted/60 border border-border/50 p-2.5 font-mono text-[0.72rem] text-ink break-all select-all">
              name, room_type (theory/lab), capacity, equipment_count (optional, labs only)
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Existing rooms are matched by name and updated in place.
            </p>
          </DrawerInfoCard>

          <DrawerInfoCard title="Workload CSV Columns" badge="12 fields">
            <p className="mb-2">One row per teaching assignment (matching a Faculty Load Sheet):</p>
            <div className="rounded-lg bg-muted/60 border border-border/50 p-2.5 font-mono text-[0.72rem] text-ink break-all select-all">
              program, year_label, section, total_students, faculty_name, faculty_type, subject_code, subject_name, session_type (theory/practical), credits, periods_per_week, block_length
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Practical rows automatically fan out into one assignment per auto-generated lab group.
            </p>
          </DrawerInfoCard>

          <DrawerInfoCard title="Section & Lab Group Rules" badge="Auto-generation">
            <ul className="list-disc pl-4 space-y-1">
              <li>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.7rem]">section</code> should be an exact section name with its real student count in <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.7rem]">total_students</code>.
              </li>
              <li>
                Lab groups are automatically created using the{" "}
                <Link to="/config" className="text-steel underline-offset-4 hover:underline">
                  Config
                </Link>{" "}
                max lab group size when the section is first imported.
              </li>
            </ul>
          </DrawerInfoCard>

          <DrawerInfoCard title="Safe Re-uploading & Validation" badge="Non-destructive">
            <ul className="list-disc pl-4 space-y-1">
              <li>Re-uploading is safe — existing rooms, faculty, subjects, sections, and assignments are matched by name without duplicates.</li>
              <li>Only <code>.csv</code> files are accepted. Files are validated row-by-row on the server.</li>
              <li>Row issues are displayed clearly without blocking valid rows.</li>
            </ul>
          </DrawerInfoCard>

          <DrawerInfoCard title="Next Steps" badge="Timetable">
            <p>
              After uploading both Rooms and Workload files, go to{" "}
              <Link to="/timetable" className="text-steel font-medium underline-offset-4 hover:underline">
                Timetable
              </Link>{" "}
              and click <strong>Generate</strong>.
            </p>
          </DrawerInfoCard>
        </div>
        <DrawerFooter>
          <DrawerClose asChild>
            <Button variant="outline" className="w-full sm:w-auto">
              Close
            </Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}

/**
 * One CSV upload card. Parsing/validation/import semantics stay entirely in
 * the backend (csv_import.py); this only picks a .csv file, POSTs it as
 * multipart FormData, and renders the backend's own messages + row errors.
 */
function ImportCard({ inputId, title, description, upload, successTitle, sampleHref, sampleLabel, invalidateOn }) {
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
      toast.warning(`"${picked.name}" is not a .csv file. Choose a valid CSV file.`, {
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
      emitOnSuccess({ ok: true }, invalidateOn);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err);
      toast.error(safeMessage(err?.message, "Import failed."), { title: "Import failed" });
    } finally {
      setIsImporting(false);
    }
  }

  const rowErrors = getImportRowErrors(result);
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
            <p>{safeMessage(result.message, "Import finished.")}</p>
            {rowErrors.length > 0 ? (
              <>
                <p className="mt-2 font-medium">
                  Some rows had problems ({rowErrors.length}):
                </p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 font-mono text-xs">
                  {rowErrors.slice(0, MAX_SHOWN_ERRORS).map((rowError, index) => (
                    <li key={`${index}-${safeMessage(rowError).slice(0, 80)}`}>
                      {safeMessage(rowError)}
                    </li>
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
            <p>{safeMessage(error.message, "Something went wrong while importing.")}</p>
            {safeMessage(error.fieldErrors?.file, "") ? (
              <p className="mt-1">{safeMessage(error.fieldErrors.file)}</p>
            ) : null}
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
      subtitle="Upload rooms and teaching workload CSV spreadsheets to configure your schedule."
      actions={<ImportInfoDrawer />}
    >
      <div className="grid gap-5 xl:grid-cols-2">
        <ImportCard
          inputId="rooms-csv"
          title="Rooms CSV"
          description="Theory rooms and laboratory capacities. Existing rooms are updated in place."
          upload={importRoomsCsv}
          successTitle="Rooms import finished"
          sampleHref="/import/sample/rooms"
          sampleLabel="Download sample rooms CSV"
          invalidateOn={ROOMS_DOMAINS}
        />
        <ImportCard
          inputId="workload-csv"
          title="Workload CSV"
          description="Teaching assignments, sections, and faculty loads. Lab groups are generated automatically."
          upload={importWorkloadCsv}
          successTitle="Workload import finished"
          sampleHref="/import/sample/workload"
          sampleLabel="Download sample workload CSV"
          invalidateOn={IMPORT_WORKLOAD_DOMAINS}
        />
      </div>
    </Page>
  );
}
