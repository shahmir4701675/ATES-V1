# ATES bug register

21 November 2026 (Asia/Karachi). Audit only. **20 grouped findings:4 Critical,14 High,2 Medium.** A grouped finding may cover several related symptoms;27 failed tests are not27 independent bugs. Static inferences are explicitly identified. Tests use isolated SQLite or in-memory engine data; none reproduce against production.

## B001 - Critical: Unauthenticated and spoofed-role access permits writes

- Location: backend/dependencies.py:69-133.
- Requirements: FR-1.5; SEC-1/3.
- Evidence: test_unauthenticated_write_requires_login; test_forged_role_is_not_authentication.
- Reproduction/finding: POST /rooms without a token returns201; X-User-Role:Administrator also returns201. Defaults adapt roles to each route; X-User-Id is trusted.
- Impact: Any caller can change scheduling data and impersonate actor IDs.
- Required action (not implemented): Verify JWT/session; load active user and roles from trusted storage; reject missing identity.

## B002 - Critical: Generated timetable can contain simultaneous instructor, room and batch clashes

- Location: backend/routers/master_data.py:1201-1243; engine/constraints.py:126-293.
- Requirements: C-6; H01-H03; FR-6.3.
- Evidence: test_weekly_slot_overlap_rejected; test_unequal_slot_length_rejected; test_solver_rejects_overlapping_clock_slots.
- Reproduction/finding: API accepts overlapping weekly slot201. A two-slot engine dataset with both windows08:00-09:00 returns optimal, two entries for instructor1/batch1/room2 and validator[].
- Impact: A schedule advertised as conflict-free can double-book all three resources in actual clock time.
- Required action (not implemented): Reject overlapping/irregular grids and independently check real temporal overlap.

## B003 - Critical: Mixed explicit and inferred exam enrollments miss required conflict edges

- Location: engine/models.py:523-550; engine/exam_scheduler.py:141-184; engine/constraints.py:1850-1866.
- Requirements: A-4; E01/E02; FR-7.1/7.3.
- Evidence: test_mixed_enrollment_fallback_has_cohort_conflict.
- Reproduction/finding: Take two same-batch offerings; fully enumerate students for one and leave the other unenumerated. First course has student:* identities; second has batch:* only. Graph edge is absent.
- Impact: Under A-4 the same real cohort can be assigned clashing exams; validator uses same flawed membership helper and will miss the same overlap.
- Required action (not implemented): Represent inferred membership using known batch students plus conservative cohort relations; test mixed, partial, repeater and elective data.

## B004 - Critical: Published timetable can be invalidated through master-data updates

- Location: backend/routers/master_data.py:801-839,1298-1329; backend/adapter.py:106-455.
- Requirements: SAF-1/4; H04; FR-9.2.
- Evidence: test_generated_schedule_immutable_through_master_data.
- Reproduction/finding: In isolated fixture mark schedule1 Published with approval metadata, PUT /rooms/1 capacity1 returns200. Reloading that published version produces H04 violations. Direct entry edits correctly return409.
- Impact: The published schedule ceases to satisfy hard constraints without new generation, validation or approval; historical views use mutable master data.
- Required action (not implemented): Snapshot immutable version inputs or block/version invalidating metadata changes and revalidate authoritative publication.

## B005 - High: Lab validator accepts clock-time gaps as consecutive

- Location: engine/constraints.py:723-768,796-813.
- Requirements: H09; C-6.
- Evidence: test_lab_contiguity_uses_clock_time.
- Reproduction/finding: Keep lab slot indexes consecutive but change final lab slot to18:00-19:00; validator returns[].
- Impact: An hours-long lab interruption passes hard validation.
- Required action (not implemented): Require previous end_time==next start_time for every lab block; validate grid topology.

## B006 - High: Unpublished and other-batch schedules exposed; Administrator permitted scheduling

- Location: backend/routers/schedules.py:343-378,505-585,391; frontend/src/pages/TimetablePage.tsx:40-59.
- Requirements: SEC-10; FR-9.4/10.5; SRS2.3.
- Evidence: test_student_cannot_read_generated_schedule; test_student_list_contains_published_only; test_administrator_cannot_generate.
- Reproduction/finding: Student with X-Batch-Id1 reads Generated schedule with 26 entries; list shows Generated; Administrator generation returns202. Pages initialize all scopes.
- Impact: Disclosure of drafts/other cohorts and violation of stated separation of duties.
- Required action (not implemented): Enforce status/ownership at list/detail/entries/export; Coordinator generates, Approver publishes, Administrator administers.

## B007 - High: Unlinked Faculty can edit any instructor availability

- Location: backend/routers/master_data.py:640-688.
- Requirements: FR-3.1; SEC-3.
- Evidence: test_faculty_without_identity_cannot_edit_any_instructor.
- Reproduction/finding: X-User-Role:Faculty with no instructor link PUT instructor2 availability returns200. Read route also lacks own-scope guard.
- Impact: Faculty can alter another instructor input.
- Required action (not implemented): Require trusted non-null Faculty link and scope read/write to it.

