"""
Demo seed script — loads the bundled sample_data/rooms_sample.csv and
sample_data/workload_sample.csv through the real CSV import pipeline
(the same code path used by the Import CSV page), so this doubles as an
end-to-end test of that feature with a realistic, full-size dataset:
4 programs (BCA, BSc IT, BCS, Btech CSE), 9 subjects each, ~20 faculty.

Run once: python seed_demo.py
"""
import os
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "demo-admin-2026")

import io
from app import app, db, init_admin_from_env
from models import Config
import csv_import

with app.app_context():
    db.drop_all()
    db.create_all()

    cfg = Config(
        session_name="Jan 2026 - Jul 2026 | Multi-Program Demo",
        max_section_size=80,
        max_lab_group_size=40,
        working_days="Mon,Tue,Wed,Thu,Fri,Sat",
        periods="09:00-10:00|10:00-11:00|11:00-12:00|12:00-13:00|13:00-14:00|14:00-15:00|15:00-16:00",
        break_after_periods=3,
        max_consecutive_teaching=3,
    )
    db.session.add(cfg)
    db.session.commit()

    init_admin_from_env()

    class FileWrapper:
        def __init__(self, path):
            self._f = open(path, "rb")
        def read(self):
            return self._f.read()

    room_counts, room_errors = csv_import.import_rooms_csv(FileWrapper("sample_data/rooms_sample.csv"))
    print("Rooms:", room_counts, "errors:", room_errors)

    load_counts, load_errors = csv_import.import_workload_csv(FileWrapper("sample_data/workload_sample.csv"), cfg)
    print("Workload:", load_counts, "errors:", load_errors)

    from models import Section, LabGroup, Faculty, Subject, TeachingAssignment, Program
    print("\nPrograms:", Program.query.count())
    print("Sections:", [(s.name, s.student_count) for s in Section.query.all()])
    print("Lab groups:", [(lg.name, lg.student_count) for lg in LabGroup.query.all()])
    print("Faculty:", Faculty.query.count())
    print("Subjects:", Subject.query.count())
    print("Teaching assignments:", TeachingAssignment.query.count())
