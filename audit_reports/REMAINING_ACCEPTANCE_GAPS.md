# Remaining acceptance gaps

Assessment date: 2026-11-21. **Complete SRS/production acceptance is withheld.** These are audit findings and next actions, not authorization to implement changes or deploy. Existing 604 project /28 original-audit passes do not close the following criteria. See [complete register](FINAL_SRS_COMPLIANCE.md) and [executed measurements](FINAL_TEST_RESULTS.md).

## Release-blocking or material demonstrated gaps

| ID | Finding / status | Evidence | Acceptance criterion / recommended next action |
| --- | --- | --- | --- |
| G01 | Reference performance incomplete/incorrect: P-1/P-3 Incorrect; P-2 Partial | API p95 12.239s at50 authenticated users; default timetable timeout120.348s;80-course exam timeout30.225s and30.273s with zero-soft | Profile auth/snapshot loading, model/diagnostic work and serialization without weakening deadlines/constraints. Demonstrate reference timetable default weights, exams<=30s and ordinary-request p95<=2s on reproducible hardware; preserve cancellation/fencing. A zero-soft timetable at91.387s is not default success. |
| G02 | Exam solution quality metadata Incorrect; FR-7.7/ES01 Partial | Actual DSATUR result labelled optimal with a strictly better hard-valid ES01 alternative | Report heuristic feasible vs CP-SAT feasible vs proven optimal accurately; verify enabled preference behavior through API and independent comparison. Do not imply mathematical infeasibility from timeout. |
| G03 | Draft/preflight lifecycle Incorrect / missing subcriteria | Empty Planned-term generation accepted then Infeasible; Figure12 says input defects stay Draft | **Not implemented subcriteria:** full input-completeness report before solving; Draft create/duplicate/regenerate flow and permitted transition coverage. Preserve numbered history and independent validation. |
| G04 | Term close does not archive Published schedules; FR-9.1 Incorrect | Real API closes term while schedule remains Published | Atomically archive official schedules on term close, preserving history/approval/snapshots and testing both types/clients. Clarify FR-2.6 exactly-one Active vs schema at-most-one Active before enforcing institutional policy. |
| G05 | Conflict CSV export lacks persistent export event; FR-11.5/12.1 Partial | ConflictReportPage constructs a Blob and downloads without backend export request | Route export/audit through trusted server identity or add an authoritative audited download workflow; retain working CSV data and scope. Verify actor/action/version/filter details and failure rollback. |
| G06 | Remaining validation/master-data gaps; Partial | Malformed instructor email accepted201; referenced offering reassignment409; no deactivation flag | Validate email semantics; define safe version-aware future assignment revision. **Not implemented subcriterion:** deactivation alternative for referenced offerings. Do not remove historical composite FKs, mutate snapshots or weaken publication guards to allow edits. |

P-8 remains partial: the paired local trial mean slowdown18.84% meets20%, but p95 slowdown27.57% does not. Specify the aggregation, repeat under controlled loads and include the same50-user ordinary workload during solving. P-4 is partial because a reference lock-only validation is not a full lab/exam movement. P-6 lacks80-course exam output; P-7 measured one indexed entry query, not all schedule-view queries. Do not classify unexecuted tests as failures or passes.

## Browser, UI, documentation and localization acceptance

| Criterion | Status and exact unfinished acceptance |
| --- | --- |
| Five-role browser journeys | **Not Verified.** Browser kernel initialization failed twice before interaction. Execute real login/logout, admin accounts/audit, Coordinator CRUD/import/config/generation/cancellation/manual lab and exam moves/locks/undo, Approver review/publish/archive, Faculty own availability/Published schedule, Student own-batch Published schedule; check unauthorized links as well as hidden controls. |
| Persistence and messages in browser | **Not Verified.** Verify refresh/second-user state, selected term/version, export/download, error/empty/loading/progress/cancellation and terminal timeout vs infeasibility. Backend persistence was verified separately. |
| Mobile / browser compatibility | **Not Verified.** Execute360px and desktop interactions/overflow for current Chrome, Firefox, Edge and Safari. Source responsive classes are not proof. |
| WCAG acceptance | **Not Verified.** Keyboard tab order/escape/focus restore/dialogs, visible labels, screen-reader names/live statuses, colour-independent signals and AA contrast need actual rendered testing. Selected SSR label/error IDs do not establish WCAG compliance. |
| Complete resource extraction | **Partially verified.** Resource files exist; scan found447 static display JSX nodes/attributes across21 files outside resources (includes duplicates/brands; not a unique-string count). Full extraction, dynamic messages and pluralization inventory are unfinished. |
| Per-term first working weekday | **Not implemented subcriterion.** Calendar/grid day labels remain fixed; no persisted per-term week-start field/API/UI. Define safe behavior for historical frozen grid display. |
| Time zone | **Partially verified.** Frontend Karachi conversion has executed tests; human PDF generation footer remains UTC. Decide explicit export/local display convention and test midnight/date boundaries consistently. |
| Screenshot-based manual | **Partially verified.** Five-page role manual exists but required task screenshots are absent; add screenshots only after real workflow acceptance. Two-page quick-start, samples and installation guide are present. |
| Help/tooltips | **Partially verified.** Selected role help and fields exist; every-screen/every-field discoverability and keyboard interaction are not verified. |
| Complex-script PDF | **Not Verified.** English PDFs and selected UTF-8 text tests do not prove Urdu joining, bidirectional shaping, font embedding or clipping. Render representative mixed Latin/Urdu names/titles/allocations and inspect extracted/visual output. |

