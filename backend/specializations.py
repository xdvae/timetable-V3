"""
Phase 6F — Specialization domain service.

Conservative originating-section occupancy (no student-level scheduling):

* A specialization belongs to exactly one enrollment/cohort.
* Its sections must belong to the same enrollment (SPECIALIZATION_ENROLLMENT).
* Membership headcounts are validated per-section and in aggregate
  (SPECIALIZATION_CAPACITY / SPECIALIZATION_MEMBERSHIP).
* All active specializations of one enrollment share identical synchronized
  slots (same day/start/length; rooms and faculty may differ).
* Each specialization's room must hold its total headcount.
* A specialization slot blocks every participating section for normal
  teaching (SPECIALIZATION_OVERLAP).
* Specialization theory participates once per section in HN1
  (MAX_TWO_THEORY via schedule_rules); practicals never count.

This module never imports Flask/HTTP code. ORM operations take the
Flask-SQLAlchemy `db` handle (like locked_blocks.py) so routes and tests
share one implementation. Pure helpers operate on plain data for the
scheduler, validator, and audit.
"""
from backend import schedule_rules as rules

VALID_SESSION_TYPES = ("theory", "practical")


class SpecializationError(Exception):
    """Raised when a specialization mutation fails validation.

    Carries ``failures``: a list of schedule_rules.RuleResult with stable
    UPPER_SNAKE codes and structured ``details``.
    """

    def __init__(self, message, failures=None):
        super().__init__(message)
        self.message = message
        self.failures = list(failures or [])

    def to_payload(self):
        primary = self.failures[0] if self.failures else None
        return {
            "error": self.message,
            "code": primary.code if primary else "SPECIALIZATION_INVALID",
            "details": primary.details if primary else {},
            "failures": [
                {"code": f.code, "message": f.message, "details": f.details}
                for f in self.failures
            ],
        }


def _fail(code, message, details=None):
    return rules.RuleResult(ok=False, code=code, message=message,
                            details=details or {})


# ------------------------------------------------------- pure helpers
def specialization_total(memberships):
    """Sum of student_count over membership dicts/rows for one spec."""
    total = 0
    for m in memberships or []:
        if isinstance(m, dict):
            total += m.get("student_count", 0) or 0
        else:
            total += getattr(m, "student_count", 0) or 0
    return total


def section_allocated_total(section_id, memberships, exclude_specialization_id=None):
    """Sum allocated to one section across memberships (optionally excluding
    one specialization, for updates)."""
    total = 0
    for m in memberships or []:
        if isinstance(m, dict):
            sid = m.get("section_id")
            spec = m.get("specialization_id")
        else:
            sid = getattr(m, "section_id", None)
            spec = getattr(m, "specialization_id", None)
        if sid != section_id:
            continue
        if exclude_specialization_id is not None and spec == exclude_specialization_id:
            continue
        total += (m.get("student_count", 0) if isinstance(m, dict)
                  else (getattr(m, "student_count", 0) or 0))
    return total


def slots_key_list(slots):
    """Normalized sorted [(day, start_period, length)] for sync comparison."""
    out = []
    for s in slots or []:
        if isinstance(s, dict):
            out.append((s.get("day"), s.get("start_period"), s.get("length")))
        else:
            out.append((getattr(s, "day", None),
                        getattr(s, "start_period", None),
                        getattr(s, "length", None)))
    return sorted(out, key=lambda t: (str(t[0]), t[1], t[2]))


def validate_specialization_fields(name, enrollment_id, session_type,
                                    block_length, periods_per_week,
                                    existing_names=None):
    """Validate specialization creation fields. Returns failing RuleResults."""
    failures = []
    if not (name or "").strip():
        failures.append(_fail(
            "SPECIALIZATION_MEMBERSHIP",
            "Specialization name is required.",
            {"name": name, "enrollment_id": enrollment_id}))
    if enrollment_id is None:
        failures.append(_fail(
            "SPECIALIZATION_ENROLLMENT",
            "Specialization requires an enrollment/cohort.",
            {"name": name}))
    if session_type not in VALID_SESSION_TYPES:
        failures.append(_fail(
            "SPECIALIZATION_MEMBERSHIP",
            f"Unknown session type '{session_type}': use 'theory' or 'practical'.",
            {"session_type": session_type}))
    try:
        bl = int(block_length)
        ppw = int(periods_per_week)
    except (TypeError, ValueError):
        failures.append(_fail(
            "SPECIALIZATION_MEMBERSHIP",
            "block_length and periods_per_week must be whole numbers.",
            {"block_length": block_length,
             "periods_per_week": periods_per_week}))
        return failures
    if bl < 1 or bl > ppw or ppw < 1:
        failures.append(_fail(
            "SPECIALIZATION_MEMBERSHIP",
            f"Block length ({bl}) can't exceed periods/week ({ppw}); both >= 1.",
            {"block_length": bl, "periods_per_week": ppw}))
    if existing_names and (name or "").strip() in existing_names:
        failures.append(_fail(
            "SPECIALIZATION_MEMBERSHIP",
            f"Specialization '{(name or '').strip()}' already exists "
            f"for enrollment {enrollment_id}.",
            {"name": (name or "").strip(),
             "enrollment_id": enrollment_id}))
    return failures


