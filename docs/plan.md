# ATES Milestone Plan

Short implementation roadmap for the **Auto Timetable / Exam Scheduler (ATES)** mapped to the functional areas (`FA-1`–`FA-12`), architecture constraints (`C-1`–`C-9`), and quality requirements in `docs/SRS.pdf`.

---

## Milestone 1: Foundation, Database & Authentication (`FA-1`, `FA-12`, `DB-1`–`DB-9`)
**Goal**: Stand up the three-tier project skeleton (FastAPI + SQLAlchemy + PostgreSQL/Supabase + React/Tailwind) with role-based access control and immutable audit logging.

- **Deliverables**:
  - Apply `db/schema.sql` to Supabase (PostgreSQL 15+) and configure SQLAlchemy ORM models & versioned Alembic migrations (`DB-1`–`DB-9`, `C-3`).
  - Implement JWT authentication (`30 min` inactivity timeout), bcrypt password hashing (`cost >= 12`), and 5-attempt / `15 min` account lockout (`FR-1.1`–`FR-1.4`, `SEC-1`–`SEC-4`).
  - Enforce server-side RBAC middleware for the 5 roles: `Administrator`, `Coordinator`, `Approver`, `Faculty`, `Student` (`FR-1.5`–`FR-1.8`).
  - Build Administrator user management and append-only audit log endpoints/screens (`/auth/*`, `/audit`, `FR-12.1`–`FR-12.3`).
- **Exit Criteria**: All `FA-1` and `FA-12` endpoints pass unit/integration tests; unauthorized role calls return `HTTP 403`.

---

## Milestone 2: Master Data Management, Availability & Bulk CSV Import (`FA-2`, `FA-3`, `FA-4`)
**Goal**: Enable the Coordinator and Faculty to populate, validate, and manage all institutional scheduling inputs.

- **Deliverables**:
  - CRUD + soft-deactivation (`is_active`) endpoints and tabbed UI (`25` rows/page, search, sort) for `departments`, `courses`, `instructors`, `rooms`, `batches`, `academic_terms`, `time_slots` (auto-generated grid + blocked slots), `course_offerings`, and `enrollments` (`FR-2.1`–`FR-2.12`).
  - Weekly instructor availability toggle grid for Faculty (own record) and Coordinator (any instructor) (`FR-3.1`–`FR-3.4`).
  - Bulk CSV import service (`POST /import/{type}`, max `10 MB` UTF-8) with downloadable templates, natural-key resolution, line/column validation report, partial/cancel import choice, and `import_logs` recording (`FR-4.1`–`FR-4.5`, `P-5`).
- **Exit Criteria**: 5,000-row CSV import validates and completes in `< 15 s` (`P-5`); invalid rows are reported with exact line, column, and reason.

---

## Milestone 3: Constraint Configuration & Independent Validator (`FA-5`, `FA-8` Core)
**Goal**: Implement the modular constraint architecture (`H01`–`H10`, `S01`–`S06`, `E01`–`E05`, `ES01`–`ES03`) and the independent schedule validator before building the solvers.

- **Deliverables**:
  - Configuration management endpoints (`/configs`, `/configs/{id}/rules`) and `exam_slots` editor with non-overlap validation (`FR-5.1`–`FR-5.8`).
  - Enforce mandatory hard constraints (`H01`, `H02`, `H03`, `H08`, `E01`, `E04`, `E05`) and confirmation warnings when disabling non-mandatory hard constraints (`FR-5.2`, `FR-5.3`, `SAF-3`).
  - Build the pluggable constraint module interface (`add_to_model`, `validate`, `describe` — SRS 4.3.5) and the independent validator (`FR-6.7`, `FR-8.1`).
- **Exit Criteria**: Unit test suite with 15 deliberately violating schedules (one per hard constraint `H01`–`H10` and `E01`–`E05`) proves 100% violation detection by the independent validator (SRS Section 4.3.1).

---

## Milestone 4: Timetable & Exam Scheduling Engines (`FA-6`, `FA-7`)
**Goal**: Build the background worker solver pipelines for weekly timetables (OR-Tools CP-SAT) and exam schedules (NetworkX DSATUR + CP-SAT fallback + room allocation).

- **Deliverables**:
  - Pre-solve input completeness checker (`FR-6.1`).
  - **Timetable Solver (`FA-6`)**: CP-SAT formulation for lecture sessions and contiguous lab blocks (`FR-2.9`, `H01`–`H10`), weighted soft-constraint objective (`S01`–`S06`), locked-entry pinning (`FR-6.10`), deterministic seed support (`FR-6.9`), and background worker execution with `2 s` status polling (`POST /schedules/generate`, `GET /schedules/{id}/status`, `P-2`, `P-8`).
  - **Exam Solver (`FA-7`)**: Student-overlap conflict graph builder (`FR-7.1`), NetworkX DSATUR colouring with exact CP-SAT fallback (`FR-7.2`), daily student exam limit enforcement (`E02`, `FR-7.3`), greedy/CP room seat allocator (`Exam Hall` and `Lecture` rooms, `E03`, `E04`, `ES01`–`ES03`, `FR-7.4`–`FR-7.7`).
  - Transactional persistence (`SAF-2`) of entries, scores, run statistics, or infeasibility/shortfall `conflict_log` items.
- **Exit Criteria**: Reference dataset (Assumption A-1: `40` batches, `150` offerings, `80` instructors, `60` rooms, `48` slots, `3,000` students) solves within `120 s` for timetables (`P-2`) and `< 30 s` for exams (`P-3`) with zero hard-constraint violations.

---

## Milestone 5: Manual Adjustment, Review, Publishing & Views/Exports (`FA-8`–`FA-11`)
**Goal**: Complete the interactive schedule views, drag-and-drop adjustment, approval workflow, and PDF/CSV exports.

- **Deliverables**:
  - Filterable Timetable Grid View and Exam Schedule View with role-scoped defaults for Faculty and Students (`FR-10.1`–`FR-10.8`, `P-7`).
  - Drag-and-drop manual move & session lock/unlock for Coordinator with `< 1 s` re-validation, `is_manual_override` tagging, and undo-all-overrides (`FR-8.2`–`FR-8.7`, `P-4`).
  - Schedule state machine (`Draft -> Generating -> Generated / Infeasible -> Published -> Archived`), Approver review summary, and single-published-version archiving (`FR-9.1`–`FR-9.6`, `SAF-1`, `SAF-4`).
  - A4 landscape PDF exporter (single view and batch/instructor bundle) and UTF-8 CSV exporter (`FR-11.1`–`FR-11.5`, `P-6`).
  - End-to-end verification, WCAG 2.1 AA contrast check, and user documentation/CSV templates (`Section 2.6`).
- **Exit Criteria**: Full lifecycle test (`Import CSV -> Configure -> Generate -> Adjust -> Validate -> Approve & Publish -> View & Export PDF/CSV`) passes across all 5 user roles with `>= 70%` engine/validator test coverage (SRS 4.3.5).
