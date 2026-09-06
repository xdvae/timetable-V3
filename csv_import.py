"""CSV import: rooms.csv and workload.csv -> DB records."""
import csv
import io
import math
from collections import defaultdict

from models import (db, Room, Faculty, Program, Enrollment, Section,
                     LabGroup, Subject, TeachingAssignment)
from validators import normalize_room_name, RoomNameError


def _split_evenly(total, n):
    base = total // n
    rem = total % n
    return [base + 1] * rem + [base] * (n - rem)


def import_rooms_csv(file_storage):
    text = file_storage.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    created, updated, errors = 0, 0, []
    for i, row in enumerate(reader, start=2):
        try:
            name = normalize_room_name(row["name"])
            room_type = row["room_type"].strip().lower()
            capacity = int(row["capacity"])
            equip_raw = (row.get("equipment_count") or "").strip()
            equipment_count = int(equip_raw) if equip_raw else None
            if room_type not in ("theory", "lab"):
                raise ValueError(f"room_type must be 'theory' or 'lab', got '{room_type}'")
        except (KeyError, ValueError, RoomNameError) as ex:
            errors.append(f"Row {i}: {ex}")
            continue

        existing = Room.query.filter_by(name=name).first()
        if existing:
            existing.room_type = room_type
            existing.capacity = capacity
            existing.equipment_count = equipment_count
            updated += 1
        else:
            db.session.add(Room(name=name, room_type=room_type, capacity=capacity,
                                 equipment_count=equipment_count))
            created += 1
    db.session.commit()
    return {"created": created, "updated": updated}, errors


def import_workload_csv(file_storage, cfg):
    text = file_storage.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    programs, enrollments, sections, subjects, faculty = {}, {}, {}, {}, {}
    lab_groups_by_section = {}
    counts = defaultdict(int)
    errors = []

    required = ["program", "year_label", "section", "total_students", "faculty_name",
                "subject_code", "subject_name", "session_type", "periods_per_week", "block_length"]

    for i, row in enumerate(reader, start=2):
        missing = [c for c in required if c not in row or row[c] is None or row[c].strip() == ""]
        if missing:
            errors.append(f"Row {i}: missing/empty column(s): {', '.join(missing)}")
            continue
        try:
            program_name = row["program"].strip()
            year_label = row["year_label"].strip()
            section_name = row["section"].strip()
            total_students = int(row["total_students"])
            faculty_name = row["faculty_name"].strip()
            faculty_type = (row.get("faculty_type") or "regular").strip() or "regular"
            subject_code = row["subject_code"].strip()
            subject_name = row["subject_name"].strip()
            session_type = row["session_type"].strip().lower()
            credits = int(row.get("credits") or 3)
            periods_per_week = int(row["periods_per_week"])
            block_length = int(row["block_length"])
            if session_type not in ("theory", "practical"):
                raise ValueError(f"session_type must be 'theory' or 'practical', got '{session_type}'")
            if block_length < 1 or block_length > periods_per_week:
                raise ValueError(f"block_length ({block_length}) can't exceed periods_per_week ({periods_per_week})")
        except ValueError as ex:
            errors.append(f"Row {i}: {ex}")
            continue

        # ---- Program ----
        prog = programs.get(program_name)
        if not prog:
            prog = Program.query.filter_by(name=program_name).first()
            if not prog:
                prog = Program(name=program_name)
                db.session.add(prog)
                db.session.flush()
                counts["programs"] += 1
            programs[program_name] = prog

        # ---- Enrollment (program + year) ----
        ekey = (prog.id, year_label)
        enr = enrollments.get(ekey)
        if not enr:
            enr = Enrollment.query.filter_by(program_id=prog.id, year_label=year_label).first()
            if not enr:
                enr = Enrollment(program_id=prog.id, year_label=year_label, total_students=0)
                db.session.add(enr)
                db.session.flush()
                counts["enrollments"] += 1
            enrollments[ekey] = enr

        # ---- Section (exact student count from the CSV, as given) ----
        skey = (enr.id, section_name)
        sec = sections.get(skey)
        if not sec:
            sec = Section.query.filter_by(enrollment_id=enr.id, name=section_name).first()
            if not sec:
                sec = Section(enrollment_id=enr.id, name=section_name, student_count=total_students)
                db.session.add(sec)
                db.session.flush()
                enr.total_students = (enr.total_students or 0) + total_students
                counts["sections"] += 1
            sections[skey] = sec

        if sec.id not in lab_groups_by_section:
            existing_groups = LabGroup.query.filter_by(section_id=sec.id).all()
            if existing_groups:
                lab_groups_by_section[sec.id] = existing_groups
            else:
                n_groups = max(1, math.ceil(sec.student_count / cfg.max_lab_group_size))
                sizes = _split_evenly(sec.student_count, n_groups)
                groups = []
                for gi, size in enumerate(sizes, start=1):
                    lg = LabGroup(section_id=sec.id, name=f"{sec.name}-G{gi}", student_count=size)
                    db.session.add(lg)
                    groups.append(lg)
                db.session.flush()
                counts["lab_groups"] += len(groups)
                lab_groups_by_section[sec.id] = groups

        # ---- Subject ----
        subkey = (enr.id, subject_code)
        subj = subjects.get(subkey)
        if not subj:
            subj = Subject.query.filter_by(enrollment_id=enr.id, code=subject_code).first()
            if not subj:
                subj = Subject(code=subject_code, name=subject_name, enrollment_id=enr.id, credits=credits)
                db.session.add(subj)
                db.session.flush()
                counts["subjects"] += 1
            subjects[subkey] = subj

        # ---- Faculty ----
        fac = faculty.get(faculty_name)
        if not fac:
            fac = Faculty.query.filter_by(name=faculty_name).first()
            if not fac:
                fac = Faculty(name=faculty_name, faculty_type=faculty_type)
                db.session.add(fac)
                db.session.flush()
                counts["faculty"] += 1
            faculty[faculty_name] = fac

        # ---- Teaching assignment(s) ----
        if session_type == "theory":
            exists = TeachingAssignment.query.filter_by(
                faculty_id=fac.id, subject_id=subj.id, session_type="theory", section_id=sec.id
            ).first()
            if not exists:
                db.session.add(TeachingAssignment(
                    faculty_id=fac.id, subject_id=subj.id, session_type="theory",
                    section_id=sec.id, periods_per_week=periods_per_week, block_length=block_length,
                ))
                counts["assignments"] += 1
        else:
            for lg in lab_groups_by_section[sec.id]:
                exists = TeachingAssignment.query.filter_by(
                    faculty_id=fac.id, subject_id=subj.id, session_type="practical", lab_group_id=lg.id
                ).first()
                if not exists:
                    db.session.add(TeachingAssignment(
                        faculty_id=fac.id, subject_id=subj.id, session_type="practical",
                        lab_group_id=lg.id, periods_per_week=periods_per_week, block_length=block_length,
                    ))
                    counts["assignments"] += 1

    db.session.commit()
    return dict(counts), errors
