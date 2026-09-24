"""
Shared scheduling rules for UniSchedule (Phase 6C).

This module holds the LOGIC of the scheduling rules that already exist in
the codebase. It is deliberately:

* pure — stdlib only (`dataclasses`), no Flask, no HTTP, no React,
  no SQLAlchemy, no OR-Tools;
* operating on plain data (ints/strings/sets/dicts), never on ORM rows,
  so `scheduler.py`, `audit_schedule.py` and the future
  `schedule_validator.py` can all use it without an app context.

Design rule (Phase 6C, Part 4): Python predicates here NEVER replace
CP-SAT expressions. The solver encoding stays in `scheduler.py`; it calls
these helpers for domain pruning and documents which logical rule each
linear constraint mirrors. The audit script and the future validator call
the same helpers to check persisted/proposed placements directly.

Rule IDs mirror the Phase 6B inventory (H1..H14) plus HN1
(MAX_TWO_THEORY, added Phase 6D). Other future rules (LOCKED_BLOCK,
SPECIALIZATION_*, preferences, manual-edit rules) remain OUT OF SCOPE.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple


# ------------------------------------------------------------------ result
@dataclass(frozen=True)
class RuleResult:
    """Lightweight outcome of one logical rule check.

    `ok=True`  -> the placement/input satisfies the rule.
    `ok=False` -> `code` is a stable UPPER_SNAKE identifier, `message` is
    human-readable, `details` carries optional structured context. This is
    intentionally a subset of the future API error contract — the rule
    layer stays reusable and never formats HTTP responses.
    """
    ok: bool
    code: str = "OK"
    message: str = ""
    details: Dict = field(default_factory=dict)


def _pass() -> RuleResult:
    return RuleResult(ok=True)


def _fail(code: str, message: str, details: Optional[Dict] = None) -> RuleResult:
    return RuleResult(ok=False, code=code, message=message, details=details or {})


# ------------------------------------------------------- session-type rules
def wanted_room_type(session_type: str) -> str:
    """H3: practical sessions need labs, everything else needs theory rooms."""
    return "lab" if session_type == "practical" else "theory"


def check_room_type(room_type: str, session_type: str, group_label: str = "?") -> RuleResult:
    """H3: room-type compatibility for a single candidate room."""
    wanted = wanted_room_type(session_type)
    if room_type != wanted:
        return _fail(
            "ROOM_TYPE_MISMATCH",
            f"{session_type} session for '{group_label}' cannot use a {room_type} room "
            f"(needs a {wanted} room).",
            {"room_type": room_type, "wanted_type": wanted, "group": group_label},
        )
    return _pass()


def check_room_capacity(capacity: int, group_size: int, room_name: str = "?",
                        group_label: str = "?") -> RuleResult:
    """H2: room capacity must cover the student group."""
    if capacity < group_size:
        return _fail(
            "ROOM_CAPACITY",
            f"Room {room_name} (capacity {capacity}) cannot accommodate "
            f"'{group_label}' ({group_size} students).",
            {"room_name": room_name, "room_capacity": capacity,
             "required_capacity": group_size, "group": group_label},
        )
    return _pass()


def check_room_equipment(equipment_count: Optional[int], group_size: int,
                         room_name: str = "?", group_label: str = "?") -> RuleResult:
    """H4: lab equipment (when tracked) must cover the group. Unset == unknown, allowed."""
    if equipment_count is not None and equipment_count < group_size:
        return _fail(
            "ROOM_EQUIPMENT",
            f"Room {room_name} has {equipment_count} equipment for "
            f"{group_size} students ('{group_label}').",
            {"room_name": room_name, "equipment_count": equipment_count,
             "required_capacity": group_size, "group": group_label},
        )
    return _pass()


def check_room_compatible(room_type: str, capacity: int, equipment_count: Optional[int],
                          session_type: str, group_size: int,
                          room_name: str = "?", group_label: str = "?") -> RuleResult:
    """H2+H3+H4 combined: is one room a legal candidate for one session?

    Mirrors `compatible_rooms()` in scheduler.py (same checks, same order).
    """
    for check in (check_room_type(room_type, session_type, group_label),
                  check_room_capacity(capacity, group_size, room_name, group_label),
                  check_room_equipment(equipment_count, group_size, room_name, group_label)):
        if not check.ok:
            return check
    return _pass()


# ------------------------------------------------------------- geometry rules
def covers(start: int, length: int) -> range:
    """Period indexes covered by a block starting at `start` with `length`."""
    return range(start, start + length)


def spans_break(start: int, length: int, break_after: Optional[int]) -> bool:
    """H10: True when a block would straddle the lunch/break period boundary."""
    if break_after is None:
        return False
    return start < break_after < start + length


def check_break_geometry(start: int, length: int, break_after: Optional[int],
                         group_label: str = "?") -> RuleResult:
    """H10: no session block may span across the configured break."""
    if spans_break(start, length, break_after):
        return _fail(
            "BREAK_SPAN",
            f"Block for '{group_label}' (starts period {start}, length {length}) "
            f"spans across the break after period {break_after}.",
            {"start_period": start, "length": length,
             "break_after": break_after, "group": group_label},
        )
    return _pass()


def check_block_geometry(start: int, length: int, num_periods: int,
                         group_label: str = "?") -> RuleResult:
    """H11: a block must fit inside the configured day (0-based periods)."""
    if start < 0 or length < 1 or start + length > num_periods:
        return _fail(
            "PERIOD_OUT_OF_RANGE",
            f"Block for '{group_label}' (starts period {start}, length {length}) "
            f"does not fit in a day with {num_periods} periods.",
            {"start_period": start, "length": length,
             "num_periods": num_periods, "group": group_label},
        )
    return _pass()


def valid_starts(length: int, num_periods: int, break_after: Optional[int]) -> List[int]:
    """H10+H11: start periods where a block fits without crossing the break.

    Identical semantics to scheduler.valid_starts (kept as the single
    definition; scheduler.py delegates to this function).
    """
    starts = []
    for start in range(0, num_periods - length + 1):
        if spans_break(start, length, break_after):
            continue
        starts.append(start)
    return starts


def check_day_known(day: str, days: Iterable[str]) -> RuleResult:
    """H13: the day must be one of the configured working days."""
    day_list = list(days)
    if day not in day_list:
        return _fail(
            "UNKNOWN_DAY",
            f"'{day}' is not a configured working day ({', '.join(day_list)}).",
            {"day": day, "working_days": day_list},
        )
    return _pass()


# ------------------------------------------------------- availability rules
def slot_key(day: str, period: int) -> str:
    """Canonical unavailable-slot token, matching Faculty.unavailable_slots format."""
    return f"{day}:{period}"


def is_faculty_available(unavailable: Set[str], day: str, start: int, length: int) -> bool:
    """H9: True when none of the covered (day, period) slots is marked unavailable."""
    return all(slot_key(day, p) not in unavailable for p in covers(start, length))


def check_faculty_available(unavailable: Set[str], day: str, start: int, length: int,
                            faculty_name: str = "?") -> RuleResult:
    """H9: faculty availability for one candidate placement."""
    if not is_faculty_available(unavailable, day, start, length):
        return _fail(
            "FACULTY_UNAVAILABLE",
            f"{faculty_name} is marked unavailable for part of {day} "
            f"periods {start}–{start + length - 1}.",
            {"faculty_name": faculty_name, "day": day,
             "start_period": start, "length": length},
        )
    return _pass()


# ------------------------------------------------- assignment validity (H14)
def check_assignment_block_length(block_length: int, periods_per_week: int) -> RuleResult:
    """H14: block length must satisfy 1 <= block <= periods/week.

    Same rule (and message shape) as api_assignment_create / csv_import.
    """
    if block_length < 1 or block_length > periods_per_week:
        return _fail(
            "BLOCK_LENGTH_INVALID",
            f"Block length ({block_length}) can't exceed periods/week ({periods_per_week}).",
            {"block_length": block_length, "periods_per_week": periods_per_week},
        )
    return _pass()


# --------------------------------------- occupancy / single-booking (H5-H8)
# An occupancy map is dict[(resource_key, day, period)] -> count. Resource keys
# are room ids, faculty ids, "section:{id}" / "labgroup:{id}" group keys, or
# any hashable the caller uses consistently.
Occupancy = Dict[Tuple, int]


def add_placement(occ: Occupancy, resource_key, day: str, start: int, length: int) -> None:
    """Record one block's covered periods for one resource (mutates `occ`)."""
    for p in covers(start, length):
        occ[(resource_key, day, p)] = occ.get((resource_key, day, p), 0) + 1


