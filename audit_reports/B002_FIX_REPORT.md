# B002 — Weekly grid and clock-time overlap fix

21 November 2026. Scope: B002 only. Uses isolated SQLite databases and in-memory engine datasets; no production data or database schema was modified.

## Changes and root causes

The API previously validated interval order and uniqueness of a weekday/index pair, but did not validate the complete weekly grid. Updates could bypass even those checks; bulk generation could construct invalid `time()` objects and return HTTP 500. Weekly requests now use strict local minute-aligned `HH:MM` or `HH:MM:00` parsing, strict weekday integers 1–7 and positive SMALLINT indexes 1–32767. Full candidate grids are checked before attaching or changing ORM rows. Same-day intersections and duplicate indexes return 409; malformed values, unequal durations, reversed/empty/cross-midnight intervals and chronological index errors return 422. Bulk failures leave no partially inserted rows. PostgreSQL term-row locks serialize cooperating API writers.

Grid length is derived from the existing term grid, since the schema has no separate configured-duration column. The first slot establishes a new term's duration. Updates preserve that length even for a one-slot grid. Valid configured lengths other than the default 60 minutes remain supported. Index gaps and nonteaching gaps are allowed; indexes must follow chronological order. Blocked slots participate in grid validation. Times use half-open intervals, so an interval ending at 09:00 can be followed by one starting at 09:00. Midnight and 24:00 endpoints are rejected rather than rolled over.

The solver previously trusted different slot IDs to represent different physical windows. It now rejects invalid grids before constructing or solving its CP-SAT model. H01, H02 and H03 also use physical occupancy windows in `AddAtMostOne`, preserving the existing architecture and other constraints. Overlap chains constrain each actual intersection rather than unnecessarily excluding adjacent endpoints. Separate instructors, rooms and batches may still share a time window.

The independent validator previously grouped resource conflicts by slot ID. It now compares clock intervals independently of the solver occupancy implementation and reports affected slot IDs for instructor, room and batch clashes. Mandatory grid failures cannot be disabled by configuration. Malformed grids return explicit hard C-6 violations instead of guessed 60-minute durations or exceptions. H08 still checks required offering/session counts; missing required courses or unknown offering references also cannot silently bypass validation. Manual adjustment routes already invoke this validator and inherit these checks.

## B002 files added or changed

- `backend/schemas.py`: weekly clock/domain and generation option validation.
- `backend/routers/master_data.py`: complete candidate grid checks for single creation, update and bulk generation; atomic rejection and HTTP error handling. Existing B001 Coordinator dependencies are preserved.
- `engine/weekly_grid.py` (new): reusable interval parser, grid invariants and CP-SAT occupancy windows.
- `engine/models.py`: eliminate the silent duration fallback for malformed weekly intervals.
- `engine/timetable_solver.py`: grid preflight rejection.
- `engine/constraints.py`: physical H01/H02/H03 exclusions and independent temporal conflict detection.
- `engine/validator.py`: mandatory grid validation, reference checks and required-course count safeguards.
- `tests/test_weekly_grid.py` (new): B002 API, solver, standalone CP-SAT and independent validator regressions.
- `audit_reports/BUG_REPORT.md`: B002 resolution annotation; original audit evidence retained.
- This report and the `b002_*` logs/XML/JSON evidence files. Generated frontend bundle output is locally excluded from Git.

No frontend source changes were needed. Existing tests and audit probes were retained without weakening assertions. Pre-existing uncommitted B001 changes remain in the working tree and are separate from this list.

## Verification

The full project suite passed: **203 passed, 0 failed**, comprising the existing 116 tests (including all 37 B001 security tests) and 87 new B002 regressions. Final results are recorded in `b002_project_tests.log` and `b002_project_tests.xml`. The first separate B002 run passed 81 cases; six additional boundary/compatibility cases were then added and passed in the final full run. Deprecation warnings concern the installed Starlette/httpx integration and the existing FastAPI 422 status constant alias; they are not test failures.

The six targeted audit regressions passed: weekly overlap, unequal slot length, malformed time, cross-midnight generation, invalid weekday and solver rejection of overlapping clock slots. See `b002_targeted_audit.log` / `.xml`.

The full retained audit suite returned **14 passed, 14 failed** (previous B001 baseline: 8 passed, 20 failed). All six newly passing tests are B002 cases; there are no newly failing audit tests. See `b002_audit_comparison.json` and `b002_audit_regressions.log` / `.xml`. No failure was excused as an intentionally replaced security or scheduling assumption.

Frontend application TypeScript, tooling TypeScript and the Vite production build passed. Commands were `node node_modules/typescript/bin/tsc -p tsconfig.app.json --noEmit`, the equivalent `tsconfig.node.json` check, and `node node_modules/vite/bin/vite.js build --outDir ../audit_reports/b002_frontend_build`. See `b002_frontend_checks.log`.

Tests use `.venv/Scripts/python.exe -B -m pytest ... -p no:cacheprovider -q` with JUnit XML output. Project scope is `tests`; audit scope is both `audit_reports/test_audit_probes.py` and `audit_reports/test_extra_probes.py`. The targeted selector includes `weekly_slot`, `unequal_slot`, `overlapping_clock`, `bad_time`, `midnight` and `invalid_day`.

B001's 17 tracked authentication, authorization, migration, test-fixture and frontend integration files have unchanged SHA-256 hashes. See `b002_b001_baseline.json` and `b002_b001_preservation.json`. B001 regression tests remain in the project suite, with real authentication used by B002 API tests.

## Remaining limitations and SRS work outside B002

The full audit is not green. Remaining failures concern draft/student visibility, missing user/audit/import/publication/export endpoints, published master-data integrity, lab clock contiguity, mixed exam enrollments, exam manual override metadata, mutation auditing and default lazy-app orphan recovery. These are retained findings, not B002 regressions. In particular B003 exam membership and B005 lab adjacency remain unresolved. Chronological grid validation rejects the malformed B005 audit fixture, but does not implement the separate mandatory lab clock-adjacency rule.

There is no implemented weekly-slot CSV import endpoint to update; the applicable bulk path is `/terms/{term_id}/slots/generate`. Future import implementations must use the same full-grid validation. Direct SQL writes bypass API validation, but malformed stored grids are rejected by the timetable solver and independent validator. No automatic cleanup or migration of existing data was attempted.

Validation and transaction behavior were exercised with isolated SQLite only; PostgreSQL row-lock concurrency was not integration-tested against a live server. The existing model has no persisted grid-duration setting, so changing an entire established grid's duration requires a separate deliberate workflow. Publication/version immutability remains B004. No claim is made that unrelated SRS requirements are complete. B003 was not started.
