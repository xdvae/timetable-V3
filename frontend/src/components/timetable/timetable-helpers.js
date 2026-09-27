/**
 * Phase 6R — shared timetable UX helpers (pure, display-only).
 *
 * Everything here is derived from already-fetched payloads: no network,
 * no mutation, no invalidation, no scheduler semantics. The editor page
 * reuses the lock/spec/movable predicates so both timetable surfaces
 * agree on what "fixed" and "specialization" mean.
 */

/** Section/group label for one editor ScheduledClass row. */
export function groupLabel(cls) {
  return cls.specialization ?? cls.lab_group ?? cls.section ?? "?";
}

/** True for classes pinned by a locked scheduling constraint. */
export function isLocked(cls) {
  return Boolean(cls?.is_locked) || cls?.locked_block_id != null;
}

/**
 * True for specialization-cohort classes. Fail-safe: a row carrying a
 * specialization slot link is spec-linked even when the name is absent
 * (mirrors the Phase 6O editor rule).
 */
export function isSpecialization(cls) {
  if (!cls || typeof cls !== "object") return false;
  return cls.specialization_id != null || cls.slot_id != null || cls.specialization != null;
}

/** Movable through the dialog editor: neither locked nor spec-linked. */
export function isMovable(cls) {
  if (!cls || typeof cls !== "object") return false;
  return !isLocked(cls) && !isSpecialization(cls);
}

const JS_DAY_TO_ABBREV = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Informational today abbreviation ("Mon" … "Sun") for highlighting the
 * current day column. Computed once by the caller (no timer, no refetch);
 * returns null when the date is unusable rather than fabricating a day.
 */
export function todayAbbrev(now = new Date()) {
  try {
    const day = now?.getDay?.();
    if (!Number.isInteger(day) || day < 0 || day > 6) return null;
    return JS_DAY_TO_ABBREV[day];
  } catch {
    return null;
  }
}

/** Client-side day filter for read-only lane rows. "all" returns every row. */
export function filterDayRows(dayRows, day) {
  if (!Array.isArray(dayRows)) return [];
  if (day == null || day === "all") return dayRows;
  return dayRows.filter((row) => row?.day === day);
}

/** Count rendered (non-empty) lane cells by kind for a context summary. */
export function summarizeDayRows(dayRows) {
  const summary = { total: 0, theory: 0, lab: 0, multi: 0, fixed: 0, spec: 0 };
  for (const row of dayRows ?? []) {
    for (const lane of row?.lanes ?? []) {
      for (const cell of lane ?? []) {
        if (cell?.empty) continue;
        const info = cell?.class;
        if (!info) continue;
        summary.total += 1;
        if (info.session_type === "practical") summary.lab += 1;
        else summary.theory += 1;
        if ((info.length ?? 1) > 1) summary.multi += 1;
        if (info.is_locked || info.locked_block_id != null) summary.fixed += 1;
        if (info.specialization_id != null || info.specialization != null) summary.spec += 1;
      }
    }
  }
  return summary;
}

/** Count editor ScheduledClass rows by movability for a context summary. */
export function summarizeEditorClasses(classes) {
  const summary = { total: 0, movable: 0, fixed: 0, spec: 0, multi: 0 };
  for (const cls of classes ?? []) {
    summary.total += 1;
    if (isLocked(cls)) summary.fixed += 1;
    else if (isSpecialization(cls)) summary.spec += 1;
    else summary.movable += 1;
    if ((cls?.length ?? 1) > 1) summary.multi += 1;
  }
  return summary;
}
