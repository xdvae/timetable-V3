"""Phase 6S tests: scheduler objective quality + reproducible benchmarks.

Covers the 6S requirements without touching any real database: every test
uses duck-typed fake assignments/rooms (no ORM, no Flask, no IO), so the
harness is isolated by construction.

Contents:
  * Part 1 — objective construction (pure helpers, scaling boundaries,
    maximum lower-tier penalty, lexicographic dominance arithmetic).
  * Part 2 — objective behavior (start priority, preferred room, faculty
    time window, day-off, combination hierarchy).
  * Part 3 — benchmark harness, scenarios A–G (baseline, preferred rooms,
    time windows, day-off, combined, constrained, larger model). Each
    benchmark records scenario, counts, status, wall time, recomputed
    objective, preference-satisfaction rates, and hard-violation checks.
    A timeout is reported as TIME_LIMIT/UNKNOWN-never-INFEASIBLE by the
    harness classifier (see classify_status).
  * Part 4 — edge cases (zero/disabled/malformed/stale/unavailable prefs,
    locked assignments, specialization assignments, empty set, infeasible).
  * Part 5 — hard-constraint regression spot checks on optimized outputs
    (HN1, H12, room/faculty/group conflicts, availability, geometry,
    locked immovability, specialization sync).

Run from the repository root:

    venv\\Scripts\\python.exe -m unittest backend.tests.test_scheduler_objective_6s -v
"""
import time
import unittest
from types import SimpleNamespace

from backend import schedule_rules as rules
from backend.faculty_preferences import (
    MAX_FACULTY_PENALTY_PER_SESSION,
    normalize_faculty_preferences,
)
from backend.scheduler import (
    compatible_rooms,
    expand_sessions,
    faculty_time_penalty,
    faculty_time_scale,
    normalize_preferred_rooms,
    objective_time_scale,
    placement_objective_cost,
    preferred_room_penalty,
    preferred_time_scale,
    run_scheduler,
    valid_starts,
)


# ------------------------------------------------------- fakes
def _room(rid, name=None, room_type="theory", capacity=100, equipment=None):
    return SimpleNamespace(id=rid, name=name or f"R{rid}",
                           room_type=room_type, capacity=capacity,
                           equipment_count=equipment)


def _theory_rooms():
    return [_room(1, "R101"), _room(2, "R102")]


class _FakeAssignment:
    """Duck-typed TeachingAssignment (normal section/lab teaching)."""

    def __init__(self, aid, faculty_id, session_type, section_id=None,
                 lab_group_id=None, ppw=1, block=1, size=30):
        self.id = aid
        self.faculty_id = faculty_id
        self.subject_id = 900 + aid
        self.session_type = session_type
        self.section_id = section_id
        self.lab_group_id = lab_group_id
        self.periods_per_week = ppw
        self.block_length = block
        self._size = size
        self.specialization_id = None
        self.lab_group = (SimpleNamespace(section_id=section_id)
                          if session_type == "practical" else None)

    def group_key(self):
        if self.session_type == "practical":
            return f"labgroup:{self.lab_group_id}"
        return f"section:{self.section_id}"

    def group_label(self):
        return self.group_key()

    def group_size(self):
        return self._size


class _FakeSpecAssignment:
    """Duck-typed specialization TeachingAssignment."""

    def __init__(self, aid, faculty_id, spec_id, ppw=1, block=1):
        self.id = aid
        self.faculty_id = faculty_id
        self.subject_id = 900 + aid
        self.session_type = "theory"
        self.specialization_id = spec_id
        self.periods_per_week = ppw
        self.block_length = block

    def group_label(self):
        return f"SPEC:{self.specialization_id}"


def _pref(fid=1, kind="TIME_WINDOW", days="Mon,Tue", start=0, end=3,
          enabled=True, weight=5, is_hard=False):
    return SimpleNamespace(faculty_id=fid, kind=kind, days=days,
                           start_period=start, end_period=end,
                           weight=weight, is_hard=is_hard, enabled=enabled)


def _spec_info():
    return {5: {"enrollment_id": 1, "section_ids": [1],
                "total_students": 10, "session_type": "theory",
                "name": "Cyber"},
            6: {"enrollment_id": 1, "section_ids": [2],
                "total_students": 10, "session_type": "theory",
                "name": "AI"}}


def _ok(status):
    return status in ("OPTIMAL", "FEASIBLE")


