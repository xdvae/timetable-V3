# Phase 6I.1 — Preferred / Home Theory Room Audit

Audit + design only. No behavior was changed in this phase.
Repository state: branch `frontend`, HEAD `2ff56df` (post-6H.5).

Terminology: "preferred room" = `Section.preferred_theory_room_id`
(a soft home-room preference for ordinary theory classes).

---

## 1. Executive Summary

- **Preferred-room support is ~5% implemented.** The column exists
  (`Section.preferred_theory_room_id`, nullable FK → `room.id`, added by
  migration `6c_additive_schema`) with a relationship and an audit
  footprint NOTE. It has **zero behavior**: nothing reads it except the
  migration test and the audit's schema-presence check.
- **What works today:** the full hard room pipeline (capacity / type /
  equipment / occupancy / locked rooms / specialization headcount) shared
  between scheduler, validator, manual edits, and audit via
  `schedule_rules.check_room_compatible`.
- **What is missing:** every behavioral piece — scheduler preference,
  API read/write, validator advisory (deliberately: none needed),
  frontend UI, room-delete orphan handling.
- **The architecture supports the feature cleanly.** Room feasibility
  (`compatible_rooms`) and room desirability (objective) are already
  separate code paths in `scheduler.py`; the preference belongs
  exclusively to the objective as an additive linear term. No hard rule,
  snapshot shape, migration, or manual-edit change is required.
