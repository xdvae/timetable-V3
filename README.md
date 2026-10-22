# UniSchedule

UniSchedule is an automated university timetable generation, optimization, and management system. Built for academic administrators, it combines an administrative React frontend with an OR-Tools CP-SAT constraint programming backend to generate conflict-free academic schedules and support post-generation adjustments (interactive manual moves, faculty reassignments, and faculty swaps).

The system models complex academic constraints — room capacities and equipment, faculty availability and workload limits, student cohorts split into theory sections and lab groups, lunch-break preservation, consecutive-teaching caps, high-workload theory distribution rules, interdepartment locked blocks, and synchronized specialization cohorts — and exports results across Section, Faculty, and Room views in Excel (`.xlsx`), CSV (`.csv`), or printable HTML.

---

## Table of Contents

- [Overview & Capabilities](#overview--capabilities)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Scheduling Engine & Constraints](#scheduling-engine--constraints)
  - [Hard Constraints](#hard-constraints)
  - [Soft Objective Hierarchy](#soft-objective-hierarchy)
  - [Solver Status Semantics](#solver-status-semantics)
- [Backend Services & Core Modules](#backend-services--core-modules)
  - [Manual Edits & Move Validation](#manual-edits--move-validation)
  - [Faculty Reassignments & Swaps](#faculty-reassignments--swaps)
  - [Interdepartment Locked Blocks](#interdepartment-locked-blocks)
  - [Specialization Cohorts](#specialization-cohorts)
  - [Audit & Verification System](#audit--verification-system)
  - [Unified Error Contract](#unified-error-contract)
- [API Reference](#api-reference)
- [Frontend Architecture & Features](#frontend-architecture--features)
  - [Navigation & Universal Search](#navigation--universal-search)
  - [State Propagation & Cache Invalidation](#state-propagation--cache-invalidation)
  - [Implemented Routes & Pages](#implemented-routes--pages)
  - [Design System & Palette](#design-system--palette)
- [Database & Migrations](#database--migrations)
- [CSV Ingestion & Multi-Format Export](#csv-ingestion--multi-format-export)
- [Verification & Automated Test Suite](#verification--automated-test-suite)
- [Local Development & Deployment](#local-development--deployment)
- [Environment Configuration](#environment-configuration)
- [Production Safety & Release Hardening](#production-safety--release-hardening)

---

## Overview & Capabilities

UniSchedule manages the complete academic scheduling lifecycle:

1. **Curriculum & Resource Modeling**: Define rooms (type, capacity, equipment), faculty (types, workload caps, availability matrices, soft preferences), degree programs, student enrollments (with automated section and lab-group generation), and subject catalogs.
2. **Automated Conflict-Free Solving**: Google OR-Tools CP-SAT solver computes optimal weekly timetables satisfying all hard physical and institutional constraints while optimizing compactness and teacher/room preferences.
3. **Interactive Timetable Editor**: Administrators can fine-tune generated timetables through atomic manual moves, candidate placement validation (dry-run conflict checking), and immediate cross-surface propagation without regenerating the whole timetable.
4. **Faculty Operations**: Safe, dry-run-validated single-assignment faculty reassignments and atomic two-assignment faculty swaps with full conflict detection and rollback guarantees.
5. **Specializations & Electives**: Synchronized multi-section elective cohorts with section-level membership quotas and shared time windows.
6. **Interdepartment Locked Blocks**: Integration of externally scheduled or fixed sessions that deduct assignment demand and pin solver occupancy.
7. **Comprehensive Timetable Visualizations**: Responsive multi-view calendar grids for Sections, Faculty members, and Rooms, plus an institution-wide "Who's Free" hourly matrix.
8. **Multi-Format Exports & Bulk Ingestion**: Download schedules in styled Excel (`.xlsx`), standard CSV, or printable HTML; import rooms and workload catalogs via structured CSV upload.

---

## Architecture

```text
Browser Client
   │
   ▼
React 19 Frontend (frontend/)
   ├── Single-Page Application (React Router 8, React Compiler)
   ├── Design System (Tailwind CSS v4, shadcn/ui, Radix Primitives, Lucide)
   ├── Universal Search Modal (Cmd/Ctrl+K across entities)
   ├── Cross-Surface Propagation & Invalidation System
   │
   │  same-origin /api/* requests (session cookies, no JWT)
   │  same-origin /export/* and /import/sample/* file downloads
   ▼
Flask 3.0 Backend (backend/app.py, served as backend.app:app)
   ├── Unified Error Contract (backend/errors.py)
   ├── JSON REST API Blueprint (backend/api_routes.py)
   ├── File Export Engine (backend/export.py, openpyxl)
   ├── CSV Ingestion Pipeline (backend/csv_import.py)
   ├── React SPA Production Serving (frontend/dist/ with 405 preservation)
   │
   ├── Core Domain Services:
   │   ├── Manual Class Moves (backend/manual_edits.py)
   │   ├── Faculty Reassignment & Swaps (backend/faculty_reassignment.py, faculty_swaps.py)
   │   ├── Locked Blocks (backend/locked_blocks.py)
   │   ├── Specializations (backend/specializations.py)
   │   ├── Faculty Preferences (backend/faculty_preferences.py)
   │   └── In-Memory Schedule Validator (backend/schedule_validator.py, schedule_rules.py)
   │
   ├── Solver Engine:
   │   └── Google OR-Tools CP-SAT (backend/scheduler.py)
   │
   └── Data & Storage Layer:
       ├── SQLAlchemy 3.1 ORM (backend/models.py)
       ├── SQLite (default: backend/instance/timetable.db) or PostgreSQL
       ├── Linear Migration Runner (backend/migrate.py, 6c → 6e → 6f → 6j)
       └── Automated Backup Engine (backend/backup.py)
```

In production, UniSchedule operates as a single-origin deployment served by Gunicorn: Flask serves the compiled React production bundle (`frontend/dist/`) with an SPA fallback while maintaining dedicated handling for `/api/*` routes and download endpoints.

---

## Project Structure

```text
timetable-V3/
├── backend/
│   ├── app.py                   Flask application factory, auth setup, export/import download routes,
│   │                            React production SPA catch-all serving
│   ├── api_routes.py            RESTful JSON API (/api/*) with unified error handling
│   ├── scheduler.py             Google OR-Tools CP-SAT scheduling engine (solver, constraints, objectives)
│   ├── schedule_validator.py    In-memory candidate validator for manual moves and edits
│   ├── schedule_rules.py        Constraint definition rules, failure categories, and audit checks
│   ├── manual_edits.py          Atomic scheduled class moves with dry-run candidate validation
│   ├── faculty_reassignment.py  Single-assignment faculty reassignment service with dry-run checks
│   ├── faculty_swaps.py         Two-assignment atomic faculty exchange service with rollback safety
│   ├── locked_blocks.py         Interdepartment locked blocks lifecycle, validation, and solver demand deduction
│   ├── specializations.py       Cross-section elective cohorts, slot synchronization, and headcount validation
│   ├── faculty_preferences.py   Faculty soft scheduling preferences (TIME_WINDOW, DAY_OFF, SUBJECT_AFFINITY)
│   ├── models.py                SQLAlchemy database models (Config, Room, Faculty, Program, Enrollment,
│   │                            Section, LabGroup, Subject, TeachingAssignment, ScheduledClass,
│   │                            Specialization, SpecializationMembership, SpecializationSlot,
│   │                            LockedBlock, FacultyPreference, AdminUser)
│   ├── errors.py                Phase 6Q unified API error contract, sanitization, and error response builder
│   ├── helpers.py               Shared timetable helpers (query filters, section splitting, grid formatters)
│   ├── validators.py            Entity input normalizers (room name normalization, input cleansing)
│   ├── csv_import.py            Transactional CSV import pipeline for rooms and workload
│   ├── export.py                Timetable grid builders for Excel (.xlsx), CSV, and printable HTML
│   ├── backup.py                Automated timestamped SQLite database snapshot utility
│   ├── migrate.py               Versioned migration runner with dry-run inspection and safety guards
│   ├── migrations/              Linear database migrations:
│   │   ├── versions/
│   │   │   ├── 6c_additive_schema.py      Locked blocks & preferences columns
│   │   │   ├── 6e_locked_assignment.py    Assignment linkage on locked blocks
│   │   │   ├── 6f_specializations.py      Specialization cohorts and slot tracking
│   │   │   └── 6j_faculty_preferences.py  Faculty preference weights and constraints
│   │   └── _helpers.py                    Safe schema introspection and alter table helpers
│   ├── audit_schedule.py        Standalone read-only CLI tool verifying schedule against all constraints
│   ├── seed_demo.py             Demo database populator using sample CSV datasets
│   ├── requirements.txt         Pinned Python dependencies
│   ├── sample_data/             Sample CSV datasets (rooms_sample.csv, workload_sample.csv)
│   ├── tests/                   Pytest test suite (633 automated tests across 27 test modules)
│   └── instance/                Local application storage (SQLite database files, backups)
│
├── frontend/
│   ├── src/
│   │   ├── app/                 router.jsx (React Router configuration), auth.jsx (RequireAuth), providers.jsx
│   │   ├── components/
│   │   │   ├── dashboard/       StatCard and dashboard metric widgets
│   │   │   ├── feedback/        Toast notifications, loading skeletons, error alerts, empty states,
│   │   │   │                    mutation failure presentations
│   │   │   ├── layout/          AppShell, Page container, Panel with institutional left-rule accents
│   │   │   ├── navigation/      Collapsible shadcn Sidebar, UniversalSearchModal (Cmd/Ctrl+K), nav-config
│   │   │   ├── timetable/       TimetableGrid, TimetableClassBlock, TimetableLegend, timetable-helpers
│   │   │   └── ui/              shadcn/ui primitives (Button, Dialog, Dropdown, Input, Select, Table, Drawer, etc.)
│   │   ├── hooks/               useApi (cancellable fetch), useAuth, useMutation, useToast, useMediaQuery
│   │   ├── lib/                 failures.js (error normalization), invalidation.js (domain cache invalidation),
│   │   │                        propagation.js (cross-surface events), utils.js (cn helper)
│   │   ├── pages/               Page views:
│   │   │   ├── Account/         Admin password change (/account/change-password)
│   │   │   ├── Assignments/     Teaching assignments management (/assignments)
│   │   │   ├── Config/          Institution settings & period config (/config)
│   │   │   ├── Dashboard/       Executive overview and session summary (/)
│   │   │   ├── Enrollments/     Enrollment cohorts & sections (/enrollments, /enrollments/:eid/sections)
│   │   │   ├── Faculty/         Faculty directory, availability grid, soft preferences
│   │   │   │                    (/faculty, /faculty/:fid/availability, /faculty/:fid/preferences)
│   │   │   ├── FreeFaculty/     Who's Free hour-by-hour matrix (/timetable/free)
│   │   │   ├── Import/          CSV bulk upload & sample downloads (/import)
│   │   │   ├── LockedBlocks/    Interdepartment locked blocks manager (/timetable/locked-blocks)
│   │   │   ├── Login/           Session-cookie sign-in (/login)
│   │   │   ├── Overview/        Institution workload and student group overview (/overview)
│   │   │   ├── Programs/        Academic degree programs (/programs)
│   │   │   ├── Rooms/           Room management (/rooms)
│   │   │   ├── Specializations/ Multi-section elective cohorts (/enrollments/:eid/specializations)
│   │   │   ├── Subjects/        Course catalog (/subjects)
│   │   │   └── Timetable/       Timetable viewer (/timetable, /timetable/:view/:id) and
│   │   │                        Interactive Timetable Editor (/timetable/editor)
│   │   ├── services/api/        Centralized fetch client (client.js) and domain API services
│   │   ├── index.css            Tailwind CSS v4 theme, institutional tokens, and color definitions
│   │   ├── main.jsx             Application entry point
│   │   └── App.jsx              Root router provider
│   ├── package.json             Frontend dependencies and scripts
│   ├── vite.config.js           Vite 8 config with Tailwind v4, React Compiler, and /api dev proxy
│   ├── vitest.config.js         Vitest configuration for unit and integration testing
│   └── components.json          shadcn/ui configuration
│
├── Procfile                     Gunicorn production entrypoint (web: gunicorn backend.app:app)
├── .env.example                 Documented environment variables template
└── README.md                    System documentation
```

---

## Scheduling Engine & Constraints

The scheduling engine (`backend/scheduler.py`) compiles curriculum requirements into an integer programming problem solved with **Google OR-Tools CP-SAT**.

### Hard Constraints

All schedules generated by the solver strictly adhere to the following physical and institutional invariants:

1. **Room Compatibility & Capacity**:
   - Theory classes must be assigned to theory rooms with capacity $\ge$ student group size.
   - Practical / lab sessions must be assigned to lab rooms with capacity $\ge$ lab group size and required equipment counts.
2. **Double-Booking Prevention**:
   - A room can host at most one class in any given period.
   - A faculty member can teach at most one class in any given period.
   - A student group (section or lab group) can attend at most one class in any given period.
3. **Lab / Theory Hierarchy**:
   - Sub-groups of a section (e.g., `BCA-1-A-G1`) cannot be scheduled in a lab session while their parent section (`BCA-1-A`) is attending a theory lecture.
   - Parallel lab groups of the same section may run concurrently in separate lab rooms.
4. **Lunch Break Integrity**:
   - Multi-period session blocks (e.g., 2-period lab blocks) cannot span across the configured lunch break period.
5. **Faculty Availability**:
   - Classes are never placed in periods marked as unavailable on the faculty member's availability grid.
6. **Maximum Consecutive Teaching**:
   - Faculty members cannot be scheduled for more than `max_consecutive_teaching` back-to-back periods without a break.
7. **HN1 Rule (High-Workload Theory Spacing)**:
   - A student section may have **at most two consecutive theory periods** in any contiguous teaching-period segment of a day. Practical lab sessions, free periods, and the lunch break reset the theory streak.
8. **Interdepartment Locked Blocks**:
   - Sessions marked as locked (e.g., external faculty teaching common subjects) enter the solver as immutable pre-solve occupancy, deducting directly from assignment demand.
9. **Specialization Synchronized Cohorts (HN3)**:
   - Specialization sessions within the same cohort share identical time slots (`day`, `start_period`, `length`) across different rooms/faculty while conservatively blocking all originating parent sections.

### Soft Objective Hierarchy

When multiple conflict-free solutions exist, OR-Tools optimizes a strictly hierarchical weighted cost function (Phase 6S):

$$\text{Total Cost} = W_{\text{compact}} \cdot \text{Cost}_{\text{start\_periods}} + W_{\text{room}} \cdot \text{Cost}_{\text{room\_mismatch}} + W_{\text{faculty}} \cdot \text{Cost}_{\text{faculty\_prefs}}$$

- **Tier 1 — Schedule Compactness (Dominant)**: Minimizes late-day class placements, prioritizing morning/mid-day periods to eliminate dead gaps and compact student schedules.
- **Tier 2 — Section Home-Room Preference (Subordinate)**: Rewards scheduling theory classes in the section's preferred theory room (`preferred_theory_room_id`). Never overrides compactness.
- **Tier 3 — Faculty Scheduling Preferences (Lowest)**: Soft rewards and penalties (weights 1–10) based on configured faculty preferences:
  - `TIME_WINDOW`: Encourages scheduling classes within a faculty member's preferred daily time window.
  - `DAY_OFF_PREFERENCE`: Encourages keeping a preferred day free of classes.
  - `SUBJECT_AFFINITY`: Soft preference for specific section/subject pairings.

### Solver Status Semantics

The generation endpoint (`POST /api/schedule/run`) implements rigorous solver status semantics (Phase 6T):

| Solver Status | HTTP Status | Response Payload | Invalidation / Rollback Behavior |
| :--- | :--- | :--- | :--- |
| `OPTIMAL` | `200 OK` | `{ok: true, status: "OPTIMAL", placements: N, run_id: "..."}` | Existing unlocked classes atomically replaced; timetable cache invalidated. |
| `FEASIBLE` | `200 OK` | `{ok: true, status: "FEASIBLE", placements: N, run_id: "..."}` | Feasible solution accepted within time limit; existing unlocked classes replaced. |
| `INFEASIBLE` | `422 Unprocessable` | `{ok: false, code: "SCHEDULING_INFEASIBLE", details: {locked_block_ids: [...]}}` | Solver proved no schedule can satisfy all hard rules. **Previous schedule is preserved untouched.** |
| `UNKNOWN` | `422 Unprocessable` | `{ok: false, code: "SCHEDULING_FAILED", details: {timeout: true, status: "UNKNOWN"}}` | Solver reached time limit without finding a solution. **Previous schedule is preserved untouched.** |
| `MODEL_INVALID` | `500 Server Error` | `{ok: false, code: "INTERNAL_ERROR", details: {reason: "..."}}` | Model specification error. Internal diagnostics logged; safe message returned to user. |

---

## Backend Services & Core Modules

### Manual Edits & Move Validation

The manual editing engine (`backend/manual_edits.py`) enables atomic relocation of individual scheduled classes without re-running the solver:

- **Dry-Run Validation (`POST /api/schedule/classes/<cid>/validate-move`)**: Evaluates a candidate move (`day`, `start_period`, `room_id`) against in-memory snapshots (`backend/schedule_validator.py`) without database mutation. Verifies room availability, capacity, type, faculty double-booking, faculty availability, section/group collisions, break integrity, and HN1 theory streak limits.
- **Atomic Execution (`POST /api/schedule/classes/<cid>/move`)**: Performs the validated move within a database transaction. If any constraint check fails, the transaction rolls back completely.
- Locked classes (`is_locked=True`) cannot be moved.

### Faculty Reassignments & Swaps

Faculty allocation management (`backend/faculty_reassignment.py`, `backend/faculty_swaps.py`) allows administrative adjustments to existing teaching assignments:

- **Reassignment (`/api/assignments/<aid>/validate-reassign` & `/api/assignments/<aid>/reassign`)**: Replaces an assignment's faculty member with a new instructor. Validates weekly workload caps, availability for all currently placed classes, and double-booking conflicts.
- **Faculty Swaps (`/api/assignments/validate-swap` & `/api/assignments/swap`)**: Atomically exchanges faculty between two assignments. Ensures neither instructor is double-booked across the combined scheduled sessions and respects weekly workload maximums.

### Interdepartment Locked Blocks

The locked blocks module (`backend/locked_blocks.py`) manages fixed scheduling commitments (e.g., classes taught by visiting faculty or external departments):

- Locked blocks specify `day`, `start_period`, `length`, `subject`, `faculty`, and optional `room`.
- They automatically link to their underlying `TeachingAssignment` (Phase 6E) to deduct demand before the solver runs.
- During solver generation, locked placements are preserved in place. During regeneration, locked rows are never cleared or relocated.

### Specialization Cohorts

The specializations module (`backend/specializations.py`) coordinates elective groupings across multiple sections (e.g., students from Sections A, B, and C taking "Cyber Security" or "Data Science"):

- Groups students by section headcount (`SpecializationMembership`) without tracking individual student records.
- Verifies that section membership quotas do not exceed total section size.
- Generates synchronized `SpecializationSlot` entries ensuring all parallel specialization options run at the exact same periods.

### Audit & Verification System

UniSchedule includes a standalone, read-only schedule audit utility (`backend/audit_schedule.py`):

```bash
python -m backend.audit_schedule --db backend/instance/timetable.db
```

The audit tool connects using SQLite read-only mode (`mode=ro`), guaranteeing no schema mutations or admin creation, and verifies:
- Room occupancy and capacity compliance
- Faculty availability and double-booking checks
- Section and lab group isolation
- Lunch break spanning violations
- Faculty consecutive teaching run compliance
- HN1 rule compliance (max 2 consecutive theory periods)
- Specialization slot synchronization and capacity bounds

### Unified Error Contract

All JSON API endpoints enforce the **Phase 6Q Unified Error Contract** (`backend/errors.py`). API error responses follow a standardized shape:

```json
{
  "ok": false,
  "error": "Human-readable sanitized error message.",
  "code": "STABLE_MACHINE_READABLE_CODE",
  "details": { "optional": "context" },
  "field_errors": { "field_name": "Specific validation failure." },
  "failures": [
    { "code": "FAILURE_CODE", "message": "Failure detail.", "details": {} }
  ]
}
```

- **Sanitization Guarantee**: SQL fragments, database tracebacks, file paths, and environment secrets are never exposed to the client.
- **Standard Codes**: `AUTH_REQUIRED`, `INVALID_CREDENTIALS`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `BAD_REQUEST`, `SCHEDULING_FAILED`, `SCHEDULING_INFEASIBLE`, `INTERNAL_ERROR`.

---

## API Reference

All application endpoints are prefixed with `/api` and require a valid session cookie (except `/api/login` and the React static shell).

### Authentication & Session

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/login` | Sign in with username and password; sets session cookie. |
| `POST` | `/api/logout` | Terminate session and clear session cookie. |
| `GET` | `/api/me` | Return authenticated user details (`{id, username}`). |
| `POST` | `/api/change-password` | Update current administrator password. |

### Configuration & Infrastructure

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard` | Summary statistics (rooms, faculty, programs, enrollments, schedule status). |
| `GET` | `/api/config` | Read global configuration (working days, periods, break index, max consecutive teaching). |
| `POST` | `/api/config` | Update global scheduling configuration. |
| `GET` | `/api/rooms` | List all rooms (type, capacity, equipment count). |
| `POST` | `/api/rooms` | Create a new room with capacity and equipment. |
| `POST` | `/api/rooms/<id>/delete` | Delete a room. |

### Faculty & Availability

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/faculty` | List faculty with department, type, weekly max hours, and assigned workload. |
| `POST` | `/api/faculty` | Create a new faculty member. |
| `POST` | `/api/faculty/<id>/delete` | Delete a faculty member. |
| `GET` | `/api/faculty/<id>/availability` | Read faculty unavailable day/period slots. |
| `POST` | `/api/faculty/<id>/availability` | Update faculty unavailable day/period slots. |
| `GET` | `/api/faculty/<id>/preferences` | List faculty soft scheduling preferences (`TIME_WINDOW`, `DAY_OFF`). |
| `POST` | `/api/faculty/<id>/preferences` | Create a new soft scheduling preference. |
| `POST` | `/api/faculty/preferences/<pid>` | Update an existing preference weight or parameters. |
| `POST` | `/api/faculty/preferences/<pid>/delete`| Delete a soft preference. |

### Academic Structure & Enrollments

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/programs` | List academic degree programs. |
| `POST` | `/api/programs` | Create a degree program. |
| `POST` | `/api/programs/<id>/delete` | Delete a degree program. |
| `GET` | `/api/enrollments` | List enrollments (program + year + student counts + section counts). |
| `POST` | `/api/enrollments` | Create enrollment (automatically generates sections and lab groups). |
| `POST` | `/api/enrollments/<id>/delete` | Delete enrollment and associated sections. |
| `GET` | `/api/enrollments/<eid>/sections`| List sections for an enrollment with student counts and preferred room. |
| `POST` | `/api/sections/<sid>/preferred-room` | Set or clear section preferred theory room (`{room_id}`). |

### Specializations & Electives

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/specializations` | List all specializations with memberships, slots, and scheduled classes. |
| `GET` | `/api/specializations/<sid>` | Get detailed specification for a single specialization. |
| `POST` | `/api/specializations` | Create a specialization cohort under an enrollment. |
| `POST` | `/api/specializations/<sid>/delete` | Delete a specialization and its memberships/slots. |
| `POST` | `/api/specializations/<sid>/memberships` | Upsert section student count quota in a specialization. |
| `POST` | `/api/specializations/<sid>/memberships/delete` | Remove a section's membership from a specialization. |

### Subjects & Teaching Assignments

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/subjects` | List subjects with theory/practical hours, credits, and default block lengths. |
| `POST` | `/api/subjects` | Create a new subject. |
| `POST` | `/api/subjects/<id>/delete` | Delete a subject. |
| `GET` | `/api/assignments` | List teaching assignments with faculty, subject, section/group, and periods. |
| `POST` | `/api/assignments` | Create a teaching assignment. |
| `POST` | `/api/assignments/<id>/delete` | Delete a teaching assignment. |
| `POST` | `/api/assignments/<aid>/validate-reassign` | Dry-run check for faculty reassignment (`{faculty_id}`). |
| `POST` | `/api/assignments/<aid>/reassign` | Atomically reassign faculty member on an assignment. |
| `POST` | `/api/assignments/validate-swap` | Dry-run check for faculty swap (`{assignment_a_id, assignment_b_id}`). |
| `POST` | `/api/assignments/swap` | Atomically swap faculty between two assignments. |

### Schedule Generation & Interactive Editing

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/schedule/run` | Execute CP-SAT solver to generate conflict-free weekly timetable. |
| `GET` | `/api/schedule/classes` | List all scheduled classes with assignment context, room, lock, and slot status. |
| `POST` | `/api/schedule/classes/<cid>/validate-move` | Dry-run validation of class move (`{day, start_period, room_id}`). |
| `POST` | `/api/schedule/classes/<cid>/move` | Atomically move scheduled class to a new day, period, and room. |
| `GET` | `/api/locked-blocks` | List interdepartment locked blocks. |
| `POST` | `/api/locked-blocks` | Create and pin a new locked block. |
| `POST` | `/api/locked-blocks/<id>/delete` | Delete a locked block. |

### Timetable Views & Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/overview` | Institutional breakdown of sections, groups, and faculty contact hours. |
| `GET` | `/api/timetable` | Timetable index with selectable section, faculty, and room lists. |
| `GET` | `/api/timetable/<view>/<id>` | Grid data for a specific view (`section`, `faculty`, `room`) with parallel lanes. |
| `GET` | `/api/timetable/free` | Who's Free matrix showing faculty availability hour-by-hour for a given day. |

### Bulk Ingestion & File Downloads

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/import/rooms` | Ingest rooms CSV file with transactional upsert. |
| `POST` | `/api/import/workload` | Ingest workload CSV file with auto-creation of entities. |
| `GET` | `/import/sample/<kind>` | Download sample CSV (`rooms` or `workload`). |
| `GET` | `/export/<view>/<id>/<fmt>` | Download timetable grid as `xlsx`, `csv`, or `html`. |

---

## Frontend Architecture & Features

The frontend is a modern single-page application built with **React 19**, **Vite**, and **Tailwind CSS v4** utilizing the **React Compiler**.

### Navigation & Universal Search

- **Responsive AppShell**: Desktop view features a 246px collapsible sidebar with route indicators and badge counts. Mobile view provides a touch-friendly off-canvas drawer.
- **Universal Search Modal (Cmd/Ctrl+K)**: Instant keyboard-driven global search across sections, faculty members, rooms, subjects, and programs with direct navigation to corresponding timetable views.

### State Propagation & Cache Invalidation

To maintain synchronized UI state across multiple views without full page reloads, the frontend employs a structured propagation and invalidation system (Phase 6P):

- **Event Bus (`frontend/src/lib/propagation.js`)**: Mutations emit domain events (`MOVE`, `SWAP`, `REASSIGN`, `CONFIG_CHANGE`, `SCHEDULE_RUN`).
- **Domain Invalidation Matrix (`frontend/src/lib/invalidation.js`)**: Maps mutation events to specific query keys. For instance, a manual class move invalidates timetable views, the editor grid, and the Who's Free matrix, while preserving cached faculty directory and room configurations.
- **`useApi` Hook (`frontend/src/hooks/use-api.js`)**: GET-on-mount fetch hook with built-in `AbortController` cancellation, declarative invalidation listeners, and automatic retry handling.

### Implemented Routes & Pages

All routes are fully implemented and connected to real backend data:

- `/login` — Session-cookie authentication with `?next=` deep-link redirection
- `/` — Institutional Dashboard with quick metrics and generation shortcuts
- `/config` — System configuration (working days, period schedule, lunch break, teaching limits)
- `/rooms` — Room catalog with type, capacity, and equipment editing
- `/faculty` — Faculty directory with contact hours and links to availability
- `/faculty/:fid/availability` — Interactive day $\times$ period availability matrix
- `/faculty/:fid/preferences` — Faculty soft scheduling preferences (`TIME_WINDOW`, `DAY_OFF`)
- `/programs` — Academic degree programs
- `/enrollments` — Student cohorts and enrollments
- `/enrollments/:eid/sections` — Section breakdown with preferred theory room assignment
- `/enrollments/:eid/specializations` — Elective/specialization cohort management
- `/enrollments/:eid/specializations/:sid` — Specialization detail with section quota allocations
- `/subjects` — Course catalog (credits, contact hours, block sizes)
- `/assignments` — Teaching assignments with inline faculty reassignment and swap triggers
- `/import` — Drag-and-drop CSV upload for rooms and workload with sample templates
- `/overview` — Institutional workload distribution and student group matrix
- `/timetable` — Multi-view timetable viewer (Section, Faculty, Room) with parallel lanes
- `/timetable/editor` — Interactive Timetable Editor with dry-run move validation and atomic execution
- `/timetable/locked-blocks` — Interdepartment locked blocks configuration
- `/timetable/free` — Who's Free matrix for faculty availability
- `/account/change-password` — Administrator password update

### Design System & Palette

The user interface uses custom design tokens reflecting an institutional aesthetic:

| Token | Hex Code | Role |
| :--- | :--- | :--- |
| **Ink** | `#16233F` | Deep navy primary brand, sidebar background, dark accents |
| **Brass** | `#B8873A` | Warm gold accent, primary action buttons, highlights |
| **Steel** | `#3E6B96` | Slate blue, theory class blocks, secondary accents |
| **Sage** | `#4B7B62` | Muted green, practical/lab session blocks, success states |
| **Signal** | `#A6423A` | Brick red, danger buttons, validation errors, locked blocks |

Typography uses **Inter** for UI elements and **Source Serif 4** for display headings.

---

## Database & Migrations

- **Default Engine**: SQLite (`backend/instance/timetable.db`).
- **Production Engine**: PostgreSQL supported by setting `DATABASE_URL=postgresql://user:pass@host:5432/dbname`.
- **Versioned Migration Runner (`backend/migrate.py`)**:
  Linear migration chain (`6c → 6e → 6f → 6j`):
  - `6c`: Additive schema for locked blocks, preferences, and section home rooms.
  - `6e`: Assignment foreign key linkage on locked blocks.
  - `6f`: Specialization cohorts, section memberships, and synchronized slots.
  - `6j`: Faculty preference weights, kinds, and validation constraints.

To inspect migration status:
```bash
python -m backend.migrate current
```

To run migrations safely on a database copy:
```bash
python -m backend.migrate --db <path-to-copy.db> upgrade
```
*(The `--allow-live` flag is required if executing migrations directly against the live database).*

---

## CSV Ingestion & Multi-Format Export

### Rooms CSV (`backend/sample_data/rooms_sample.csv`)
```csv
name,room_type,capacity,equipment_count
LH-101,theory,80,
LH-102,theory,80,
CS-LAB-1,lab,40,40
```
- `name`: Normalized room identifier (e.g., `LH 101` $\rightarrow$ `LH-101`).
- `room_type`: `theory` or `lab`.
- `capacity`: Maximum student capacity.
- `equipment_count`: Available workstations (labs only).

### Workload CSV (`backend/sample_data/workload_sample.csv`)
```csv
program,year_label,section,total_students,faculty_name,faculty_type,subject_code,subject_name,session_type,credits,periods_per_week,block_length
BCA,1st Year,A,75,Dr. Sharma,regular,BCA101,Programming in C,theory,4,4,1
BCA,1st Year,A,75,Dr. Sharma,regular,BCA101P,C Programming Lab,practical,2,2,2
```
- Ingestion creates missing programs, enrollments, sections, subjects, and faculty automatically.
- Practical rows automatically generate assignments for each sub-divided lab group (`G1`, `G2`).

### Export Options
Export endpoints produce standalone files formatted per timetable view (one section, faculty member, or room at a time):
- **Excel (`.xlsx`)**: Styled workbook generated with `openpyxl` featuring color-coded theory/lab cells, merged multi-period blocks, and clean typography.
- **CSV (`.csv`)**: Day $\times$ Period tabular grid.
- **Printable HTML (`.html`)**: Self-contained HTML with embedded styles formatted for direct printing.

---

## Verification & Automated Test Suite

The UniSchedule repository includes a comprehensive automated test suite covering all backend constraints, API contracts, solver objectives, and frontend integration behaviors:

### Backend Pytest Suite (633 Tests)
Located in `backend/tests/`:
- `test_hn1.py`, `test_hn1_capacity.py` — High-workload consecutive theory limits and capacity rules
- `test_scheduler_objective_6s.py` — Hierarchy of CP-SAT soft objective tiers and benchmarks
- `test_scheduler_status_6t.py` — Solver status mapping (`OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`)
- `test_manual_edits_6g.py`, `test_manual_edits_6n.py` — Atomic class moves and candidate validator
- `test_faculty_reassignment_6h.py` — Workload caps and availability checks during reassignment
- `test_faculty_swap_6h.py` — Atomic two-assignment faculty exchanges
- `test_locked_blocks_6e.py` — Interdepartment locked blocks demand deduction and occupancy pinning
- `test_specializations_6f.py` — Specialization multi-section cohorts, quotas, and synchronized slots
- `test_preferred_room_6i.py`, `test_preferred_room_validator_6i.py` — Home room soft preferences
- `test_faculty_preferences_6j.py` — Faculty time windows and day-off soft weights
- `test_errors_6q.py` — Unified API error contract, sanitization, and error envelopes
- `test_timetable_cells_6r.py` — Lane/block rendering semantics and cell shape contracts
- `test_frontend_integration_contracts_6u.py` — End-to-end API contract testing for frontend
- `test_production_safety_6v.py` — Production startup, SPA catch-all, and regression hardening
- `test_audit_readonly.py` — Read-only verification tool validation

Run the backend test suite:
```bash
pytest
```

### Frontend Vitest Suite (162 Tests)
Located across `frontend/src/**/__tests__/`:
- `sidebar-shadcn.test.jsx` — Responsive AppShell, sidebar collapse states, route matching
- `universal-search.test.jsx` — Global search modal, keyboard shortcuts, navigation
- `timetable-6r.test.jsx` — Timetable grid rendering, merged cells, parallel lanes, accessibility
- `api-contract-6u.test.js` — Client API contracts and error normalization
- `error-components-6q.test.jsx`, `errors-6q.test.js` — Safe error presentation and failure code handling
- `propagation.test.js`, `invalidation.test.js` — Cross-surface event bus and cache invalidation
- `cross-surface.test.jsx` — Multi-surface synchronization matrix

Run the frontend test suite:
```bash
cd frontend
npm test
```

---

## Local Development & Deployment

### Prerequisites
- Python 3.12+
- Node.js 18+ and npm

### 1. Backend Setup
From the repository root:
```bash
# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install backend dependencies
pip install -r backend/requirements.txt

# Run the Flask development server (serves on http://127.0.0.1:5050)
python -m backend.app
```

### 2. Frontend Setup
From the `frontend/` directory:
```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite development server
npm run dev
```
The Vite development server runs on its default port and automatically proxies `/api`, `/export`, and `/import/sample` requests to the Flask backend at `http://127.0.0.1:5050`.

### 3. Loading Demo Data (Optional)
To populate the database with sample departments, rooms, faculty, and workload:
```bash
python -m backend.seed_demo
```
Then navigate to **Timetable** $\rightarrow$ **Generate Timetable** in the web interface.

### 4. Production Deployment (Single-Origin Process)
Build the React frontend into static assets and serve via Gunicorn:
```bash
# Build React static bundle
cd frontend
npm install
npm run build
cd ..

# Start single-origin production server
gunicorn backend.app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 90
```
Flask serves the compiled bundle from `frontend/dist/` with an SPA fallback for non-API GET requests while preserving 405 Method Not Allowed semantics for API routes.

---

## Environment Configuration

Copy `.env.example` to `.env` in the repository root. Never commit `.env` or sensitive credentials to version control.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///timetable.db` | Database connection URI (`sqlite:///timetable.db` or PostgreSQL URI). |
| `SECRET_KEY` | *(Generated on boot)* | Cryptographic key used to sign session cookies. **Must be fixed in production.** |
| `ADMIN_USERNAME` | `admin` | Initial administrator login username created on first run. |
| `ADMIN_PASSWORD` | *(Generated on boot)* | Initial administrator login password. If unset, a random password is printed once to the console. |
| `INSTITUTION_NAME` | `UniSchedule Demo` | Institutional title displayed on dashboard and session headers. |

---

## Production Safety & Release Hardening

Following Phase 6V hardening, UniSchedule implements strict operational safety practices:

1. **State Isolation**: Database mutation, migration tests, and solver benchmarks use isolated temporary SQLite databases (`tempfile.NamedTemporaryFile`) and never mutate reference demo files.
2. **Copy-on-Write Migrations**: Production database upgrades operate on verified copies using `python -m backend.migrate --db <path.db> upgrade` before swapping files into production.
3. **Audit Safety**: The standalone audit CLI (`python -m backend.audit_schedule`) strictly opens SQLite with `uri=True` and `mode=ro` preventing any schema creation or row mutation.
4. **Session-Cookie Security**: The React frontend communicates strictly over same-origin requests using HTTP-only session cookies. No JWTs, access tokens, or credentials are stored in `localStorage` or `sessionStorage`.
5. **Deterministic Diagnostics**: Solver infeasibility returns detailed conflict metadata (e.g. blocking locked block IDs) to administrators while preventing internal server crashes.