## B008 - High: Publication and archiving only exist in browser overlay

- Location: frontend/src/services/api.ts:313-323; frontend/src/pages/ReviewPublishPage.tsx:34.
- Requirements: FR-9.1-9.6; UC-13; SAF-1.
- Evidence: test_required_endpoint_exists[post-/schedules/1/publish-payload5].
- Reproduction/finding: Publish route404. publishOverlay sets Published and prior Archived in a Map; refresh/new client loses state and no Approver server check executes.
- Impact: Users may believe a version is official while database still says Generated.
- Required action (not implemented): Implement transactional Approver publish/archive with independent live validation.

## B009 - High: CSV import validates mock records and can report inserts it never performs

- Location: frontend/src/services/api.ts:325-333; frontend/src/services/mockApi.ts:307-368.
- Requirements: FR-4.1-4.5; UR-12.
- Evidence: POST /import/courses404 executed; remaining behavior static inspection.
- Reproduction/finding: Real-mode import still calls mock.validateImport/confirmImport. confirmImport has only course/instructor/room/batch insert branches but reports job.rows.length for offerings/enrollments.
- Impact: No imported records reach authoritative database; offering/enrollment imports can report false success even in mock mode.
- Required action (not implemented): Implement staged server validation/confirmation, complete FK checks and truthful counts.

## B010 - High: Schedule PDF/CSV export buttons have no download behavior

- Location: frontend/src/components/ui.tsx:87-89; frontend/src/pages/TimetablePage.tsx:72; frontend/src/pages/ExamSchedulePage.tsx:54.
- Requirements: FR-11.1-11.5; UC-16.
- Evidence: Both export endpoint probes return404; buttons statically traced.
- Reproduction/finding: Both schedule pages use ExportActions, whose callbacks only emit status text. ConflictReportPage has a distinct real client CSV download.
- Impact: Users cannot produce required schedules for printing/distribution.
- Required action (not implemented): Add authorized PDF/CSV exporters, metadata/filters and audit events.

## B011 - High: Login/accounts/audit screens simulate security without server persistence

- Location: frontend/src/services/mockApi.ts:373-391; frontend/src/App.tsx:59-79; frontend/src/services/api.ts:335-338.
- Requirements: FR-1.x; FR-12.2; SEC-1/2/4.
- Evidence: Auth/users/audit endpoint probes404; static mock login check.
- Reproduction/finding: Known mock username plus any nonempty password succeeds; saveUser discards password. UI starts as Administrator and allows arbitrary role switching; no logout/password lifecycle.
- Impact: Prototype identity and security records cannot establish a real authenticated session.
- Required action (not implemented): Replace security mocks with authenticated server workflows, bcrypt>=12, expiry and lockout.

## B012 - High: Cancellation, total deadlines and process isolation are incomplete

- Location: frontend/src/services/api.ts:205-226; backend/routers/schedules.py:473-480; engine/exam_scheduler.py:471,614-688,1150,1364; engine/timetable_solver.py:883-936.
- Requirements: C-4; P-2/3/8; FR-6.5/6.6.
- Evidence: Static control-flow finding; no stress benchmark executed.
- Reproduction/finding: Cancel stops UI following only. BackgroundTasks is same-process execution; repeated5s room/diagnostic solves and unconstrained backtracking exceed a single global deadline; timetable diagnosis adds2s/rule.
- Impact: Run may continue after cancellation and consume shared resources beyond stated budget.
- Required action (not implemented): Use a cancellable process worker and shared monotonic deadline covering preflight/build/search/diagnostics/validation.

## B013 - High: Default production app skips startup recovery of orphaned runs

- Location: backend/main.py:96-109; backend/dependencies.py:38-55.
- Requirements: SRS4.3.2; Q-02.
- Evidence: test_default_app_recovers_orphan_on_startup.
- Reproduction/finding: create_app() has no factory at lifespan start; factory is initialized by first request after recovery phase. Isolated patched engine probe leaves status Generating.
- Impact: Restarted runs remain indefinitely Generating in default deployment.
- Required action (not implemented): Initialize configured engine/session factory before startup recovery and test default entrypoint.

## B014 - High: Backend regeneration never supplies previous timetable to S05

- Location: backend/routers/schedules.py:261-296; engine/timetable_solver.py:1002-1004.
- Requirements: S05; FR-6.4.
- Evidence: Static call tracing; direct-engine S05 test passes.
- Reproduction/finding: Worker discards all unlocked previous entries and calls solve_timetable without previous_schedule/previous_entries; S05 obtains empty list.
- Impact: Configured schedule-stability preference silently does nothing in real API regeneration.
- Required action (not implemented): Pass complete previous timetable to objective separately from mandatory locked entries.

## B015 - High: Manual adjustment workflow lacks state/block/lock/override completeness

