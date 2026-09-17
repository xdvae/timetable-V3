import { useState } from "react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { PageLoading, QueryError } from "@/components/feedback/data-states.jsx";
import { Button } from "@/components/ui/button.jsx";
import { Input } from "@/components/ui/input.jsx";
import { Label } from "@/components/ui/label.jsx";
import { FieldError, MutationError } from "@/components/feedback/mutation.jsx";
import { useApi } from "@/hooks/use-api.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { getConfig, saveConfig } from "@/services/api/config.js";

function ConfigField({ id, label, help, error, children }) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="mt-1.5">{children}</div>
      {help ? <p className="mt-1 text-xs text-muted-foreground">{help}</p> : null}
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}

/**
 * Editable scheduling configuration. All fields mirror the Jinja config
 * form; validation stays server-side and field errors map back onto inputs.
 * Remounted (via key) whenever fresh config arrives so the form always
 * starts from backend truth.
 */
function ConfigForm({ initial, onSaved }) {
  const toast = useToast();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(saveConfig);
  const [sessionName, setSessionName] = useState(initial.session_name ?? "");
  const [maxSectionSize, setMaxSectionSize] = useState(initial.max_section_size ?? "");
  const [maxLabGroupSize, setMaxLabGroupSize] = useState(initial.max_lab_group_size ?? "");
  const [workingDays, setWorkingDays] = useState(initial.working_days ?? "");
  const [periods, setPeriods] = useState(initial.periods ?? "");
  const [breakAfter, setBreakAfter] = useState(initial.break_after_periods ?? "");
  const [maxConsecutive, setMaxConsecutive] = useState(initial.max_consecutive_teaching ?? "");

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      session_name: sessionName,
      max_section_size: maxSectionSize,
      max_lab_group_size: maxLabGroupSize,
      working_days: workingDays,
      periods,
      break_after_periods: breakAfter,
      max_consecutive_teaching: maxConsecutive,
    });
    if (result.ok) {
      toast.success(result.data.message || "Configuration saved.");
      onSaved();
    } else if (result.error) {
      toast.error(result.error.message || "Could not save configuration.");
    }
  }

  const described = (id, field) => (fieldErrors[field] ? `${id}-error` : undefined);

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <MutationError error={error && !error.fieldErrors ? error : null} />
      <Panel accent="steel" title="Session / General">
        <ConfigField id="session_name" label="Session name" error={fieldErrors.session_name}>
          <Input
            id="session_name"
            value={sessionName}
            onChange={(e) => setSessionName(e.target.value)}
            disabled={isSubmitting}
            aria-describedby={described("session_name", "session_name")}
          />
        </ConfigField>
      </Panel>

      <Panel accent="steel" title="Capacity" description="How cohorts are split into sections and lab groups.">
        <div className="grid gap-4 sm:grid-cols-2">
          <ConfigField
            id="max_section_size"
            label="Max section size"
            help="A section is split into more sections once it exceeds this."
            error={fieldErrors.max_section_size}
          >
            <Input
              id="max_section_size"
              type="number"
              required
              value={maxSectionSize}
              onChange={(e) => setMaxSectionSize(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={described("max_section_size", "max_section_size")}
            />
          </ConfigField>
          <ConfigField
            id="max_lab_group_size"
            label="Max lab group size"
            help="A section is split into lab groups once it exceeds this (equipment limit)."
            error={fieldErrors.max_lab_group_size}
          >
            <Input
              id="max_lab_group_size"
              type="number"
              required
              value={maxLabGroupSize}
              onChange={(e) => setMaxLabGroupSize(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={described("max_lab_group_size", "max_lab_group_size")}
            />
          </ConfigField>
        </div>
      </Panel>

      <Panel accent="sage" title="Days & Periods">
        <div className="space-y-4">
          <ConfigField id="working_days" label="Working days (comma separated)" error={fieldErrors.working_days}>
            <Input
              id="working_days"
              value={workingDays}
              onChange={(e) => setWorkingDays(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={described("working_days", "working_days")}
            />
          </ConfigField>
          <ConfigField
            id="periods"
            label="Periods (pipe-separated, in order)"
            help="e.g. 09:00-10:00|10:00-11:00|... — the index (0,1,2...) is what's used internally."
            error={fieldErrors.periods}
          >
            <Input
              id="periods"
              value={periods}
              onChange={(e) => setPeriods(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={described("periods", "periods")}
            />
          </ConfigField>
        </div>
      </Panel>

      <Panel accent="sage" title="Scheduling Rules">
        <div className="grid gap-4 sm:grid-cols-2">
          <ConfigField
            id="break_after_periods"
            label="Lunch break after period # (blank = none)"
            help="e.g. 3 means break falls between period index 2 and 3 — no class may span across it."
            error={fieldErrors.break_after_periods}
          >
            <Input
              id="break_after_periods"
              type="number"
              value={breakAfter}
              onChange={(e) => setBreakAfter(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={described("break_after_periods", "break_after_periods")}
            />
          </ConfigField>
          <ConfigField
            id="max_consecutive_teaching"
            label="Max consecutive teaching periods before a faculty break is required"
            error={fieldErrors.max_consecutive_teaching}
          >
            <Input
              id="max_consecutive_teaching"
              type="number"
              required
              value={maxConsecutive}
              onChange={(e) => setMaxConsecutive(e.target.value)}
              disabled={isSubmitting}
              aria-describedby={described("max_consecutive_teaching", "max_consecutive_teaching")}
            />
          </ConfigField>
        </div>
      </Panel>

      <div>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
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

  return (
    <Page title="Configuration" subtitle={config.session_name || "Scheduling configuration for this institution."}>
      <div className="max-w-[720px]">
        <ConfigForm key={config.id} initial={config} onSaved={retry} />
      </div>
    </Page>
  );
}
