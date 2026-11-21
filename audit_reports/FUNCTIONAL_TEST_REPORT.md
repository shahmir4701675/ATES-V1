# ATES functional and testing assessment

Audit date:21 November 2026 (Asia/Karachi). Existing application code was not edited. This report distinguishes successful execution from static inspection and unverified behavior.

## Executed results

- Supplied pytest suite: **79 executed,79 passed,0 failed**,114.70 seconds. Backend API10, database12, exam scheduler13, timetable solver25, validator19.
- Final audit probes: **28 executed,1 passed,27 failed**,16.09 seconds. The passing added case verifies Published entry-edit rejection. Failed assertions test expected safe/SRS behavior and therefore reveal noncompliance; they are not expected-success security demonstrations.
- Combined distinct final pytest cases: **107 executed,80 passed,27 failed**. No final test errors or skips. This total counts each final case once, not every retry/invocation. It is not a requirements coverage percentage.
- Frontend checks: **3 executed,3 passed**: application TypeScript, tooling TypeScript, isolated Vite production build. These are separate from107 pytest cases.
- Runtime inventory/OpenAPI generation succeeded and enumerated21 ORM tables and32 documented API paths. These read-only diagnostics are not counted as extra pytest cases.

Final evidence: direct_tests.log/xml, final_audit_probes.log/xml, frontend_checks.log, runtime_inventory.json and test_results.json. Full pytest names/results are listed below.

## Execution safety and commands

Tests used the already-installed .venv Python3.13.2, pytest9.2.0, OR-Tools9.15.6755, NetworkX3.7, SQLAlchemy2.1.8, FastAPI0.162.2, Uvicorn0.54.0 and httpx0.28.1. The supplied fixtures explicitly create local temporary SQLite databases; audit fixtures create sqlite:///:memory: and seed only that engine. No configured .env values were read by audit probes, and no remote database was contacted. Existing env-loading tests monkeypatch only their own process and write a temporary test .env, which pytest restores. No user environment/configuration/credentials were edited.

Commands ran from repository root:

~~~powershell
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --junitxml=audit_reports/direct_tests.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py audit_reports/test_extra_probes.py -p no:cacheprovider -v --junitxml=audit_reports/final_audit_probes.xml
node frontend/node_modules/typescript/bin/tsc --project frontend/tsconfig.app.json --noEmit --incremental false
node frontend/node_modules/typescript/bin/tsc --project frontend/tsconfig.node.json --noEmit --incremental false
node frontend/node_modules/vite/bin/vite.js build frontend --outDir <absolute-repository-path>/audit_reports/frontend_build
~~~

The existing suite's first PowerShell-launched attempt was interrupted during startup; a direct child-process invocation completed the79-case suite. Initial added probes had two invalid Published fixture setups because the database correctly requires approved_by and published_at; only audit fixtures were corrected. The final28-case run uses valid approval metadata and completes without fixture errors. Partial audit_probes.log/extra_probes.log and superseded audit_probes_initial.log/xml are diagnostic attempts, not authoritative counts. Use final_audit_probes.* for the final result. Source checks were not broadened after final success except to resolve these concrete audit-evidence issues.

The build output is under audit_reports/frontend_build, leaving frontend/dist intact. Vite warned that output was outside its project root and would not be emptied; build completed successfully. The supplied tests emitted Starlette deprecations for TestClient/httpx and an HTTP422 constant; no packages were installed to address them. The actual package build script was not run because tsc -b may write incremental metadata and vite build would replace frontend/dist; equivalent app/tooling checks and a safely redirected bundle were run instead.

## What supplied passing tests establish

- Normal seed timetable generation with 26 persisted entries; input-defect and deliberately infeasible results; ordinary H01-H10 violations/toggles, mandatory rules, locks, deterministic seed, solver validator rejection.
- Weighted S01-S06 objectives and score breakdown, optional rules and extensible constraint interface on small controlled fixtures.
- Conflict graph and DSATUR, ordinary student conflicts/daily exam limits, room capacity/collision, CP-SAT fallback success/failure, ES01-ES03 preferences and locked exams.
-21-model expected-column and SQL table-name checks, FK restriction/cascade, ordinary CHECK/UNIQUE constraints, composite offering FK, adapter loading, generation persistence and rollback.
- Master CRUD subset, availability, term grid/exam-overlap validation for normal inputs, config mandatory-rule protection, CORS origin behavior, generation/status/entries/conflicts, valid/invalid manual moves, explicit-header role rejection and recovery helper behavior.