def validate_membership_pure(*, specialization, section,
                             student_count, all_memberships):
    """Pure membership validation. `specialization` and `section` are dicts
    with id/enrollment_id (+ student_count/name for section). Returns list."""
    failures = []
    spec_id = specialization.get("id") if isinstance(specialization, dict) \
        else getattr(specialization, "id", None)
    spec_enr = specialization.get("enrollment_id") if isinstance(specialization, dict) \
        else getattr(specialization, "enrollment_id", None)
    spec_name = (specialization.get("name") if isinstance(specialization, dict)
                 else getattr(specialization, "name", "?")) or "?"
    sec_id = section.get("id") if isinstance(section, dict) \
        else getattr(section, "id", None)
    sec_enr = section.get("enrollment_id") if isinstance(section, dict) \
        else getattr(section, "enrollment_id", None)
    sec_size = section.get("student_count") if isinstance(section, dict) \
        else getattr(section, "student_count", None)
    sec_name = (section.get("name") if isinstance(section, dict)
                else getattr(section, "name", "?")) or "?"
    # Enrollment invariant.
    res = rules.check_specialization_enrollment(
        spec_enr, sec_enr, specialization_id=spec_id, section_id=sec_id,
        specialization_name=spec_name, section_name=sec_name)
    if not res.ok:
        failures.append(res)
        return failures  # further capacity checks are noise on wrong cohort
    # Positive count.
    res = rules.check_specialization_membership_count(
        student_count, specialization_id=spec_id, section_id=sec_id)
    if not res.ok:
        failures.append(res)
        return failures
    # Duplicate section membership for this spec.
    for m in all_memberships or []:
        ms = m.get("specialization_id") if isinstance(m, dict) \
            else getattr(m, "specialization_id", None)
        ss = m.get("section_id") if isinstance(m, dict) \
            else getattr(m, "section_id", None)
        if ms == spec_id and ss == sec_id:
            failures.append(_fail(
                "SPECIALIZATION_MEMBERSHIP",
                f"Section '{sec_name}' is already a member of "
                f"specialization '{spec_name}'.",
                {"specialization_id": spec_id, "section_id": sec_id}))
            break
    # Aggregate capacity: sum across this section's specs (same enrollment
    # invariant already enforced, so all memberships for the section count).
    existing = section_allocated_total(sec_id, all_memberships,
                                       exclude_specialization_id=None)
    # When updating (duplicate case above) the caller passes memberships
    # without the row under update; for pure-create, existing is the sum.
    res = rules.check_specialization_capacity(
        student_count, sec_size, existing,
        specialization_id=spec_id, section_id=sec_id,
        section_name=sec_name, specialization_name=spec_name)
    if not res.ok:
        failures.append(res)
    return failures


def validate_sync_for_enrollment(slots_by_spec, spec_names=None,
                                 enrollment_id=None):
    """Check all active specs share one synchronized slot pattern.

    `slots_by_spec`: {spec_id: [(day, start, length), ...]}. Empty specs
    (no slots yet) are ignored when at least one spec has slots? No — for
    strict sync, every ACTIVE spec (with memberships) must have identical
    slots. The caller filters to active specs before calling. A single
    active spec always passes; zero active specs pass vacuously.
    """
    failures = []
    ids = sorted(slots_by_spec or {}, key=str)
    if len(ids) <= 1:
        return failures
    reference_id = ids[0]
    reference = sorted(slots_by_spec[reference_id] or [])
    for sid in ids[1:]:
        got = sorted(slots_by_spec[sid] or [])
        res = rules.check_specialization_sync(
            reference, got, specialization_id=sid,
            specialization_name=(spec_names or {}).get(sid, str(sid)),
            enrollment_id=enrollment_id)
        if not res.ok:
            # Enrich with reference holder for debuggability.
            det = dict(res.details)
            det["reference_specialization_id"] = reference_id
            det["reference_slots"] = [list(s) for s in reference]
            failures.append(rules.RuleResult(ok=False, code=res.code,
                                             message=res.message,
                                             details=det))
    return failures


