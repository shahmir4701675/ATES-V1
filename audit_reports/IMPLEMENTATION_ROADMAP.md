# ATES implementation roadmap

21 November 2026 (Asia/Karachi). This is a proposed remediation plan only. **No application code, feature or bug fix was implemented during the audit.** The six phases preserve the requested priority order. Critical security issues are included in phase1 because they are already critical bugs; phase4 covers remaining security/data-integrity work.

## Current baseline

228 traceability items:38 full,110 partial,22 missing,44 incorrect,14 unverified. Strict verified-assessment compliance17.76% (38/214); primary FR compliance19.51% (16/82).107 final pytest cases:80 passed,27 failed; existing79 all pass; added 28 expose27 failures. Three frontend compile/build checks pass. Bug register has4 Critical,14 High and2 Medium grouped findings. These are prototype evidence, not institutional acceptance.

## Phase1 - Critical bugs and hard-constraint violations

Sequence these as release blockers:

1. **B001 authentication/permission bypass:** reject anonymous callers, authenticate server-side identity, eliminate authority from caller-supplied role/ID/link headers, reject inactive/locked accounts. Establish minimal trusted identity before any shared/deployed operation.
2. **B002 weekly grid and true physical clashes:** enforce equal slot duration, nonoverlapping windows and ordered valid weekday/index topology. Independently reject overlapping real-time resource intervals in generated and adjusted schedules. Preserve mandatory H01-H03/H08 regardless of config.
3. **B003 mixed exam enrollment membership:** unify complete explicit enrollment, partial elective/repeater links and missing-data cohort fallback under A-4. Ensure a missing-enrollment offering includes known students of the inferred cohort and daily limits count each real student consistently. Use an independent oracle to avoid a shared-helper blind spot.
4. **B004 published integrity:** choose immutable per-version input snapshots or restrictive version-aware master/config updates. An old published version must remain semantically stable and hard-valid; new results must be rejected if solve inputs are stale. Publication must revalidate against the authoritative chosen snapshot.
5. **B005 lab adjacency:** require same day, same room, consecutive indexes and adjacent clock windows; make API/grid validator and solver agree. Add atomic block movement preconditions.

**Exit evidence:** all applicable existing tests retained; new overlapping-clock and lab-gap/mixed-enrollment/published-metadata regression cases pass with independent expected results. Default/public caller cannot mutate data; no enabled hard-invalid schedule reaches Generated or Published. Add negative fixtures for every hard rule under adversarial input, not just valid weekly grids. A partially passing audit suite does not clear this gate.

## Phase2 - Missing mandatory SRS requirements

1. Complete secure login/logout, JWT expiry after30 minutes inactivity, bcrypt cost>=12/password minimum8, five failures/15-minute lockout, password change/reset, account activation/deactivation and instructor/batch links (FR-1.x; SEC-1/2/4). Bind actor identity to audit events.
2. Implement server multipart CSV upload for all six types,<=10MB UTF-8 parsing, staged row/column/reason reporting, all FK/range/duplicate checks, valid-only import or cancellation, atomic persistence and accurate ImportLog. Test5000-row inputs after functional correctness.
3. Implement Generated-only Approver publication with fresh independent validation, one-Published-per-term/type atomic archive/publish, approved_by/published_at/audit, archive view and duplicate-to-new-draft. Define all SRS state transitions, including term close and failed preflight.
4. Implement real authorized schedule CSV and A4 landscape PDF exporters, displayed filters/metadata, multi-batch/instructor pages and export audit. Render and inspect produced PDFs; test actual download bytes/content types.
5. Add actual process-worker cancellation and bounded run status. Do not report cancellation until server acknowledges stopped/cancelled state. Complete schema migrations and operational/user documentation required for release; dependency/license notices and documented templates are deliverables, not inferred from source files.

**Exit evidence:** required auth/users/import/publish/export/audit resources no longer404; multi-client/reload roundtrips persist state; full user journeys use the database; PDF/CSV files contain exactly authorized filtered records. Reference docs and quick-start can be followed on a clean setup. Removed mocks cannot silently remain active for mandatory workflows.

## Phase3 - Broken backend/frontend integrations

1. Replace login/users/audit/import/publish/config-delete mocks in real mode with completed live services. Remove unrestricted role switch and default Administrator session. Unify numeric real user/instructor/batch IDs; enforce own scope in backend and default filters in UI.
2. Pass full previous timetable into S05 objective while supplying locked entries separately. Exercise this through the real API, not only direct-engine tests.
3. Complete Generated-only manual adjustment state guards, atomic multi-slot lab moves, exam room reassignment, persistent exam override markers, lock/unlock UI and undo snapshot workflow. Distinguish locks from overrides.
4. Fix default app startup: initialize database/session factory before interrupted-run recovery. Exercise backend.main:app lifespan and first request rather than calling helper alone.
5. Use atomic term activation; implement persistent unused-config delete; match requested schedule type to config explicitly. Ensure refreshing/reopening shows the same publication/archive/config state.
6. Make health/errors truthful: unknown conflict health remains unknown; errors cannot become a zero-conflict success banner. Add explicit term-scoped version selection and contextual navigation to newly generated version.