def classify_status(status):
    """Harness-side classification: never call a timeout INFEASIBLE.

    run_scheduler currently folds solver timeouts into "INFEASIBLE" (6S audit
    §18: documented wrapper limitation, deferred to 6T). The harness keeps
    the raw string but classifies it honestly: only a solver-proven "OPTIMAL"
    is optimal, "FEASIBLE" is feasible-but-unbounded, anything else is a
    failure whose cause (infeasible vs time-limit) is UNKNOWN from this
    return contract alone.
    """
    if status == "OPTIMAL":
        return "OPTIMAL"
    if status == "FEASIBLE":
        return "FEASIBLE (not proven optimal)"
    if status == "NO_SESSIONS":
        return "NO_SESSIONS (empty demand)"
    return "FAILURE (infeasible OR time-limit — not distinguished by wrapper)"


# ------------------------------------------------------- harness
def _session_count(assignments, specialization_data=None):
    """Mirror the solver's N = len(sessions) without solving.

    Normal assignments contribute ceil(ppw/block); spec assignments
    contribute ceil(ppw/block) unless their spec is empty (no sections or
    total <= 0), in which case 0 — matching _expand_spec_sessions.
    """
    spec_info = dict(specialization_data or {})
    n = 0
    for a in assignments:
        sid = getattr(a, "specialization_id", None)
        if sid is not None:
            info = spec_info.get(sid, {})
            if not (info.get("section_ids") or []) or \
                    (info.get("total_students", 0) or 0) <= 0:
                continue
        ppw = getattr(a, "periods_per_week", 0) or 0
        blk = getattr(a, "block_length", 1) or 1
        rem = ppw
        while rem > 0:
            n += 1
            rem -= blk if rem >= blk else rem
    return n


def _time_scale_for(n, faculty_map):
    return faculty_time_scale(n) if faculty_map else preferred_time_scale(n)


def recompute_objective(placements, assignments, rooms, days, num_periods,
                        preferred_raw=None, pref_rows=None,
                        specialization_data=None):
    """Recompute the 6S objective from placements (test-only, no solver).

    Returns (total, scale, room_pen_total, fac_pen_total, detail_list).
    Mirrors scheduler.py 1035-1045 exactly: start*K + room + faculty.
    """
    pmap = normalize_preferred_rooms(preferred_raw, rooms)
    fmap = normalize_faculty_preferences(pref_rows, days, num_periods)
    n = _session_count(assignments, specialization_data)
    k = _time_scale_for(n, fmap)
    by_id = {a.id: a for a in assignments}
    total = room_tot = fac_tot = 0
    detail = []
    for p in placements:
        a = by_id[p["assignment_id"]]
        sid = getattr(a, "specialization_id", None)
        if sid is not None:
            sess = {"session_type": getattr(a, "session_type", "theory"),
                    "group_key": f"specialization:{sid}"}
        elif getattr(a, "session_type", "") == "practical":
            sess = {"session_type": "practical",
                    "group_key": f"labgroup:{getattr(a, 'lab_group_id', '?')}"}
        else:
            sess = {"session_type": "theory",
                    "group_key": f"section:{getattr(a, 'section_id', '?')}"}
        rp = preferred_room_penalty(sess, p["room_id"], pmap)
        fp = faculty_time_penalty(getattr(a, "faculty_id", None), p["day"],
                                  p["start_period"], p["length"], fmap)
        total += p["start_period"] * k + rp + fp
        room_tot += rp
        fac_tot += fp
        detail.append({"assignment_id": p["assignment_id"], "start": p["start_period"],
                       "room_pen": rp, "fac_pen": fp})
    return total, k, room_tot, fac_tot, detail


def estimate_candidates(assignments, rooms, faculty_unavailable, days,
                        num_periods, break_after):
    """Upper-bound candidate count (ignores locked/HN1/H12 pruning).

    Labels itself an estimate: the solver prunes further (availability is
    applied here; locked/HN1/H12 pruning is not). Good enough to observe
    model growth across scenarios A–G.
    """
    total = 0
    for a in assignments:
        if getattr(a, "specialization_id", None) is not None:
            continue  # spec candidate shape differs; counted separately below
        sess = {"session_type": a.session_type,
                "group_key": a.group_key(),
                "group_label": a.group_label(),
                "group_size": a.group_size(),
                "length": a.block_length,
                "faculty_id": a.faculty_id}
        rooms_ok = compatible_rooms(
            {"session_type": sess["session_type"],
             "group_size": sess["group_size"],
             "group_label": sess["group_label"]}, rooms)
        if not rooms_ok:
            continue
        starts = valid_starts(a.block_length, num_periods, break_after)
        unavail = (faculty_unavailable or {}).get(a.faculty_id, set())
        day_starts = 0
        for day in days:
            for st in starts:
                if rules.is_faculty_available(unavail, day, st, a.block_length):
                    day_starts += 1
        total += day_starts * len(rooms_ok)
    return total