def cohort_demand_signature(specializations, assignments_by_spec):
    """Expanded session lengths+types per spec for sync feasibility.

    Returns {spec_id: [(length, session_type), ...]} in deterministic order
    (assignments sorted by id, sessions in expand order). The scheduler
    requires all active specs in one enrollment to have identical
    signatures; otherwise sync is impossible (SPECIALIZATION_SYNC).
    """
    sig = {}
    for spec in specializations or []:
        sid = spec.get("id") if isinstance(spec, dict) \
            else getattr(spec, "id", None)
        assigns = (assignments_by_spec or {}).get(sid, [])
        seq = []
        for a in sorted(assigns, key=lambda x: getattr(x, "id", 0)
                        if not isinstance(x, dict) else x.get("id", 0)):
            ppw = a.get("periods_per_week") if isinstance(a, dict) \
                else getattr(a, "periods_per_week", 0) or 0
            blk = a.get("block_length") if isinstance(a, dict) \
                else getattr(a, "block_length", 1) or 1
            st = a.get("session_type") if isinstance(a, dict) \
                else getattr(a, "session_type", "theory")
            rem = ppw or 0
            while rem > 0:
                ln = blk if rem >= blk else rem
                seq.append((ln, st))
                rem -= ln
        sig[sid] = seq
    return sig


def validate_cohort_signatures(specs_in_enrollment, assignments_by_spec,
                               spec_names=None, enrollment_id=None):
    """All active specs in one cohort must have identical demand signatures
    (same session count, same lengths and types per index)."""
    failures = []
    sig = cohort_demand_signature(specs_in_enrollment, assignments_by_spec)
    ids = sorted(sig, key=str)
    if len(ids) <= 1:
        return failures
    ref = sig[ids[0]]
    for sid in ids[1:]:
        if sig[sid] != ref:
            failures.append(_fail(
                "SPECIALIZATION_SYNC",
                f"Specialization '{(spec_names or {}).get(sid, sid)}' demand "
                f"{sig[sid]} does not match cohort pattern {ref}: all "
                f"specializations in enrollment {enrollment_id} must share "
                f"identical session counts, block lengths, and session types.",
                {"specialization_id": sid,
                 "enrollment_id": enrollment_id,
                 "expected_signature": [list(s) for s in ref],
                 "actual_signature": [list(s) for s in sig[sid]],
                 "reference_specialization_id": ids[0]}))
    return failures


# ------------------------------------------------------- ORM operations
def _orm_config(db):
    from backend.models import Config
    cfg = Config.query.first()
    if cfg is None:
        raise SpecializationError("No scheduling configuration found.")
    return cfg


def specialization_json(spec, memberships=None, slots=None,
                        scheduled=None, total=None):
    """API-facing serialization (ScheduledClass stays the view source)."""
    mems = []
    for m in memberships or []:
        if isinstance(m, dict):
            mems.append(m)
        else:
            sec = getattr(m, "section", None)
            mems.append({"id": m.id,
                         "section_id": m.section_id,
                         "section_name": getattr(sec, "name", None),
                         "student_count": m.student_count})
    sl = []
    for s in slots or []:
        if isinstance(s, dict):
            sl.append(s)
        else:
            sl.append({"id": s.id, "day": s.day,
                       "start_period": s.start_period, "length": s.length})
    cl = []
    for c in scheduled or []:
        if isinstance(c, dict):
            cl.append(c)
        else:
            cl.append({"id": c.id, "assignment_id": c.assignment_id,
                       "day": c.day, "start_period": c.start_period,
                       "length": c.length, "room_id": c.room_id,
                       "slot_id": getattr(c, "slot_id", None)})
    return {
        "id": getattr(spec, "id", None),
        "name": getattr(spec, "name", None),
        "enrollment_id": getattr(spec, "enrollment_id", None),
        "session_type": getattr(spec, "session_type", None),
        "block_length": getattr(spec, "block_length", None),
        "periods_per_week": getattr(spec, "periods_per_week", None),
        "total_students": total if total is not None
        else specialization_total(memberships),
        "memberships": mems,
        "slots": sl,
        "scheduled_classes": cl,
    }