**Exit evidence:** a clean browser can log in, enter/import data, configure, generate, inspect failures, adjust/lock, regenerate, review/publish and export with persistent state. A second browser/user sees the authoritative status. Faculty and Student own views show only allowed Published rows; Approver cannot alter master data; Administrator cannot generate or approve. No status-only button claims a completed download or cancellation.

## Phase4 - Remaining security and data integrity

1. Extend trusted role and ownership checks to every alias, list/detail/status/entries/conflict/export/availability/enrollment endpoint; never trust identity query/body/header values. Use trusted request user for created_by/generated_by and audit actors.
2. Replace unparsed time strings/unchecked day lists with domain validation; validate rule catalogue/type/parameter bounds, active references and cross-term relationships. Return precise422/409 responses and consistently roll back errors.
3. Introduce versioned schema migrations and dual PostgreSQL/SQLite checks. Reconcile SQL-only guards/indexes with ORM-created databases through migrations. The following leading FK indexes exist in schema.sql but are missing from ORM metadata: schedules.generated_by/approved_by, exam_entries.course_id, timetable_entries.instructor_id/batch_id/room_id. Enforce immutable append-only audit/import policies and complete mandatory event coverage.
4. Allocate schedule versions safely under concurrency; use input snapshot IDs/hashes and consistency checks at save/publish; test update-after-load and concurrent-generation races. Keep historical metadata/config meaning stable.
5. Verify deployment HTTPS redirect/refusal, TLS>=1.2, encrypted DB connections, minimal application DB privileges and secrets management without publishing credentials. Confirm daily backups with last7 retained and execute a disposable restore verification.

**Exit evidence:** negative authorization/ownership matrix; malformed-input tests; concurrent/stale-input cases; append-only/grant checks; migrations on both engines; TLS/backup/restore evidence. These must run on disposable targets, never production data.

## Phase5 - Performance

1. Apply one monotonic end-to-end run deadline including input load/build/DSATUR mapping/room allocation/fallback/diagnostics/validation. Honor cancellation in every phase. Correct runtime accounting and distinguish heuristic feasible results from proved optimal results.
2. Benchmark A-1 reference data (up to40 batches,150 offerings,80 instructors,60 rooms,48 weekly slots,3000 students,80 exam courses). Fix seed/reference reproducibility and record hardware/dataset/hash/config/solver status.
3. Measure all SRS P targets: ordinary request p95<=2s at50 users; timetable configured limit/typical60s; exams<=30s; manual move<=1s;5000-row import<=15s; single export<=5s/all-batch PDF<=30s; schedule-view queries<=500ms; generation interference<=20% with isolated worker.
4. Inspect query plans/counts and remove avoidable per-entry ORM lookups; push permitted filters/paging to SQL where appropriate. Bound API/generation concurrency and evaluate doubled-size300-offering/120-room scenario.
5. Run repeated valid-input generations for the99% reliability target and monitor monthly working-hours availability99%. Passing small unit fixtures cannot satisfy these targets.

**Exit evidence:** versioned reference dataset, benchmark commands/raw distributions/query plans, independently validated outputs, deadline/cancel measurements, paired concurrency baseline and repeatable comparison. Set regression thresholds only after measurement.

## Phase6 - UI/UX improvements

1. Finish accessible labels/tooltips/error IDs, focus/keyboard navigation and clear summaries; verify WCAG2.1AA contrast across states. Use severity icon/text in the fixed status area.
2. Verify every screen at360px and common desktop widths with realistic record counts and four supported browsers. Correct parallel-grid session overlap, lab timing presentation, pagination/filter controls and empty/loading/error behavior.
3. Provide role-appropriate dashboard actions, own default views, explicit term/version selection, confirmation consequence text and accurate progress/cancellation/export messages. Add requested drag-and-drop only with the same server atomic validation as dialogs.
4. Extract interface strings to resource files; use24-hour local times and explicit Asia/Karachi for event timestamps; support configurable first weekday and Unicode/Urdu names. Test UTF-8 roundtrip.
5. Deliver screenshot-based role manuals, two-page quick-start, per-screen help, field explanations/templates and installation/admin guide. Run timed Coordinator (<15-minute dataset-to-timetable) and Faculty/Student (own schedule<=2clicks) usability studies.

**Exit evidence:** browser screenshots/test recordings and accessibility/contrast results, functional downloads/persistent actions, timed usability results and complete documentation. Do not label a UI control complete from its appearance or build success alone.

## Release decision

Treat the current branch as a controlled development/demo prototype. Resolve all critical findings before any shared deployment; complete mandatory workflows and prove zero enabled hard violations before institutional approval/publication. Then require both databases, reference-size performance, role privacy, failure/cancellation/restart integrity, PDF/CSV acceptance, backup restore and user acceptance evidence. Recompute the traceability matrix from new evidence rather than marking the roadmap itself as implementation. No duration or completion estimate is asserted without implementation scope and staffing confirmation.