def check_hard_violations(placements, assignments, rooms, faculty_unavailable,
                          days, num_periods, break_after, max_consecutive):
    """Lightweight hard-violation scan over placements (test-only).

    Returns a list of violation strings (empty == clean) covering room /
    faculty / group double-booking, availability, geometry/break/day, H12
    longest-run, and HN1 theory streaks.
    """
    violations = []
    by_id = {a.id: a for a in assignments}
    room_occ, fac_occ, group_occ = {}, {}, {}
    theory_by_sec_day = {}
    fac_by_day = {}
    for p in placements:
        a = by_id.get(p["assignment_id"])
        if a is None:
            violations.append(f"placement for unknown assignment {p}")
            continue
        day, st, ln = p["day"], p["start_period"], p["length"]
        if day not in days:
            violations.append(f"unknown day {day}")
        if st < 0 or ln < 1 or st + ln > num_periods:
            violations.append(f"geometry {day} {st}+{ln}")
        if rules.spans_break(st, ln, break_after):
            violations.append(f"break span {day} {st}+{ln}")
        unavail = (faculty_unavailable or {}).get(a.faculty_id, set())
        if not rules.is_faculty_available(unavail, day, st, ln):
            violations.append(f"faculty {a.faculty_id} unavailable {day}:{st}")
        sid = getattr(a, "specialization_id", None)
        gkey = f"specialization:{sid}" if sid is not None else a.group_key()
        for q in range(st, st + ln):
            for occ, key, label in (
                    (room_occ, (p["room_id"], day, q), "room"),
                    (fac_occ, (a.faculty_id, day, q), "faculty"),
                    (group_occ, (gkey, day, q), "group")):
                occ[key] = occ.get(key, 0) + 1
                if occ[key] > 1:
                    violations.append(f"{label} double-booked {key}")
            fac_by_day.setdefault((a.faculty_id, day), set()).add(q)
        if getattr(a, "session_type", "") == "theory" and sid is None \
                and gkey.startswith("section:"):
            theory_by_sec_day.setdefault((gkey, day), set()).update(
                range(st, st + ln))
    if max_consecutive and max_consecutive > 0:
        for (fid, day), occ in fac_by_day.items():
            res = rules.check_faculty_consecutive(occ, max_consecutive,
                                                  faculty_id=fid, day=day)
            if not res.ok:
                violations.append(res.message)
    for (gkey, day), occ in theory_by_sec_day.items():
        bad = rules.check_max_two_theory(occ, num_periods, break_after,
                                         gkey, day)
        violations.extend(r.message for r in bad)
    return violations


def run_benchmark(label, assignments, rooms, faculty_unavailable, days,
                  num_periods, break_after, max_consecutive,
                  time_limit_seconds=10, preferred_raw=None, pref_rows=None,
                  locked_placements=None, specialization_data=None):
    """Solve once and return a metrics dict (Scenario A–G harness)."""
    t0 = time.time()
    status, placements, message = run_scheduler(
        assignments, rooms, faculty_unavailable, days, num_periods,
        break_after, max_consecutive,
        time_limit_seconds=time_limit_seconds,
        locked_placements=locked_placements,
        specialization_data=specialization_data,
        preferred_theory_rooms=preferred_raw,
        faculty_preferences=pref_rows)
    wall = time.time() - t0
    placements = placements or []
    n_sessions = _session_count(assignments, specialization_data)
    total, k, room_pen, fac_pen, _ = recompute_objective(
        placements, assignments, rooms, days, num_periods, preferred_raw,
        pref_rows, specialization_data)
    # Satisfaction: applicable theory sessions in preferred room; faculty
    # placements with zero penalty.
    pmap = normalize_preferred_rooms(preferred_raw, rooms)
    fmap = normalize_faculty_preferences(pref_rows, days, num_periods)
    by_id = {a.id: a for a in assignments}
    room_app = room_hit = fac_sat = 0
    for p in placements:
        a = by_id[p["assignment_id"]]
        sid = getattr(a, "specialization_id", None)
        if sid is not None:
            sess = {"session_type": "theory",
                    "group_key": f"specialization:{sid}"}
        elif a.session_type == "practical":
            sess = {"session_type": "practical",
                    "group_key": f"labgroup:{a.lab_group_id}"}
        else:
            sess = {"session_type": "theory",
                    "group_key": f"section:{a.section_id}"}
        rp = preferred_room_penalty(sess, p["room_id"], pmap)
        fp = faculty_time_penalty(a.faculty_id, p["day"], p["start_period"],
                                  p["length"], fmap)
        if sess["session_type"] == "theory" and \
                sess["group_key"].startswith("section:"):
            try:
                sec = int(sess["group_key"].split(":", 1)[1])
            except (ValueError, IndexError):
                sec = None
            if sec is not None and pmap.get(sec) is not None:
                room_app += 1
                room_hit += (rp == 0)
        if fmap.get(a.faculty_id):
            fac_sat += (fp == 0)
    fac_app = sum(1 for p in placements
                  if fmap.get(by_id[p["assignment_id"]].faculty_id))
    violations = check_hard_violations(
        placements, assignments, rooms, faculty_unavailable, days,
        num_periods, break_after, max_consecutive)
    return {
        "scenario": label,
        "assignments": len(assignments),
        "sessions": n_sessions,
        "candidate_estimate": estimate_candidates(
            assignments, rooms, faculty_unavailable, days, num_periods,
            break_after),
        "status": status,
        "classified": classify_status(status),
        "wall_time": round(wall, 2),
        "scale": k,
        "objective": total,
        "room_pen": room_pen,
        "faculty_pen": fac_pen,
        "scheduled": len(placements),
        "room_hit_rate": f"{room_hit}/{room_app}",
        "faculty_sat_rate": f"{fac_sat}/{fac_app}",
        "hard_violations": violations,
        "message": (message or "")[:120],
    }