They do **not** establish secure authentication, correct caller identity, authorization without forged headers, default-entrypoint startup recovery, full input topology, authoritative publication/import/export, reference-size performance, browser usability or production PostgreSQL correctness. The test called role_check_readiness explicitly expects unauthenticated operation; passing that test is evidence of the prototype milestone, not SRS-compliant authentication. Likewise the startup test calls the recovery helper directly; the additional default-app lifecycle probe fails.

## Frontend screen and workflow inventory (static inspection)

Every source page, shared shell/forms and service boundary was inspected. These statements describe source wiring, not executed browser clicks.

| Screen / routes | Actual wiring and controls | Findings / verification limit |
|---|---|---|
| Login /login | LoginPage -> loginMock -> mock.login | Any nonempty password for known mock username; no JWT/session/logout/password change; default app already privileged. |
| Dashboard / | Live terms/schedules/counts/conflicts through getDashboardSummary | Errors loading conflicts are converted to empty arrays, potentially presenting healthy status without evidence; Generate/conflict actions not scoped by role. |
| Master Data /data | Tabs Courses, Instructors, Rooms, Batches, Terms/Slots, Offerings, Enrollments; live CRUD | DataTable search/sort/paging default 25, edit/confirm dialogs and field errors exist. Term activation is two requests; offering deactivation absent; enrollment selection relies on inconsistent mock users. Complete real-browser behavior unverified. |
| Import /import | Browser templates, local CSV parse/validation and confirmImportMock | Does not write live DB in real mode. Offering/enrollment confirm reports imported rows without inserting even in mock. Validation has incomplete references. |
| Availability /availability and /teaching | Live grid and saveAvailability | Coordinator selection and Faculty link UI exist; Faculty server ownership bypass; warning says regenerate for changes. /teaching renders availability rather than own timetable. |
| Constraints /settings | Live configs/rules/create/clone and exam session creation | Hard disable confirmation exists. Delete only hides in browser; rule/parameter validation incomplete. Session editor adds sessions; update/delete routes not implemented. |
| Generate /generate | Live request, immediate and2s polling, elapsed/time-limit progress | Cancel only stops UI following; progress is share of limit, not measured solver progress. Reset available during run; no worker cancellation. |
| Timetable /timetable and /my-schedule | Live entries, numeric/string/day adaptation, weekly grid, filters/version, move dialog | Own-user defaults/published-only absent; explicit term selector absent; no drag-and-drop handlers; multi-slot lab Move disabled; no lock/unlock controls. Parallel all-batch entries may overlap in identical CSS cells (static inference). |
| Exams /exams | Live date-sorted exams, room/seat counts, date/batch/course/room filters, session Move | Own-user scope absent; room move UI absent; no lock/unlock controls; exam override flag not persisted. |
| Conflicts /conflicts | Live conflicts, type/severity filters, local CSV Blob download | This CSV export is real source wiring; it is distinct from nonfunctional schedule CSV buttons. Browser download not executed. |
| Review/Publish /approvals | Live summary/selection/conflicts; publishScheduleMock | Client-only Published/Archived overlay, no server publication/validator/approver gate. Reload loses publication. |
| Users and Audit /users | getUsersMock/saveUserMock/getAuditLogMock, UI filters | Live master lists coexist with mock account IDs/security history; no authoritative users/audit endpoints. Passwords discarded by mock save. |
| PlaceholderPage | Fallback component with obsolete planning copy | Major valid routes map to real page components, so the presence of this file does not establish that their routes are placeholders. Unrecognized URL normalizes to dashboard. |

Shared Modal implements focus-management hooks, DataTable sorting/search/page controls, LoadState/Notice/ErrorSummary and responsive styles. These are positive static findings. Field error aria-describedby IDs are not rendered on corresponding error containers. Tooltip presence, contrast, focus order, screen-reader behavior, touch,360px layout, every button and browser compatibility were **not** verified by execution. Schedule ExportActions only emits notifications and does not invoke print/download. No drag/drop event handlers or undo/lock controls were found in the active timetable/exam pages.

## Endpoint integration assessment

Live documented method/path inventory is runtime_inventory.json. Required probes found404 for POST /auth/login, POST /auth/logout, GET /users, GET /audit, POST /import/courses, POST /schedules/1/publish and GET /schedules/1/export in both PDF/CSV formats. Root/API-prefixed aliases do not add missing capabilities. DELETE /configs/{id}, schedule cancellation, draft duplication and undo are also absent by route inspection. GET /health returns a static OK and does not prove database/worker readiness.