def find_overlaps(occ: Occupancy) -> List[Tuple]:
    """Return sorted [(resource_key, day, period)] cells booked more than once."""
    return sorted([cell for cell, n in occ.items() if n > 1],
                  key=lambda c: (str(c[0]), str(c[1]), c[2]))


def check_no_overlap(occ: Occupancy, code: str, label: str) -> List[RuleResult]:
    """H5/H6/H7: one RuleResult per double-booked cell (empty list == valid)."""
    results = []
    for (key, day, period) in find_overlaps(occ):
        results.append(_fail(
            code,
            f"{label} double-booked: {key} on {day} at period {period}.",
            {"resource": key, "day": day, "period": period},
        ))
    return results


def find_hierarchy_overlaps(labgroup_periods: Dict[int, Set[Tuple[str, int]]],
                            section_periods: Dict[int, Set[Tuple[str, int]]],
                            labgroup_section: Dict[int, int]) -> List[Tuple[int, int, Tuple[str, int]]]:
    """H8: (lab_group_id, section_id, (day, period)) triples where a lab group's
    practical overlaps its own parent section's whole-section theory."""
    overlaps = []
    for lg_id, sec_id in labgroup_section.items():
        shared = labgroup_periods.get(lg_id, set()) & section_periods.get(sec_id, set())
        for cell in sorted(shared):
            overlaps.append((lg_id, sec_id, cell))
    return overlaps