# ------------------------------------------------------- Part 1: construction
class TestObjectiveConstruction(unittest.TestCase):
    def test_no_preference_scale(self):
        for n, want in ((0, 1), (1, 2), (5, 6), (30, 31)):
            self.assertEqual(preferred_time_scale(n), want)

    def test_faculty_scale(self):
        for n, want in ((0, 1), (1, 3), (5, 11), (30, 61)):
            self.assertEqual(faculty_time_scale(n), want)

    def test_max_lower_tier_bounds(self):
        # Room-only world: max secondary N < K=N+1. Combined world:
        # max secondary 2N < K=2N+1. Holds for every N >= 0.
        for n in (0, 1, 2, 7, 30, 200):
            self.assertLess(n, preferred_time_scale(n))
            self.assertLess(2 * n, faculty_time_scale(n))

    def test_strict_hierarchy_arithmetic(self):
        # One start-unit improvement beats the best possible secondary
        # swing, in both worlds, for a concrete N=30 like the baseline.
        n = 30
        self.assertGreater(preferred_time_scale(n), n)       # 31 > 30
        self.assertGreater(faculty_time_scale(n), 2 * n)     # 61 > 60
        # Concrete: start 1 + zero secondary (31) vs start 0 + worst room (30).
        self.assertLess(n, 1 * preferred_time_scale(n))
        # Combined: start 1 + zero secondary (61) vs start 0 + worst both (60).
        self.assertLess(2 * n, 1 * faculty_time_scale(n))

    def test_penalties_binary(self):
        sess = {"session_type": "theory", "group_key": "section:1"}
        for room in (1, 2, 99):
            self.assertIn(preferred_room_penalty(sess, room, {1: 1}), (0, 1))
        prefs = normalize_faculty_preferences(
            [_pref(1, "TIME_WINDOW", "Mon", 0, 1),
             _pref(1, "DAY_OFF_PREFERENCE", "Mon", None, None)],
            ["Mon", "Tue"], 7)
        for day, start in (("Mon", 0), ("Mon", 5), ("Tue", 0)):
            self.assertIn(faculty_time_penalty(1, day, start, 1, prefs), (0, 1))
        self.assertLessEqual(MAX_FACULTY_PENALTY_PER_SESSION, 1)

    def test_scale_keys_on_surviving_prefs_only(self):
        # Junk-only rows normalize to {} -> room-only scale stays valid.
        junk = [None, 42, "x",
                _pref(1, "SUBJECT_AFFINITY", "Mon", 0, 3)]
        fmap = normalize_faculty_preferences(junk, ["Mon"], 7)
        self.assertEqual(fmap, {})
        self.assertEqual(_time_scale_for(4, fmap), preferred_time_scale(4))

    def test_named_helpers_match_inline_formula(self):
        # Phase 6S explicitness refactor: the named helpers must equal the
        # audited inline arithmetic for every placement shape.
        pmap = normalize_preferred_rooms({1: 1}, _theory_rooms())
        fmap = normalize_faculty_preferences(
            [_pref(1, "TIME_WINDOW", "Mon", 0, 2)], ["Mon"], 4)
        self.assertEqual(objective_time_scale(5, fmap),
                         faculty_time_scale(5))
        self.assertEqual(objective_time_scale(5, {}),
                         preferred_time_scale(5))
        for sess in ({"session_type": "theory", "group_key": "section:1",
                      "faculty_id": 1, "length": 1},
                     {"session_type": "practical", "group_key": "labgroup:9",
                      "faculty_id": 2, "length": 2},
                     {"session_type": "theory",
                      "group_key": "specialization:5", "faculty_id": 3,
                      "length": 1}):
            for k in (preferred_time_scale(3), faculty_time_scale(3)):
                want = (0 * k
                        + preferred_room_penalty(sess, 1, pmap)
                        + faculty_time_penalty(sess.get("faculty_id"), "Mon",
                                               0, sess["length"], fmap))
                self.assertEqual(
                    placement_objective_cost(sess, "Mon", 0, 1, k, pmap,
                                             fmap), want)

    def test_recompute_matches_formula(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 1})
        self.assertTrue(_ok(status))
        total, k, room_pen, fac_pen, _ = recompute_objective(
            placements, a, _theory_rooms(), ["Mon"], 2, {1: 1}, None)
        self.assertEqual(k, preferred_time_scale(1))
        p = placements[0]
        self.assertEqual(total, p["start_period"] * k + room_pen + fac_pen)