Malformed time produces500, midnight grid overflow500, invalid day409 with a misleading overlap message; overlapping/unequal slots201. No source exception fixes were applied. See B001-B020 for impact and actions.

## Not executed and why

- Browser end-to-end/screenshot/mobile/cross-browser/accessibility: no isolated browser/backend session was established. The default frontend points at localhost:8000 and the default backend may resolve the configured database; the audit did not launch that deployment or interact with its data. This is an explicit assessment limit, not a claim those tools are inherently unavailable. Source inspection and compile/build success cannot substitute for these tests.
- PostgreSQL/Supabase, deployment TLS/DB grants/backups: no disposable PostgreSQL target or deployment evidence was provided; the configured target was deliberately not connected to. No migrations, seed command against .env, production writes or restore drills ran.
- Reference-size/concurrent/load/reliability/uptime: supplied fixtures are much smaller than A-1. No150-offering/3000-student or50-user benchmark,100-run reliability sample, doubled-size scale test or monthly uptime observation ran. Recorded fixture runtimes are not P-1 through P-8 acceptance results.
- Coverage>=70%: no coverage campaign/result produced;79 passing tests do not prove a percentage. No missing dependencies were installed.
- PDF/CSV acceptance: required schedule services absent; no generated application schedule PDF was visually verified. The retained PNGs render the SRS source only.

## Final per-case execution ledger

### Supplied suite

#### tests.test_backend_api

- PASS test_cors_allows_react_dev_server_only
- PASS test_role_check_readiness_enforces_roles_when_header_present
- PASS test_master_data_crud_courses_instructors_rooms_batches
- PASS test_master_data_terms_slots_exam_slots_offerings_and_configs
- PASS test_post_schedules_generate_creates_generating_row_and_runs_worker
- PASS test_post_schedules_generate_exam_schedule_end_to_end
- PASS test_post_schedules_generate_infeasible_persists_conflicts
- PASS test_put_schedule_entry_valid_move_and_409_on_violated_timetable_constraints
- PASS test_put_schedule_entry_exam_validation_409_and_valid_move
- PASS test_startup_recovery_marks_interrupted_generations_as_infeasible

#### tests.test_backend_db

- PASS test_env_example_and_gitignore_security_compliance
- PASS test_database_url_loading_and_normalization
- PASS test_all_21_models_match_schema_sql
- PASS test_seed_database_loads_master_data_students_and_enrollments
- PASS test_seed_cli_entrypoint_with_local_sqlite
- PASS test_db2_composite_foreign_key_and_db4_clash_constraints
- PASS test_db3_restrict_master_delete_and_cascade_schedule_delete
- PASS test_partial_unique_indexes_and_check_constraints
- PASS test_adapter_loads_term_and_validates_seeded_schedules
- PASS test_adapter_solves_and_saves_timetable_and_exam_results_in_one_transaction
- PASS test_adapter_saves_infeasible_results_and_logs_conflicts_without_harming_existing_schedules
- PASS test_saf2_and_db6_atomic_rollback_on_save_failure

#### tests.test_exam_scheduler

- PASS test_step1_build_conflict_graph
- PASS test_step2_dsatur_colouring_produces_valid_proper_colouring
- PASS test_feasible_seed_exam_dataset_scheduled_and_validated
- PASS test_overconstrained_exam_dataset_falls_back_to_cpsat_and_reports_shortfall
- PASS test_cpsat_fallback_succeeds_when_dsatur_colour_group_exceeds_room_or_daily_limits
- PASS test_infeasible_when_single_course_exceeds_total_exam_room_capacity
- PASS test_optional_constraint_e02_can_be_disabled
- PASS test_es01_soft_preference_spreads_batch_exams_across_different_days
- PASS test_es02_soft_preference_minimises_rooms_per_exam
- PASS test_es03_soft_preference_keeps_exam_rooms_in_same_building
- PASS test_exam_soft_breakdown_objective_score_and_ui_summary
- PASS test_exam_locked_sessions_are_preserved
- PASS test_exam_deterministic_seed_and_extensible_soft_constraint_interface

#### tests.test_timetable_solver