# --------------------------------- consecutive teaching (H12, faculty side)
def max_run_length(occupied_periods: Iterable[int]) -> int:
    """Longest run of consecutive ints in `occupied_periods` (0 when empty)."""
    occ = sorted(set(occupied_periods))
    best = run = 0
    prev = None
    for p in occ:
        run = run + 1 if prev is not None and p == prev + 1 else 1
        best = max(best, run)
        prev = p
    return best


def check_faculty_consecutive(occupied_periods: Iterable[int], max_consecutive: Optional[int],
                              faculty_id=None, day: str = "?") -> RuleResult:
    """H12: a faculty member's longest same-day teaching run must stay within
    `max_consecutive`. A falsy limit disables the rule (mirrors the solver,
    whose window sum `<= max_consecutive` over binary occupancy is equivalent
    to longest-run `<= max_consecutive`)."""
    if not max_consecutive or max_consecutive <= 0:
        return _pass()
    run = max_run_length(occupied_periods)
    if run > max_consecutive:
        return _fail(
            "FACULTY_CONSECUTIVE",
            f"Faculty {faculty_id} on {day} teaches {run} periods in a row "
            f"(max allowed {max_consecutive}).",
            {"faculty_id": faculty_id, "day": day,
             "run_length": run, "max_consecutive": max_consecutive},
        )
    return _pass()


# ------------------------------------------------- coverage helper (H1 side)
def check_session_coverage(expected_counts: Dict, actual_counts: Dict) -> List[RuleResult]:
    """H1 support: every expected session (keyed by caller-chosen id, e.g.
    assignment id) must be placed exactly its expected number of times."""
    results = []
    for key in sorted(set(expected_counts) | set(actual_counts), key=str):
        exp = expected_counts.get(key, 0)
        got = actual_counts.get(key, 0)
        if exp != got:
            results.append(_fail(
                "COVERAGE_MISMATCH",
                f"Session '{key}' placed {got} time(s), expected {exp}.",
                {"session": key, "expected": exp, "actual": got},
            ))
    return results


# --------------------------- HN1: max two consecutive theory (Phase 6D)
# A student section may have at most two consecutive THEORY periods within
# one teaching segment of a day. Labs/practicals never count as theory,
# free periods naturally break the streak (occupancy-based, no counters),
# and windows never cross the configured break. Applies per section, per
# day. Independent of the faculty-side H12 rule.
HN1_WINDOW = 3
HN1_MAX_THEORY = 2