## B004 legacy integrity: no automatic recovery

Modern per-version snapshots, hashes/receipts, actor scope, independent publication validation and stale-result rejection have positive evidence. Legacy Published/Archived versions without their original trustworthy context remain **partially verified**, and PostgreSQL execution remains unverified. Existing fail-closed behavior is a safeguard, not proof that missing historical assumptions have been recovered.

A safe recovery proposal must be prepared and approved separately:

1. Inventory affected version IDs/type/term/status and missing/corrupt context using a read-only backup/clone. Record original entry/output, approval and database hashes; never rewrite live historical entries to fit current inputs.
2. Obtain contemporaneous trusted scheduling inputs: original rooms/capacities/types, offerings/course hours/instructor/batch/enrollment membership, availability/blocked periods/clock slots, exact enabled rules/weights/parameters, prior/locked context, algorithm/schema compatibility and provenance. Current master data is not evidence of the original values.
3. Independently validate the original entries against the reconstructed context and reconcile exact offerings/session/seat counts. Investigate inconsistencies instead of modifying the historical schedule or claiming inferred data are original.
4. Prepare an additive, reviewable per-version recovery mapping with provenance, content hash, validation receipt, operator identity, approvals and append-only audit. Preserve original version/status/approval relationships; do not expose a general API that auto-trusts legacy data. Prove transaction rollback and immutability on cloned SQLite and PostgreSQL.
5. Obtain designated institutional and technical review before any operator-run production recovery. If original inputs cannot be proven, label that historical version unverifiable, preserve/freeze it, and generate/approve a fresh version from current data. Do not silently rehabilitate it with current data or a fresh solver result.

This assessment performed no inventory of production data, recovery, migration or rewrite of an existing user database.

## Database / operational prerequisites and unverified acceptance

- **PostgreSQL — Not Verified:** provide an explicitly isolated disposable instance; run001–005 upgrade/rollback, DB checks/indexes/append-only and snapshot guards, generation/version allocation, competing publication, stale/cancel/save races, isolation/serialization handling and rollback tests. Do not infer compatibility from available SQL files.
- **Migration prerequisites:** back up and test restore first, determine exact installed schema, review and apply additive migrations001–005 with the supplied transaction/preconditions. Preserve001–004;005 is not a blindly repeatable migration. Seven SQLite test cases passed, but this is not permission to migrate user data. Resolve/approve supplemental nonce PK and immutable archival-denormalization exceptions to literal SRS schema wording.
- **Worker deployment:** file-backedSQLite or verifiedPostgreSQL, spawn-compatible entrypoint, initialized session factory, run/lease ownership and cancellation/save fencing. Verify multiple API processes, restart/lease recovery and connection contention in the intended environment. Single-machine tests do not establish a distributed deployment guarantee.
- **TLS and least privilege — Not Verified:** test TLS>=1.2, HTTP refusal/redirect/proxy behavior, deployed origin policy, externally supplied secrets, restricted DB grants and operational secret handling. Local loopback HTTP is deliberately not evidence of production transport compliance.
- **Backups/restore — Not Verified:** demonstrate automatic daily schedule, retention of seven backups and complete restore of master data, snapshots, entries, accounts/audit/import/history/run relationships. Written install steps are not an executed drill.
- **Reliability/availability/scalability — Not Verified in full:** specify campaigns for99% valid-run reliability and99% monthly working-hours availability, double-reference-size scalability, sustained load and failure recovery. No uptime/percentage is inferred from604 tests.
- **Portability/maintainability:** Linux deployment, current four-browser support, one-command packaging, >=70% engine coverage, complete exporter/rule/role extensibility and independent adoption remain unverified or partial as individually classified.
- **Privacy/licensing:** obtain university policy approval and verify delivered third-party licence notices/retention policy. Only inspected scheduling PII is evidenced; this is not a legal compliance certification.

## Recommended next actions

1. Obtain separate authorization for fixes G01–G06; prioritize reference completion/latency, honest solver outcome metadata and correct lifecycle transitions. Preserve all passing security, hard-constraint, snapshot and concurrency tests.
2. Restore safe browser tooling and execute the five-role/360px/keyboard/cross-browser acceptance matrix with persisted disposable data. Capture evidence for full user/use-case journeys instead of promoting source review to UI acceptance.
3. Provide isolated PostgreSQL and a production-like staging environment for migrations, concurrency, TLS, backups and load. Keep B004 legacy recovery independently approved and fail closed meanwhile.
4. Complete resource/week-start/screenshot/help/complex-script gaps and rerun only affected acceptance tests, then a final regression confirmation. Update the same requirement register and strict coverage calculation; require institutional signoff for any accepted exceptions.

No remaining work was automatically implemented. The assessment stops here; it does not authorize deployment or declare production readiness.