- PASS test_default_time_limit_constant
- PASS test_solve_seed_dataset_feasible_and_validated
- PASS test_solve_result_tuple_unpacking
- PASS test_solve_deliberately_infeasible_dataset
- PASS test_deterministic_seed_produces_identical_schedule
- PASS test_mandatory_constraints_always_enforced_even_if_disabled
- PASS test_optional_constraint_h04_capacity_toggle
- PASS test_optional_constraint_h05_room_type_toggle
- PASS test_optional_constraint_h06_availability_toggle
- PASS test_optional_constraint_h07_blocked_slot_toggle
- PASS test_optional_constraint_h09_lab_contiguity_toggle
- PASS test_optional_constraint_h10_workload_toggle
- PASS test_locked_sessions_are_preserved_in_new_run
- PASS test_validator_rejection_gate_discards_invalid_solution
- PASS test_input_completeness_check_reports_defects
- PASS test_soft_constraints_objective_breakdown_and_score_summary
- PASS test_s01_minimises_batch_idle_gaps_on_a_day
- PASS test_s02_spreads_offering_sessions_across_different_days
- PASS test_s03_keeps_batch_daily_sessions_at_or_below_parameter
- PASS test_s04_keeps_instructor_consecutive_teaching_slots_within_limit
- PASS test_s05_prefers_previous_schedule_slot_and_room_and_skips_when_none
- PASS test_s06_prefers_smallest_fitting_room
- PASS test_zero_weight_or_disabled_soft_constraints_are_ignored
- PASS test_soft_constraints_never_violate_hard_constraints_even_with_conflicting_previous_schedule
- PASS test_extensible_soft_constraint_interface_srs_4_3_5

#### tests.test_validator

- PASS test_valid_seed_schedule_has_no_violations
- PASS test_h01_instructor_clash
- PASS test_h02_room_clash
- PASS test_h03_batch_clash
- PASS test_h04_room_capacity
- PASS test_h05_room_type_mismatch
- PASS test_h06_instructor_unavailable
- PASS test_h07_blocked_slot
- PASS test_h08_session_count_mismatch
- PASS test_h09_lab_block_contiguity
- PASS test_h10_instructor_workload_exceeded
- PASS test_mandatory_constraints_cannot_be_disabled_in_validator
- PASS test_valid_seed_exam_schedule_has_no_violations
- PASS test_e01_student_exam_clash
- PASS test_e02_daily_exam_limit_exceeded
- PASS test_e03_exam_seat_allocation_exceeds_room_capacity
- PASS test_e04_exam_room_clash_in_session
- PASS test_e05_single_session_per_course_missing
- PASS test_mandatory_exam_constraints_cannot_be_disabled

### Final audit probes