def teaching_segments(num_periods: int, break_after: Optional[int]) -> List[List[int]]:
    """Split periods 0..num_periods-1 into contiguous teaching segments.

    Mirrors the H10 break semantics exactly: with break_after=N the break
    sits between periods N-1 and N, so a block covering both is forbidden
    and no HN1 window may span it. A missing/out-of-range break yields one
    segment (consistent with spans_break() having no effect then).
    """
    if not break_after or break_after <= 0 or break_after >= num_periods:
        return [list(range(num_periods))]
    return [list(range(0, break_after)), list(range(break_after, num_periods))]


def hn1_windows(num_periods: int, break_after: Optional[int]) -> List[Tuple[int, ...]]:
    """Every 3-period window inside a single teaching segment, in order."""
    windows = []
    for seg in teaching_segments(num_periods, break_after):
        for i in range(len(seg) - HN1_WINDOW + 1):
            windows.append(tuple(seg[i:i + HN1_WINDOW]))
    return windows


def overlap_count(start: int, length: int, window: Iterable[int]) -> int:
    """Period-weighted contribution of one block to one window: the number
    of the block's covered periods lying inside the window. A length-2
    theory block fully inside contributes 2; a length-3 block, 3."""
    covered = set(covers(start, length))
    return sum(1 for p in window if p in covered)


def find_theory_streaks(theory_periods: Iterable[int], num_periods: int,
                        break_after: Optional[int]) -> List[Tuple[int, ...]]:
    """theory_periods: periods occupied by THEORY for one section on one day
    (labs and free periods simply absent). Returns the sorted violating
    3-period windows fully covered by theory (empty == valid)."""
    occ = set(theory_periods)
    return [w for w in hn1_windows(num_periods, break_after)
            if all(p in occ for p in w)]


def check_max_two_theory(theory_periods: Iterable[int], num_periods: int,
                         break_after: Optional[int], section_label: str = "?",
                         day: str = "?", section_id=None,
                         extra_details: Optional[Dict] = None) -> List[RuleResult]:
    """HN1: one RuleResult per violating window (empty list == valid)."""
    results = []
    for w in find_theory_streaks(theory_periods, num_periods, break_after):
        details = {"section_id": section_id, "section": section_label,
                   "day": day, "periods": list(w), "window": list(w)}
        if extra_details:
            details.update(extra_details)
        results.append(_fail(
            "MAX_TWO_THEORY",
            f"Section '{section_label}' has theory in periods "
            f"{w[0]}, {w[1]}, {w[2]} on {day} "
            f"(at most two consecutive theory periods allowed).",
            details,
        ))
    return results


# ----------------- HN1 capacity & demand primitives (Phase 6D.1)
# Pure planning helpers: how much theory a section-day/week can hold under
# HN1, and how much theory each section demands. Used by diagnostics and
# (in future) capacity pre-checks; never part of constraint enforcement.
def segment_theory_capacity(segment_length: int) -> int:
    """Max theory periods placeable in one contiguous segment of length L
    without three consecutive theory periods.

    Optimal pattern repeats T,T,F: every full group of 3 holds 2 theory,
    remainders hold fully. Closed form: L - L//3.
    (L=3->2, L=4->3, L=5->4, L=6->4, L=7->5, L<=0->0.)
    """
    if segment_length <= 0:
        return 0
    return segment_length - segment_length // 3


def hn1_daily_capacity(num_periods: int, break_after: Optional[int]) -> int:
    """Max theory periods one section can hold in one day under HN1:
    sum of segment capacities (windows never cross the break)."""
    return sum(segment_theory_capacity(len(seg))
               for seg in teaching_segments(num_periods, break_after))


def hn1_weekly_capacity(num_periods: int, break_after: Optional[int],
                        num_days: int) -> int:
    """Max theory periods one section can hold in a week under HN1."""
    if num_days <= 0:
        return 0
    return hn1_daily_capacity(num_periods, break_after) * num_days


def section_theory_demand(assignments) -> Dict:
    """Total required THEORY periods/week per section.

    Accepts duck-typed rows with session_type/section_id/periods_per_week
    (practicals and rows without a section never contribute).
    Returns {section_id: total_periods}.
    """
    demand: Dict = {}
    for a in assignments:
        if getattr(a, "session_type", "") != "theory":
            continue
        sid = getattr(a, "section_id", None)
        if sid is None:
            continue
        demand[sid] = demand.get(sid, 0) + (getattr(a, "periods_per_week", 0) or 0)
    return demand