- **Two pre-existing gaps the feature exposes** (no change made here):
  (a) `api_room_delete` has no referential guard, so deleting a room can
  orphan `preferred_theory_room_id` (same unguarded pattern as faculty
  delete); (b) the model comment ("unused by the scheduler until Phase
  6G", "see Phase 6B §8") is stale — the field is unused through 6H.5
  and no Phase 6B document exists in the repo (only 6E/6F/6G notes).

---

## 2. Section / Room Data Model

`backend/models.py` (actual fields):

**Section** (`section` table)
- `id` PK (int).
- `name` (string, NOT NULL, e.g. `BCA-1-A`); no uniqueness constraint
  at the DB level.
- `enrollment_id` FK → `enrollment.id`, NOT NULL → Enrollment →
  Program (which carries `department`). No direct department/program
  column on Section.
- `student_count` (int, NOT NULL) — drives room-capacity checks via
  `TeachingAssignment.group_size()`.
- `preferred_theory_room_id` FK → `room.id`, **nullable**, no
  `ondelete` behavior, no index/constraint beyond the FK. Relationship
  `preferred_theory_room = relationship("Room")`.
- Delete behavior: nothing configured. SQLite does not enforce FKs by
  default in this app (no `PRAGMA foreign_keys`), and `api_room_delete`
  (`api_routes.py:556`) deletes unconditionally — a deleted preferred
  room leaves a dangling id (verified by code inspection; cf. identical
  unguarded `api_faculty_delete`).

**Room** (`room` table)
- `id` PK; `name` unique NOT NULL, normalized to `<digits>[-LETTER]`
  by `validators.normalize_room_name` on create.
- `room_type` NOT NULL (`theory` | `lab`); `capacity` NOT NULL (int);
  `equipment_count` nullable (tracked for labs; `None` = unknown = allowed).
- **No** department / building / location / availability columns.
- No relationships to sections/classes on the model (references flow
  the other way: `ScheduledClass.room_id`, `LockedBlock.room_id`,
  `Section.preferred_theory_room_id`).

---

## 3. Existing Hard Room Rules

| Rule | Implementation | Hard/Soft | Scheduler | Validator | Manual Edit |
|---|---|---|---|---|---|
| Room existence (`UNKNOWN_ROOM`) | snapshot `rooms` dict lookup | Hard | Yes (candidates only from known rooms) | Yes (`validate_candidate`, `validate_specialization_candidate`) | Yes (via validator; own int coercion) |
| Room type H3 (`ROOM_TYPE_MISMATCH`) | `schedule_rules.check_room_type` via `check_room_compatible` | Hard | Yes (`compatible_rooms` pruning) | Yes | Yes |
| Capacity H2 (`ROOM_CAPACITY`, spec-mapped `SPECIALIZATION_CAPACITY`) | `check_room_capacity` via `check_room_compatible` | Hard | Yes (pruning; infeasible message when none) | Yes | Yes |
| Equipment H4 (`ROOM_EQUIPMENT`) | `check_room_equipment` via `check_room_compatible` | Hard | Yes (pruning) | Yes | Yes |
| Room occupancy H5 (`ROOM_CONFLICT`) | `room_occ[(room,day,p)] ≤ 1` | Hard | Yes (linear constraint) | Yes | Yes (+ conflicting-class enrichment) |
| Locked room occupancy | `locked_blocks.query_locked_placements` → `_locked_occupancy` prunes candidates with `(room,day,p)` in `locked_room` | Hard | Yes | Yes (locked rows in snapshot) | Yes (locked rows immovable) |
| Locked create requires room (`ROOM_REQUIRED`) | `locked_blocks.validate_locked_candidate` | Hard | n/a (input) | n/a | n/a |
| Spec headcount room fit | `compatible_rooms` with membership-total `group_size`; `_expand_spec_sessions` | Hard | Yes | Yes (`validate_specialization_candidate`) | n/a (spec moves forbidden) |
| Audit room checks | `audit_schedule` via same `schedule_rules` | Hard (read-only) | n/a | n/a | n/a |

Key finding: **`schedule_rules.check_room_compatible` is the single
shared hard filter** used by scheduler (`compatible_rooms`,
`scheduler.py:92`), validator, and audit. 6I must reuse it untouched —
the preference lives downstream of it, never inside it.

---

## 4. Current Scheduler Room Flow

`backend/scheduler.py` (`run_scheduler`), verified at HEAD:

1. `TeachingAssignment` → `expand_sessions()` → session dicts
   (`assignment_id, faculty_id, subject_id, session_type, group_key,
   group_label, group_size, parent_section_key, length, seq`).
   **Sessions carry no `section_id` and no preferred-room id.**
   Theory sessions are recognizable by `group_key == "section:{id}"`;
   practicals by `labgroup:{id}` (+`parent_section_key`); specs by
   `specialization:{id}`.
2. `compatible_rooms(sess, rooms)` (`:92`) filters by H2/H3/H4 only,
   preserving input room order. **Every compatible room becomes a
   candidate** — no ranking, no preference.
3. Per session × day × valid start (H9/HN1/H12/locked pruning) × each
   compatible room (locked-room clash prune): one
   `model.NewBoolVar(x_{s}_{day}_{start}_{room})` (`:597`); appended to
   `session_options[s_idx]` (`:599`). **Room ids are part of the BoolVar
   index, not separate IntVars.**
4. Hard constraints: each session placed exactly once (H1); room / faculty
   / group occupancy `≤ 1` (H5/H6/H7); H8 hierarchy; spec day/start
   equality; H12 windows; HN1 windows.
5. `ScheduledClass.room_id` = the chosen candidate's room on solve.

Room selection today is feasibility + start-minimization only; among
equal-start options the solver picks the first feasible binding
(room input order comes from unordered `Room.query.all()`).

---

## 5. Current Objective

`scheduler.py:902-907` — the **entire** objective is:

```python
objective_terms = []
for s_idx, sess in enumerate(sessions):
    for (d, start, r) in session_options[s_idx]:
        objective_terms.append(start * x[(s_idx, d, start, r)])
model.Minimize(sum(objective_terms))
```

- Single term, single weight (1 per start-period unit). Not
  lexicographic, not weighted — there are **no existing soft
  preferences** and nothing room-dependent.
- Tests barely pin the objective directly (only incidental
  `start_period == 0` placement assertions in 6E/6F tests); coverage is
  via feasibility + hard-constraint compliance. 6I.2 must add dedicated
  preference tests (see §12).

---

## 6. Preferred Room Current Usage

Complete repository inventory for `preferred_theory_room_id`:

| Location | Kind |
|---|---|
| `backend/models.py:83` | Definition (nullable FK + relationship + stale 6G/6B comment) |
| `backend/migrations/versions/6c_additive_schema.py:70,86` | `ALTER TABLE ... ADD/DROP COLUMN` (upgrade/downgrade) |
| `backend/audit_schedule.py:55` | Schema-footprint NOTE only |
| `backend/tests/test_migration_6c.py:111` | Migration assertion (column exists) |

Not present in: scheduler, validator, manual edits, locked blocks,
specializations, `api_routes.py` (no read/write/serialization),
frontend (`src/` has zero matches for prefer*/home-room), seed/demo
data, export, audit logic. **Stored only, zero behavior.**

---

## 7. Manual Editing Interaction

Verified in `manual_edits.py` + move endpoints (`api_routes.py:1402+`):

- Target room is user-chosen; room changes are independent of period
  changes (same-position = noop). Validation runs the full shared
  `validate_candidate` (H2/H3/H4 + occupancy + H12) against a snapshot
  minus the moved class, with conflicting-class enrichment.
- Preferred status never enters the path (field unread).
- **Future: change nothing.** Manual edits must validate hard room
  constraints only and must never auto-relocate toward the preferred
  room, warn about non-preferred rooms, or refuse a compatible
  non-preferred room. The validator stays hard-only so one semantic
  ("valid placement") is shared by moves, reassignments, swaps, and
  audit. No 6I.3 validator change is actually necessary.

---

## 8. Locked Block Interaction

Verified in `locked_blocks.py`, scheduler pre-solve occupancy, validator
lock footprint, `LockedBlock` model (`room_id` nullable, `room_locked`
flag; create requires a room — `ROOM_REQUIRED`):

- Locked theory classes pin an explicit room; the scheduler treats
  `(room, day, period)` as a constant (`locked_room` prune,
  `query_locked_placements`).
- **Precedence is already clean: locked room = hard fact.** Locked
  placements are never solver variables, so an objective term can never
  move them; residual sessions of the same assignment are ordinary
  variables and may still prefer the section's room where compatible.
- A locked block occupying the preferred room simply removes those
  `(room, day, period)` candidates (existing prune) — scheduling stays
  feasible elsewhere. No design work needed beyond keeping the prune
  (untouched) and excluding locked rows from any preference term
  (automatic, since they are not variables).

---

## 9. Specialization Interaction

Verified in `specializations.py`, scheduler cohort encoding
(`cohort_order` equality on day/start; rooms/faculty may differ),
`SpecializationSlot` (day/start/length only — **no room**), and
`validate_specialization_candidate`:

- Preference belongs to the **originating section only**, never to the
  cohort: `SpecializationSlot` has no room column and sync equality
  covers `(day, start)` exclusively, so a room term cannot
  desynchronize by construction — provided no 6I term is attached to
  spec sessions at all.
- Spec room choice stays governed by aggregate headcount
  (`compatible_rooms` with membership totals) + occupancy.
- **Future integration point (post-6I.2):** none required in 6I.2 —
  exclude `group_key.startswith("specialization:")` sessions from the
  preference term. Member-section normal theory classes keep working as
  today (their own section preference may apply to their normal
  sessions only).

---

## 10. API Gap Analysis

Existing state: section payloads (`GET /api/enrollments/<eid>/sections`,
assignment-page section lists: `{id, name, student_count, lab_groups}`)
and room payloads contain **no** preferred-room data; no
section-update endpoint exists (only enrollment create/delete).

Minimum 6I.4 work:
1. Include `preferred_theory_room_id` (+ room name) in section
   serializations.
2. New `POST /api/sections/<id>/preferred-room {room_id | null}`:
   404 unknown section/room; reject lab-type rooms (theory-only
   preference, administrative validation); `null` clears; capacity NOT
   validated at set time (soft semantics); set/clear must not touch
   `ScheduledClass` (no regeneration).
3. Companion fix (required by §2 orphan finding): `api_room_delete`
   nulls out referencing `preferred_theory_room_id`s in the same
   transaction (SET NULL, additive, no migration).
4. Optional: `preferred_by` section list on room payloads.

---

## 11. Frontend Gap Analysis

No preferred-room UI exists anywhere. Natural home, following the 6H.5
patterns (`useApi`/`useMutation`/toast/Dialog/Select + `retry()`
invalidation): the Enrollments sections view (per-section "Home room"
selector limited to theory rooms, with clear-to-none). No new client
abstraction needed — two methods on the existing service layer. No
timetable-view changes (faculty/room cells already derive from
`ScheduledClass` joins; nothing stale to propagate).

---

## 12. Proposed 6I Implementation Design

### 6I.2 Scheduler Preference
- **Where:** `run_scheduler`, additive only: (a) accept optional
  `preferred_rooms=None` (`{section_id: room_id}`), built in
  `api_schedule_run` from `Section` rows and filtered to existing
  theory rooms (dangling ids dropped → §15.1/15.2); (b) in the objective
  loop (`:902-907`), add `+ penalty * x[...]` per candidate where
  `penalty = 0` if the candidate room equals the session's section
  preference else `1`, applied **only** when all hold: theory session,
  `group_key` is `section:{id}`, section has a mapped preference,
  preference ∈ that session's `rooms_ok` (compatible). Everything else
  (practicals, spec sessions, locked rows, null/incompatible/missing
  preference) contributes 0. `None` (default) → byte-identical behavior;
  existing tests unaffected without new coverage.
- **Reward vs penalty:** penalty-on-non-preferred (0/1) — identical
  optimum to reward-on-preferred with one fewer constant per session,
  and zero-centered so preference-free solves are untouched.
- **Feasibility:** candidate domains and all hard constraints
  unchanged ⇒ an infeasible-today instance stays infeasible for the
  same reason, and no feasible-today instance can become infeasible.
- **Weighting (see §14):** scale start costs so time-compactness
  strictly dominates; preference breaks ties.
- **Tests:** two-theory-room fixture — (i) free preferred room ⇒
  chosen; (ii) preferred occupied/locked/incompatible ⇒ feasible
  schedule elsewhere, no error; (iii) no preference ⇒ placement
  identical to pre-6I.2 solver output; (iv) labs/spec unaffected.

### 6I.3 Validator / Manual Edit
No changes. Hard rules already shared; preference is scheduler-side
advisory. (Deliberately no "preferred but unused" warning — keeps one
validity semantic.)

### 6I.4 API
§10 items 1–3 (+ optional 4). Plus domain tests for set/clear/reject
lab/404/null-on-room-delete.

### 6I.5 Frontend
§11: home-room selector + display, existing patterns only.

---

## 14. Explicit Objective Design (recommendation for 6I.2)

Recommended formulation (matches the prompt's sketch):

```text
preferred-room penalty =
    0 if a whole-section theory session uses its section's preferred room
    1 if it uses another compatible room
    (0 for every other session type / missing / incompatible preference)
```

- **Weighting:** make time-primary strict by scaling the existing term:
  `Minimize(sum((start * K + pref_penalty) * x))` with
  `K = (#sessions + 1)` computed per solve — a true lexicographic
  guarantee (total penalty `< K`, so no room preference can ever trade
  against one period of compactness). Rationale: preserves the
  documented "compact + early-finish" behavior exactly; preference only
  arbitrates among time-equal alternatives. A small constant `K`
  (e.g. 10) is acceptable only if documented as approximate; prefer the
  exact form — it costs nothing (pure integer coefficients, no new
  variables/constraints, negligible solver impact).
- **Why not hard:** a hard "must use preferred room" contradicts the
  decided semantics (occupancy, capacity, locked conflicts must win)
  and would convert today's feasible instances into infeasible ones
  whenever the room is taken — the exact failure mode the feature must
  avoid.
- **Labs:** excluded by the `section:`-theory gate (practicals keep
  `labgroup:` keys and lab-room machinery untouched).
- **Locked:** excluded structurally (locked rows are constants, never
  variables, never re-emitted).
- **Null preference:** contributes 0 → today's behavior bit-for-bit.
- **Incompatible preferred room:** filtered by `rooms_ok` membership
  before the term applies → contributes 0, never prunes, never errors.

---

## 15. Edge Cases

| # | Case | Future behavior |
|---|---|---|
| 1 | Preferred room id points at nothing | **Normal scheduling** (treated as no preference) + administrative 404 at set time |
| 2 | Room deleted after configuration | **Normal scheduling**; 6I.4 nulls references on room delete (administrative) |
| 3 | Insufficient capacity | **Soft preference lost** — `compatible_rooms` filters it; schedule elsewhere |
| 4 | Preferred room is a lab | **Administrative validation** — reject at set time (theory-only); if present, ignored as incompatible |
| 5 | Lacks equipment | **Soft preference lost** for lab sessions (n/a for theory — equipment only constrains labs); normal scheduling |
| 6 | Occupied at desired time | **Soft preference lost** — occupancy wins; solver picks another room/time |
| 7 | Occupied by a locked block | **Soft preference lost** — locked prune wins; feasible elsewhere |
| 8 | Used by another section | **Normal scheduling** — `room_occ ≤ 1` decides; no inter-section priority in 6I.2 |
| 9 | Section lab elsewhere simultaneously | **Normal scheduling** — preference is theory-only; H8 hierarchy unchanged |
| 10 | No preferred room | **Normal scheduling** — exactly today's behavior |
| 11 | Only compatible room | **Normal scheduling** — preference trivially satisfied, zero difference |
| 12 | Several sections prefer one room | **Normal scheduling** — soft competition, no priority tiers in 6I.2 |
| 13 | Spec synchronized slots | **Normal scheduling** — spec sessions excluded from the term; sync untouched |
| 14 | Interdepartment fixed room | **Hard fact wins** — locked placement authoritative; preference never applies |
| 15 | Manual move to non-preferred room | **Manual-edit validation** — valid iff hard rules pass; no auto-relocate, no warning |
| 16 | Timetable predates preference | **Normal scheduling** — existing rows untouched until next generation replaces non-locked rows |

---

## 16. Regression / Safety Invariants (must hold through 6I)

- Room capacity / compatibility / occupancy stay hard (shared filter + constraints untouched).
- Faculty constraints, HN1, locked authority, spec synchronization unchanged.
- Manual moves never auto-relocate; validator stays hard-only.
- Setting/clearing a preference never regenerates or mutates any timetable row.
- Null preference ⇒ today's behavior exactly (`preferred_rooms=None` default + zero terms).
- Unavailable preferred room ⇒ feasible schedule elsewhere, never infeasibility caused by the preference.
- No preference term overrides any hard rule (objective-only, domains unchanged).

---

## Appendix — Verification

- Backend: `venv\Scripts\python.exe -m unittest discover -s backend\tests -t .` → **343 tests, OK**.
- Frontend: `npm run lint` → clean; `npm run build` → success (~8s).
- `git status` clean; no code modified in this phase (report file only).
