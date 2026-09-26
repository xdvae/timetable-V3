/**
 * Structured backend validation failures ({ code, message, details }[]).
 *
 * The Flask API preserves the domain RuleResult envelope on 422s as
 * `{ error, code, details, failures }` (see ApiError.payload). These
 * helpers turn that envelope into human-readable UI without inventing
 * explanations the backend did not provide.
 */

/** Structured backend failures if present, otherwise an empty list. */
export function getFailures(error) {
  const failures = error?.payload?.failures;
  return Array.isArray(failures) ? failures : [];
}

/** Short human-readable label per known backend rule code. */
export const FAILURE_LABELS = {
  FACULTY_UNAVAILABLE: "Faculty unavailable",
  FACULTY_CONFLICT: "Faculty double-booked",
  FACULTY_CONSECUTIVE: "Consecutive-teaching limit",
  LOCKED_BLOCK: "Locked timetable block",
  SPECIALIZATION_SWAP: "Incompatible specialization swap",
  SPECIALIZATION_OVERLAP: "Specialization overlap",
  SPECIALIZATION_SYNC: "Specialization out of sync",
  SPECIALIZATION_CAPACITY: "Specialization capacity",
  SPECIALIZATION_ENROLLMENT: "Specialization cohort mismatch",
  SPECIALIZATION_MEMBERSHIP: "Specialization membership",
  SPECIALIZATION_INVALID: "Invalid specialization",
  PERSISTENCE_FAILED: "Could not save",
  INVALID_SWAP: "Invalid swap",
  UNKNOWN_ASSIGNMENT: "Assignment not found",
  UNKNOWN_FACULTY: "Faculty not found",
  UNKNOWN_ROOM: "Room not found",
  ROOM_CONFLICT: "Room already occupied",
  ROOM_CAPACITY: "Room too small",
  ROOM_TYPE_MISMATCH: "Wrong room type",
  SECTION_CONFLICT: "Section already has a class",
  SECTION_HIERARCHY_CONFLICT: "Lab/section overlap",
  MAX_TWO_THEORY: "Too much consecutive theory",
  UNKNOWN_DAY: "Unknown day",
  PERIOD_OUT_OF_RANGE: "Period out of range",
  BREAK_SPAN: "Block spans the break",
  BLOCK_GEOMETRY: "Invalid block placement",
  ROOM_REQUIRED: "Room required",
  ROOM_EQUIPMENT: "Room equipment insufficient",
  ASSIGNMENT_MISMATCH: "Assignment mismatch",
  KIND_NOT_ENABLED: "Unsupported block kind",
  UNKNOWN_KIND: "Unknown block kind",
  UNKNOWN_LOCKED_BLOCK: "Fixed block not found",
  GROUP_CONFLICT: "Student group already has a class",
  UNKNOWN_PREFERENCE: "Preference not found",
  PREF_INVALID_KIND: "Unsupported preference kind",
  PREF_INVALID_DAYS: "Invalid preference days",
  PREF_INVALID_PERIOD: "Invalid preference period range",
  PREF_INVALID_WEIGHT: "Invalid preference weight",
  PREF_HARD_UNSUPPORTED: "Preferences are soft-only",
};

/** Secondary context line built only from fields the backend provided. */
export function failureContext(details) {
  if (!details || typeof details !== "object") return null;
  const bits = [];
  if (details.day != null) bits.push(`Day ${details.day}`);
  const period = details.period ?? details.start_period;
  if (period != null) bits.push(`Period ${period}`);
  if (details.scheduled_class_id != null) bits.push(`Class #${details.scheduled_class_id}`);
  if (details.conflicting_class_id != null) {
    bits.push(`conflicts with class #${details.conflicting_class_id}`);
  }
  return bits.length > 0 ? bits.join(" · ") : null;
}