def create_specialization(db, *, name, enrollment_id, session_type="theory",
                          block_length=1, periods_per_week=2):
    """Validate + persist one Specialization (no slots/memberships yet)."""
    from backend.models import Enrollment, Specialization
    name = (name or "").strip()
    try:
        block_length = int(block_length)
        periods_per_week = int(periods_per_week)
    except (TypeError, ValueError):
        raise SpecializationError(
            "block_length and periods_per_week must be whole numbers.",
            [_fail("SPECIALIZATION_MEMBERSHIP",
                   "block_length and periods_per_week must be whole numbers.",
                   {"block_length": block_length,
                    "periods_per_week": periods_per_week})])
    enrollment = Enrollment.query.get(enrollment_id)
    if enrollment is None:
        raise SpecializationError(
            f"Enrollment {enrollment_id} does not exist.",
            [_fail("SPECIALIZATION_ENROLLMENT",
                   f"Enrollment {enrollment_id} does not exist.",
                   {"enrollment_id": enrollment_id})])
    existing = [s.name for s in
                Specialization.query.filter_by(enrollment_id=enrollment_id).all()]
    failures = validate_specialization_fields(
        name, enrollment_id, session_type, block_length,
        periods_per_week, existing)
    if failures:
        raise SpecializationError(
            f"Specialization invalid: {failures[0].message}", failures)
    try:
        spec = Specialization(name=name, enrollment_id=enrollment_id,
                              session_type=session_type,
                              block_length=block_length,
                              periods_per_week=periods_per_week)
        db.session.add(spec)
        db.session.commit()
        db.session.refresh(spec)
        return spec
    except Exception as exc:  # noqa: BLE001 — unique violations surface here
        db.session.rollback()
        msg = str(exc)
        if "uq_specialization_name_enrollment" in msg or "UNIQUE" in msg.upper():
            raise SpecializationError(
                f"Specialization '{name}' already exists for enrollment "
                f"{enrollment_id}.",
                [_fail("SPECIALIZATION_MEMBERSHIP",
                       f"Specialization '{name}' already exists for "
                       f"enrollment {enrollment_id}.",
                       {"name": name, "enrollment_id": enrollment_id})])
        raise SpecializationError(
            f"Could not persist specialization: {exc}",
            [_fail("PERSISTENCE_FAILED",
                   f"Could not persist specialization: {exc}", {})])


def delete_specialization(db, specialization_id):
    """Remove a specialization + its memberships/slots. Scheduled classes
    for its specialization assignments are also removed (they are
    specialization footprint, never normal teaching). Normal assignments
    are never touched."""
    from backend.models import (ScheduledClass, Specialization,
                                SpecializationMembership, SpecializationSlot,
                                TeachingAssignment)
    spec = Specialization.query.get(specialization_id)
    if spec is None:
        raise SpecializationError(
            f"Specialization {specialization_id} does not exist.",
            [_fail("SPECIALIZATION_MEMBERSHIP",
                   f"Specialization {specialization_id} does not exist.",
                   {"specialization_id": specialization_id})])
    try:
        spec_assign_ids = [a.id for a in TeachingAssignment.query.filter_by(
            specialization_id=spec.id).all()]
        if spec_assign_ids:
            ScheduledClass.query.filter(
                ScheduledClass.assignment_id.in_(spec_assign_ids)).delete(
                    synchronize_session=False)
            # Detach assignments from the spec so they become inert normal
            # rows? No — specialization assignments without a spec are
            # meaningless; delete them (they were created for the spec).
            TeachingAssignment.query.filter(
                TeachingAssignment.id.in_(spec_assign_ids)).delete(
                    synchronize_session=False)
        SpecializationMembership.query.filter_by(
            specialization_id=spec.id).delete()
        SpecializationSlot.query.filter_by(
            specialization_id=spec.id).delete()
        db.session.delete(spec)
        db.session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        raise SpecializationError(
            f"Could not delete specialization: {exc}",
            [_fail("PERSISTENCE_FAILED",
                   f"Could not delete specialization: {exc}",
                   {"specialization_id": specialization_id})])