| Test | Result | Observed evidence |
|---|---|---|
| test_unauthenticated_read_requires_login | FAILED | AssertionError: Unauthenticated GET /courses returned 200 assert 200 == 401  +  where 200 = <Response [200 OK]>.status_code |
| test_unauthenticated_write_requires_login | FAILED | AssertionError: Unauthenticated room creation returned 201 assert 201 == 401  +  where 201 = <Response [201 Created]>.status_code |
| test_forged_role_is_not_authentication | FAILED | AssertionError: Forged Administrator header returned 201 assert 201 == 401  +  where 201 = <Response [201 Created]>.status_code |
| test_student_cannot_read_generated_schedule | FAILED | AssertionError: Student read Generated schedule with 26 entries assert 200 in (401, 403, 404)  +  where 200 = <Response [200 OK]>.status_code |
| test_student_list_contains_published_only | FAILED | AssertionError: [{'schedule_id': 1, 'term_id': 1, 'config_id': 1, 'schedule_type': 'Timetable', 'version_no': 1, 'status': 'Generated', 'solver_status': 'optimal', 'objective_score': 128.0, 'run_seconds': 1.25, 'entry_count': 26, 'conflict_count': 0, 'hard_violation_count': 0, 'generated_by': 1, 'generated_at': '2026-10-20T09:15:00Z', 'approved_by': None, 'published_at': None}, {'schedule_id': 2, 'term_id': 1, 'config_id': 2, 'schedule_type': 'Exam', 'version_no': 1, 'status': 'Generated', 'solv... [+3 more lines; full report in element text] |
| test_faculty_without_identity_cannot_edit_any_instructor | FAILED | AssertionError: Unlinked Faculty edit returned 200 assert 200 in (401, 403)  +  where 200 = <Response [200 OK]>.status_code |
| test_administrator_cannot_generate | FAILED | AssertionError: Administrator generation returned 202 assert 202 == 403  +  where 202 = <Response [202 Accepted]>.status_code |
| test_required_endpoint_exists[post-/auth/login-payload0] | FAILED | AssertionError: POST /auth/login: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[post-/auth/logout-payload1] | FAILED | AssertionError: POST /auth/logout: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[get-/users-None] | FAILED | AssertionError: GET /users: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[get-/audit-None] | FAILED | AssertionError: GET /audit: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[post-/import/courses-payload4] | FAILED | AssertionError: POST /import/courses: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[post-/schedules/1/publish-payload5] | FAILED | AssertionError: POST /schedules/1/publish: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[get-/schedules/1/export?format=csv-None] | FAILED | AssertionError: GET /schedules/1/export?format=csv: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_required_endpoint_exists[get-/schedules/1/export?format=pdf-None] | FAILED | AssertionError: GET /schedules/1/export?format=pdf: 404 assert 404 not in (404, 405)  +  where 404 = <Response [404 Not Found]>.status_code |
| test_weekly_slot_overlap_rejected | FAILED | AssertionError: Overlapping slot accepted: 201 assert 201 in (409, 422)  +  where 201 = <Response [201 Created]>.status_code |
| test_unequal_slot_length_rejected | FAILED | AssertionError: Unequal length accepted: 201 assert 201 in (409, 422)  +  where 201 = <Response [201 Created]>.status_code |
| test_bad_time_returns_validation_error | FAILED | AssertionError: Malformed time returned 500 assert 500 == 422  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| test_grid_over_midnight_returns_validation_error | FAILED | AssertionError: Cross-midnight grid returned 500 assert 500 == 422  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| test_invalid_day_returns_validation_error | FAILED | AssertionError: Invalid day returned 409 assert 409 == 422  +  where 409 = <Response [409 Conflict]>.status_code |
| test_generated_schedule_immutable_through_master_data | FAILED | AssertionError: Published metadata mutated: HTTP 200; violations=['H04'] [+2 more lines; full report in element text] |
| test_lab_contiguity_uses_clock_time | FAILED | AssertionError: Nonadjacent clock-time lab accepted; violations=[] assert False  +  where False = any(<generator object test_lab_contiguity_uses_clock_time.<locals>.<genexpr> at 0x000001CA3ECBE260>) |
| test_mixed_enrollment_fallback_has_cohort_conflict | FAILED | AssertionError: Fully enumerated course and missing-enrollment course in same batch have no edge assert False  +  where False = has_edge(1, 2)  +    where has_edge = <networkx.classes.graph.Graph object at 0x000001CA3EF0C980>.has_edge  +    and   1 = CourseOffering(offering_id=1, term_id=1, course_id=1, batch_id=1, instructor_id=1, enrolled_count=45).course_id  +    and   2 = CourseOffering(offering_id=2, term_id=1, course_id=2, batch_id=1, instructor_id=2, enrolled_count=45).course_id |
| test_exam_manual_override_persisted | FAILED | AssertionError: Exam response/model cannot preserve manual override flag assert 'is_manual_override' in {'exam_entry_id': 1, 'schedule_id': 2, 'course_id': 1, 'course_code': 'CS-326', ...}  +  where {'exam_entry_id': 1, 'schedule_id': 2, 'course_id': 1, 'course_code': 'CS-326', ...} = json()  +    where json = <Response [200 OK]>.json |
| test_published_direct_edit_rejected | PASSED | Published entry update correctly rejected with409. |
| test_mutation_audit_written | FAILED | AssertionError: Room creation has no persistent audit event assert [] |
| test_solver_rejects_overlapping_clock_slots | FAILED | AssertionError: Solver returned optimal: [(1, 1, 1, 2), (2, 1, 1, 2)] in identical clock windows; validator=[] assert not True [+1 more line; full report in element text] |
| test_default_app_recovers_orphan_on_startup | FAILED | AssertionError: Default lazy app left status=Generating assert 'Generating' == 'Infeasible'      - Infeasible   + Generating |

Failure messages are excerpts; full assertion context is preserved in JUnit/log files. No passing claim is inferred solely from code presence.

## SQL versus ORM initialization qualification

The supplied schema test checks SQL table names and hard-coded ORM column sets. It does not execute or compare PostgreSQL trigger/index behavior. schema.sql defines the six indexes absent from runtime ORM metadata, immutable audit/import triggers, exam overlap/capacity triggers and Published/Archived entry protection. metadata.create_all does not install these SQL-only definitions. PostgreSQL installation was not tested. Treat initialization-path parity as a defect even though the supplied schema-shape test passes.