- Location: backend/routers/schedules.py:673-681,859-903; backend/models.py:920-966; frontend/src/pages/TimetablePage.tsx:96; frontend/src/pages/ExamSchedulePage.tsx:23-28.
- Requirements: FR-8.3/8.5/8.6/8.7; FR-6.10.
- Evidence: test_exam_manual_override_persisted; static UI/state inspection.
- Reproduction/finding: Only Published/Archived forbidden; Generated-only rule not enforced. Multi-slot Move disabled; no lock/unlock UI; exam room selector/override persistence and undo absent.
- Impact: Core adjustment and repeatability workflow cannot be completed through UI; exam override history lost.
- Required action (not implemented): Atomic lab-block/exam room moves, Generated-only guard, persisted override flags, lock controls and undo snapshot.

## B016 - High: Audit, schema lifecycle and database enforcement incomplete

- Location: backend/models.py:678-716,1096-1125; backend/database.py:170-174; db/schema.sql.
- Requirements: DB-5/7/9; FR-12.1-12.3; SEC-9.
- Evidence: Runtime metadata inventory; room mutation audit probe fails.
- Reproduction/finding: ORM metadata is missing leading FK indexes; schema.sql already defines those indexes and log/overlap/capacity/published-entry triggers, but create_all omits SQL-only definitions. No versioned migrations; ordinary room creation has no audit event; mandatory security services absent.
- Impact: Poor accountability, migration reproducibility and incomplete integrity guarantees.
- Required action (not implemented): Reconcile existing SQL-only indexes/triggers with ORM-created databases through tested migrations; complete trusted audit services and verify installed PostgreSQL grants.

## B017 - High: Malformed time/grid input returns500 or misleading409

- Location: backend/schemas.py:238-281; backend/routers/master_data.py:125-133,1251-1291.
- Requirements: SEC-6; Q-11; FR-2.7.
- Evidence: test_bad_time_returns_validation_error; test_grid_over_midnight_returns_validation_error; test_invalid_day_returns_validation_error.
- Reproduction/finding: not-a-time produces500;23:00 two-hour grid produces500; working_days[8] returns409 described as existing grid overlap.
- Impact: User cannot distinguish validation failure from server failure; robustness requirement violated.
- Required action (not implemented): Use typed time/domain validators and precise422 messages before constructing or committing rows.

## B018 - High: Generation lacks snapshot/concurrency guarantees for versions and saving

- Location: backend/adapter.py:457-465,534-589; backend/routers/schedules.py:239-304,450-461.
- Requirements: FR-6.7/9.5; DB-6; SAF-1/2.
- Evidence: Static race analysis; not reproduced under concurrent load.
- Reproduction/finding: Next version uses max+1 without serialization/retry; data is loaded then session closed before solve, later save does not revalidate against current data. Config/master changes may occur in between.
- Impact: Concurrent runs can collide with unhandled UNIQUE failure; stale input can yield a Generated version invalid against current data.
- Required action (not implemented): Atomically allocate versions, snapshot/hash inputs, reject stale results or validate under save-time consistency guarantees.

## B019 - Medium: Configuration deletion is local and parameters lack domain validation

- Location: frontend/src/services/api.ts:298-310; backend/schemas.py:348-353; backend/routers/master_data.py:1866-1900.
- Requirements: FR-5.4/5.6/5.8.
- Evidence: Static service/schema inspection.
- Reproduction/finding: Deletion only hides ID in a Set; arbitrary negative param_value and unknown rule code/type accepted by schema/service.
- Impact: Configuration may reappear or advertise a rule the engine does not enforce.
- Required action (not implemented): Implement persistent delete and catalogue-specific validation.

## B020 - Medium: UI role, layout, localization and documentation remain incomplete

- Location: frontend/src/components/ui.tsx:45-50; frontend/src/pages/DashboardPage.tsx; frontend/src/pages/TimetablePage.tsx:75-96; frontend/src/data/reference.ts:4; docs/.
- Requirements: FR-10.x; UI standards; DB-8; SRS2.6/5.3.
- Evidence: Static inspection; no visual/cross-browser/accessibility execution.
- Reproduction/finding: All-batch parallel timetable entries share CSS grid cells; explicit term selector absent; dashboard actions not role-scoped; error IDs missing; local timezone rather than explicit Karachi; documentation and resource extraction incomplete.
- Impact: Unverified mobile/accessibility behavior and confusing scope/navigation/display.
- Required action (not implemented): Finish role-specific UX, rendering, explicit timezone/resources/help and execute browser/contrast tests.

## Evidence limits

No browser screenshots/workflows, external PostgreSQL, deployment TLS/grants, destructive operations, load tests, backup restores or production penetration tests were executed. Browser/source findings do not imply a live click was tested. See final_audit_probes.xml/log for final actual assertions, direct_tests.xml/log for supplied tests, frontend_checks.log for compile/bundle results and source_manifest.json for inspected-file hashes. Two initial probe fixture setup failures were corrected only in audit_reports; their superseded failures are not application bugs.