def add_or_update_membership(db, specialization_id, section_id,
                             student_count):
    """Create or update one membership (upsert). Validates enrollment
    match, positivity, section capacity, and aggregate section allocation."""
    from backend.models import (Section, Specialization,
                                SpecializationMembership)
    try:
        student_count = int(student_count)
    except (TypeError, ValueError):
        raise SpecializationError(
            "student_count must be a whole number.",
            [_fail("SPECIALIZATION_MEMBERSHIP",
                   "student_count must be a whole number.",
                   {"specialization_id": specialization_id,
                    "section_id": section_id,
                    "student_count": student_count})])
    spec = Specialization.query.get(specialization_id)
    if spec is None:
        raise SpecializationError(
            f"Specialization {specialization_id} does not exist.",
            [_fail("SPECIALIZATION_MEMBERSHIP",
                   f"Specialization {specialization_id} does not exist.",
                   {"specialization_id": specialization_id})])
    section = Section.query.get(section_id)
    if section is None:
        raise SpecializationError(
            f"Section {section_id} does not exist.",
            [_fail("SPECIALIZATION_MEMBERSHIP",
                   f"Section {section_id} does not exist.",
                   {"section_id": section_id})])
    existing_row = SpecializationMembership.query.filter_by(
        specialization_id=spec.id, section_id=section.id).first()
    others = SpecializationMembership.query.filter_by(
        section_id=section.id).all()
    if existing_row is not None:
        others = [m for m in others if m.id != existing_row.id]
    existing_total = sum(m.student_count for m in others)
    failures = []
    res = rules.check_specialization_enrollment(
        spec.enrollment_id, section.enrollment_id,
        specialization_id=spec.id, section_id=section.id,
        specialization_name=spec.name, section_name=section.name)
    if not res.ok:
        failures.append(res)
    else:
        res = rules.check_specialization_membership_count(
            student_count, specialization_id=spec.id,
            section_id=section.id)
        if not res.ok:
            failures.append(res)
        else:
            res = rules.check_specialization_capacity(
                student_count, section.student_count, existing_total,
                specialization_id=spec.id, section_id=section.id,
                section_name=section.name,
                specialization_name=spec.name)
            if not res.ok:
                failures.append(res)
    if failures:
        raise SpecializationError(
            f"Membership invalid: {failures[0].message}", failures)
    try:
        if existing_row is not None:
            existing_row.student_count = student_count
        else:
            db.session.add(SpecializationMembership(
                specialization_id=spec.id, section_id=section.id,
                student_count=student_count))
        db.session.commit()
        row = SpecializationMembership.query.filter_by(
            specialization_id=spec.id, section_id=section.id).first()
        return row
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        raise SpecializationError(
            f"Could not persist membership: {exc}",
            [_fail("PERSISTENCE_FAILED",
                   f"Could not persist membership: {exc}",
                   {"specialization_id": specialization_id,
                    "section_id": section_id})])


def delete_membership(db, specialization_id, section_id):
    """Remove one membership (no-op-safe)."""
    from backend.models import SpecializationMembership
    row = SpecializationMembership.query.filter_by(
        specialization_id=specialization_id,
        section_id=section_id).first()
    if row is None:
        raise SpecializationError(
            f"No membership for specialization {specialization_id} "
            f"section {section_id}.",
            [_fail("SPECIALIZATION_MEMBERSHIP",
                   f"No membership for specialization {specialization_id} "
                   f"section {section_id}.",
                   {"specialization_id": specialization_id,
                    "section_id": section_id})])
    try:
        db.session.delete(row)
        db.session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        raise SpecializationError(
            f"Could not delete membership: {exc}",
            [_fail("PERSISTENCE_FAILED",
                   f"Could not delete membership: {exc}", {})])


def query_spec_info(db=None):
    """Scheduler/validator input: per-spec totals + participating sections.

    Returns {spec_id: {enrollment_id, section_ids, total_students,
    session_type, block_length, periods_per_week, name}}.
    """
    from backend.models import Specialization, SpecializationMembership
    try:
        specs = Specialization.query.all()
    except Exception:
        return {}
    try:
        mems = SpecializationMembership.query.all()
    except Exception:
        mems = []
    by_spec = {}
    for m in mems:
        by_spec.setdefault(m.specialization_id, []).append(m)
    out = {}
    for s in specs:
        sm = by_spec.get(s.id, [])
        out[s.id] = {
            "enrollment_id": s.enrollment_id,
            "section_ids": sorted(m.section_id for m in sm),
            "total_students": sum(m.student_count for m in sm),
            "session_type": s.session_type,
            "block_length": s.block_length,
            "periods_per_week": s.periods_per_week,
            "name": s.name,
        }
    return out