# ------------------------------------------------------- Part 2: behavior
class TestStartPriority(unittest.TestCase):
    def test_earlier_start_beats_preferred_room(self):
        locked_asg = _FakeAssignment(9, 9, "theory", section_id=2)
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        locked = [{"locked_block_id": 7, "assignment_id": 9, "day": "Mon",
                   "start_period": 0, "length": 1, "room_id": 1,
                   "faculty_id": 9, "session_type": "theory",
                   "group_key": "section:2", "parent_section_key": None}]
        status, placements, _ = run_scheduler(
            [locked_asg, normal], _theory_rooms(), {}, ["Mon"], 3, None,
            None, time_limit_seconds=10, locked_placements=locked,
            preferred_theory_rooms={1: 1})
        self.assertTrue(_ok(status))
        self.assertEqual((placements[0]["day"],
                          placements[0]["start_period"],
                          placements[0]["room_id"]), ("Mon", 0, 2))

    def test_earlier_start_beats_faculty_window(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Mon", 2, 4)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 4, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["start_period"], 0)


class TestPreferredRoomBehavior(unittest.TestCase):
    def test_preferred_room_wins_on_start_tie(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = list(reversed(_theory_rooms()))
        status, placements, _ = run_scheduler(
            a, rooms, {}, ["Mon"], 2, None, None, time_limit_seconds=10,
            preferred_theory_rooms={1: 1})
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["room_id"], 1)
        self.assertEqual(placements[0]["start_period"], 0)

    def test_labs_and_specs_excluded(self):
        sess_lab = {"session_type": "practical", "group_key": "labgroup:10"}
        sess_spec = {"session_type": "theory",
                     "group_key": "specialization:5"}
        self.assertEqual(preferred_room_penalty(sess_lab, 3, {1: 3}), 0)
        self.assertEqual(preferred_room_penalty(sess_spec, 3, {1: 3}), 0)


class TestFacultyPreferenceBehavior(unittest.TestCase):
    def test_time_window_wins_on_day_tie(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Tue", 0, 2)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["day"], "Tue")

    def test_day_off_wins_on_day_tie(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "DAY_OFF_PREFERENCE", "Mon", None, None)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["day"], "Tue")

    def test_combination_trades_one_for_one(self):
        # All starts tie at 0: room pref (R101) + faculty window (Tue) both
        # apply; neither dominates the other.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = list(reversed(_theory_rooms()))
        prefs = [_pref(1, "TIME_WINDOW", "Tue", 0, 2)]
        status, placements, _ = run_scheduler(
            a, rooms, {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 1},
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual((placements[0]["day"], placements[0]["room_id"]),
                         ("Tue", 1))

    def test_soft_pref_never_blocks_feasibility(self):
        # Window says Mon-only but faculty is unavailable Mon: schedule must
        # still succeed on Tue, violating the soft preference.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Mon", 0, 2)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {1: {"Mon:0", "Mon:1"}}, ["Mon", "Tue"],
            2, None, None, time_limit_seconds=10,
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual(placements[0]["day"], "Tue")


# ------------------------------------------------------- Part 3: benchmarks A-G
def _standard_assignments(count=15, ppw=2, faculties=5, sections=4):
    out = []
    for i in range(count):
        out.append(_FakeAssignment(i + 1, (i % faculties) + 1, "theory",
                                   section_id=(i % sections) + 1,
                                   ppw=ppw, block=1, size=25))
    return out


def _standard_rooms(count=3):
    return [_room(i + 1, f"R10{i + 1}", "theory", 60) for i in range(count)]


class TestBenchmarks6S(unittest.TestCase):
    """Scenarios A–G. Each asserts feasibility + zero hard violations and
    prints a one-line metrics summary (visible with -v / pytest -s)."""

    DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    N_PERIODS = 7
    BREAK = 4
    MAXC = 3

    def _report(self, m):
        print(f"\n[6S {m['scenario']}] status={m['status']} "
              f"({m['classified']}) asg={m['assignments']} "
              f"sess={m['sessions']} cand~{m['candidate_estimate']} "
              f"wall={m['wall_time']}s scale={m['scale']} obj={m['objective']} "
              f"(room_pen={m['room_pen']} fac_pen={m['faculty_pen']}) "
              f"scheduled={m['scheduled']} room_hit={m['room_hit_rate']} "
              f"fac_sat={m['faculty_sat_rate']} "
              f"violations={m['hard_violations'] or 'none'}")

    def test_a_baseline(self):
        m = run_benchmark(
            "A-baseline", _standard_assignments(), _standard_rooms(), {},
            self.DAYS, self.N_PERIODS, self.BREAK, self.MAXC,
            time_limit_seconds=20)
        self._report(m)
        self.assertTrue(_ok(m["status"]), m)
        self.assertEqual(m["scheduled"], m["sessions"])
        self.assertEqual(m["hard_violations"], [])
        self.assertEqual(m["scale"], preferred_time_scale(m["sessions"]))

    def test_b_preferred_rooms(self):
        asg = _standard_assignments()
        m = run_benchmark(
            "B-preferred-rooms", asg, _standard_rooms(), {},
            self.DAYS, self.N_PERIODS, self.BREAK, self.MAXC,
            time_limit_seconds=20,
            preferred_raw={1: 1, 2: 2, 3: 1, 4: 2})
        self._report(m)
        self.assertTrue(_ok(m["status"]), m)
        self.assertEqual(m["hard_violations"], [])
        # Preferred room is feasible for every section here; the optimum
        # should honor it wherever starts tie (hit rate well above zero).
        hit, app = (int(x) for x in m["room_hit_rate"].split("/"))
        self.assertGreater(app, 0)
        self.assertGreater(hit, 0)

    def test_c_faculty_time_windows(self):
        asg = _standard_assignments()
        prefs = [_pref(fid, "TIME_WINDOW", "Mon,Tue,Wed,Thu", 0, 4)
                 for fid in range(1, 6)]
        m = run_benchmark(
            "C-time-windows", asg, _standard_rooms(), {},
            self.DAYS, self.N_PERIODS, self.BREAK, self.MAXC,
            time_limit_seconds=20, pref_rows=prefs)
        self._report(m)
        self.assertTrue(_ok(m["status"]), m)
        self.assertEqual(m["hard_violations"], [])
        self.assertEqual(m["scale"], faculty_time_scale(m["sessions"]))

    def test_d_faculty_day_off(self):
        asg = _standard_assignments()
        prefs = [_pref(fid, "DAY_OFF_PREFERENCE", "Fri", None, None)
                 for fid in range(1, 6)]
        m = run_benchmark(
            "D-day-off", asg, _standard_rooms(), {},
            self.DAYS, self.N_PERIODS, self.BREAK, self.MAXC,
            time_limit_seconds=20, pref_rows=prefs)
        self._report(m)
        self.assertTrue(_ok(m["status"]), m)
        self.assertEqual(m["hard_violations"], [])

    def test_e_combined(self):
        asg = _standard_assignments()
        prefs = [_pref(fid, "TIME_WINDOW", "Mon,Tue,Wed,Thu", 0, 4)
                 for fid in range(1, 6)]
        m = run_benchmark(
            "E-combined", asg, _standard_rooms(), {},
            self.DAYS, self.N_PERIODS, self.BREAK, self.MAXC,
            time_limit_seconds=20,
            preferred_raw={1: 1, 2: 2, 3: 1, 4: 2}, pref_rows=prefs)
        self._report(m)
        self.assertTrue(_ok(m["status"]), m)
        self.assertEqual(m["hard_violations"], [])
        self.assertEqual(m["scale"], faculty_time_scale(m["sessions"]))

    def test_f_constrained(self):
        # Tighter availability + a locked block + one specialization cohort.
        asg = _standard_assignments(count=8, ppw=2)
        cyber = _FakeSpecAssignment(101, 6, 5)
        ai = _FakeSpecAssignment(102, 7, 6)
        asg = asg + [cyber, ai]
        rooms = [_room(1, "R101", "theory", 60), _room(2, "R102", "theory", 60)]
        unavail = {1: {"Mon:0", "Mon:1", "Tue:0"},
                   2: {"Fri:5", "Fri:6"}}
        locked_asg = _FakeAssignment(200, 9, "theory", section_id=4)
        locked = [{"locked_block_id": 42, "assignment_id": 200,
                   "day": "Mon", "start_period": 0, "length": 1,
                   "room_id": 1, "faculty_id": 9,
                   "session_type": "theory", "group_key": "section:4",
                   "parent_section_key": None}]
        m = run_benchmark(
            "F-constrained", asg + [locked_asg], rooms, unavail,
            ["Mon", "Tue", "Wed"], 6, 3, 3,
            time_limit_seconds=20, locked_placements=locked,
            specialization_data=_spec_info())
        self._report(m)
        self.assertTrue(_ok(m["status"]), m)
        self.assertEqual(m["hard_violations"], [])
        # Locked assignment is never re-emitted; spec cohort stays synced.
        self.assertNotIn(200, [p["assignment_id"] for p in
                               run_scheduler(
                                   asg + [locked_asg], rooms, unavail,
                                   ["Mon", "Tue", "Wed"], 6, 3, 3,
                                   time_limit_seconds=20,
                                   locked_placements=locked,
                                   specialization_data=_spec_info())[1]])

    def test_g_larger_model(self):
        asg = _standard_assignments(count=30, ppw=2, faculties=8, sections=6)
        rooms = _standard_rooms(count=4)
        m = run_benchmark(
            "G-large", asg, rooms, {}, self.DAYS, self.N_PERIODS,
            self.BREAK, self.MAXC, time_limit_seconds=25)
        self._report(m)
        # Larger model must at least solve (OPTIMAL or FEASIBLE); a timeout
        # is classified honestly and never asserted as infeasible here.
        self.assertIn(m["status"], ("OPTIMAL", "FEASIBLE"), m)
        if _ok(m["status"]):
            self.assertEqual(m["hard_violations"], [])


# ------------------------------------------------------- Part 4: edges
class TestObjectiveEdges(unittest.TestCase):
    def test_empty_assignment_set(self):
        status, placements, msg = run_scheduler(
            [], _theory_rooms(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=10)
        self.assertEqual(status, "NO_SESSIONS")
        self.assertEqual(placements, [])

    def test_all_preferences_disabled(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        prefs = [_pref(1, "TIME_WINDOW", "Tue", 0, 2, enabled=False)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon", "Tue"], 2, None, None,
            time_limit_seconds=10, faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        # Disabled == absent: identical optimum shape (earliest start, any
        # room); only assert feasibility + start, not the tied room.
        self.assertEqual(placements[0]["start_period"], 0)

    def test_malformed_preferences_neutral(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        junk = [None, 42, "x", object(),
                SimpleNamespace(faculty_id=1, kind="SUBJECT_AFFINITY"),
                {"faculty_id": 1, "kind": "TIME_WINDOW", "days": "Mon",
                 "start_period": "a", "end_period": []}]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 1, None, None,
            time_limit_seconds=10, faculty_preferences=junk)
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)

    def test_stale_preferred_room_neutral(self):
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 999})
        self.assertTrue(_ok(status))
        self.assertEqual(len(placements), 1)
        self.assertIn(placements[0]["room_id"], (1, 2))

    def test_unavailable_preferred_room_stays_soft(self):
        # Preferred room exists but is hard-incompatible (lab for theory):
        # schedule must still succeed in a theory room.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = _theory_rooms() + [_room(3, "L1", "lab", 40, 40)]
        status, placements, _ = run_scheduler(
            a, rooms, {}, ["Mon"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 3})
        self.assertTrue(_ok(status))
        self.assertIn(placements[0]["room_id"], (1, 2))

    def test_infeasible_stays_infeasible(self):
        # No compatible room at all: hard failure, preference-independent.
        a = [_FakeAssignment(1, 1, "theory", section_id=1, size=500)]
        status, placements, msg = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=10, preferred_theory_rooms={1: 1},
            faculty_preferences=[_pref(1, "TIME_WINDOW", "Mon", 0, 2)])
        self.assertEqual(status, "INFEASIBLE")
        self.assertEqual(placements, [])

    def test_weight_does_not_change_optimum(self):
        # weight 1 vs 10 on the same single preference: identical placement
        # (weight is stored but unused in 6S by product decision).
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        rooms = list(reversed(_theory_rooms()))
        out = []
        for w in (1, 10):
            status, placements, _ = run_scheduler(
                a, rooms, {}, ["Mon", "Tue"], 2, None, None,
                time_limit_seconds=10, preferred_theory_rooms={1: 1},
                faculty_preferences=[_pref(1, "TIME_WINDOW", "Tue", 0, 2,
                                           weight=w)])
            self.assertTrue(_ok(status))
            out.append((placements[0]["day"], placements[0]["room_id"]))
        self.assertEqual(out[0], out[1])
        self.assertEqual(out[0], ("Tue", 1))

    def test_tiny_time_limit_never_misclassified(self):
        # Even under an implausibly small budget the wrapper contract holds:
        # the harness classifies honestly and never calls it INFEASIBLE-as-proof.
        a = [_FakeAssignment(1, 1, "theory", section_id=1)]
        status, placements, _ = run_scheduler(
            a, _theory_rooms(), {}, ["Mon"], 2, None, None,
            time_limit_seconds=1)
        self.assertIn(status, ("OPTIMAL", "FEASIBLE", "INFEASIBLE"))
        self.assertIn(classify_status(status),
                      ("OPTIMAL", "FEASIBLE (not proven optimal)",
                       "FAILURE (infeasible OR time-limit — not distinguished "
                       "by wrapper)"))


# ------------------------------------------------------- Part 5: hard regression
class TestHardRegression6S(unittest.TestCase):
    def test_optimized_output_respects_hard_rules(self):
        asg = _standard_assignments(count=10, ppw=2)
        prefs = [_pref(fid, "TIME_WINDOW", "Mon,Tue,Wed", 0, 4)
                 for fid in range(1, 6)]
        status, placements, _ = run_scheduler(
            asg, _standard_rooms(), {}, ["Mon", "Tue", "Wed", "Thu"], 7,
            4, 3, time_limit_seconds=20,
            preferred_theory_rooms={1: 1, 2: 2, 3: 1, 4: 2},
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        violations = check_hard_violations(
            placements, asg, _standard_rooms(), {}, ["Mon", "Tue", "Wed",
                                                     "Thu"], 7, 4, 3)
        self.assertEqual(violations, [])

    def test_locked_blocks_untouched_by_objective(self):
        locked_asg = _FakeAssignment(9, 9, "theory", section_id=2)
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        locked = [{"locked_block_id": 7, "assignment_id": 9, "day": "Mon",
                   "start_period": 0, "length": 1, "room_id": 1,
                   "faculty_id": 9, "session_type": "theory",
                   "group_key": "section:2", "parent_section_key": None}]
        prefs = [_pref(9, "TIME_WINDOW", "Tue", 0, 3)]
        status, placements, _ = run_scheduler(
            [locked_asg, normal], _theory_rooms(), {}, ["Mon", "Tue"], 3,
            None, None, time_limit_seconds=10, locked_placements=locked,
            faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        self.assertEqual([p["assignment_id"] for p in placements], [1])

    def test_specialization_sync_under_preferences(self):
        normal = _FakeAssignment(1, 1, "theory", section_id=1)
        cyber = _FakeSpecAssignment(10, 3, 5)
        ai = _FakeSpecAssignment(11, 4, 6)
        prefs = [_pref(3, "TIME_WINDOW", "Tue", 0, 3),
                 _pref(4, "DAY_OFF_PREFERENCE", "Tue", None, None)]
        status, placements, _ = run_scheduler(
            [normal, cyber, ai], _theory_rooms(), {}, ["Mon", "Tue"], 3,
            None, None, time_limit_seconds=15,
            specialization_data=_spec_info(), faculty_preferences=prefs)
        self.assertTrue(_ok(status))
        by_assign = {}
        for p in placements:
            by_assign.setdefault(p["assignment_id"], []).append(
                (p["day"], p["start_period"], p["length"]))
        self.assertEqual(sorted(by_assign[10]), sorted(by_assign[11]))


if __name__ == "__main__":
    unittest.main()
