# Remaining work and acceptance criteria

Weekly-grid save duplication is corrected separately (`WEEKLY_GRID_SAVE_FIX.md`): atomic idempotent PUT, original IDs/blocks/history retained, no deletion, strict POST/B002 validation preserved. Targeted checks pass; actual browser/PostgreSQL verification and broader final acceptance gaps are not closed by this fix. Existing installations need the updated backend/frontend, no additional migration.

## Current verified baseline

Final original-audit batch: **604/604 project tests**, **28/28 original audit regressions**, **27 new Python cases** included in the full run, and **5 separate frontend rendering/client tests** passed. Both TypeScript projects, production build and **7 disposable SQLite migration tests** passed. Full/audit suites were run once each; reruns are not distinct tests. Exact commands and earlier batch history remain in PROGRESS.md; machine evidence is in `batch4_test_results.json`.

- B001–B003 and B005 resolved; prior security/grid/enrollment/lab regressions remain passing.
- B006–B011 implemented: authoritative account/RBAC/availability/publication/import/export workflows remain passing.
- B012–B018 protections remain passing: process cancellation/deadlines, startup recovery, S05, atomic manual blocks/allocations/locks/undo, append-only audit, malformed input validation, snapshots/freshness and concurrency. Both original unchanged 10-second timetable/exam generation tests now pass. The eager backend package app import was removed through compatible lazy exports; engine, auth core, snapshots, supervisor/executor, existing tests and migrations are unchanged.
- B019 implemented and SQLite/API verified: persistent unused-config deletion, protected historical references, atomic settings/rule saves, catalogue/domain/mandatory validation, clone persistence, generation preflight and serialized delete/generate races. No browser-local deletion overlay remains.
- B020 functional UI/documentation improvements delivered; **full SRS completion and browser acceptance remain partial** as listed below.

## B004 legacy integrity (separate from passing regressions)

- Legacy Published/Archived versions without trustworthy original scheduling inputs must continue to fail closed. Recovery needs reviewed original data; never infer/fabricate snapshots, destructively recover schedules or rewrite official history.
- Preserve exact reviewed snapshot-reader fingerprints across engine releases. Passing the 99 existing B004 cases does not establish legacy recovery or PostgreSQL execution.

## B020 unfinished requirements / acceptance

- Complete extraction of remaining dynamic/form UI text into locale resources, complete field-tooltip coverage and configurable first working day per term. Current UTF-8 English/navigation/status/help resources and explicit Asia/Karachi formatting are implemented; complete Urdu interface coverage is not claimed.
- Obtain role-specific screenshots for the delivered PDF user manual and conduct the SRS timed Coordinator/Faculty/Student usability trials. The delivered five-page manual, two-page quick start, installation PDF/Markdown and six CSV examples/field reference are real text artifacts; no screenshots or test results are simulated.
- Test actual Chrome/Firefox/Edge/Safari workflows, narrow/mobile layouts, keyboard navigation/focus restoration, screen-reader descriptions and WCAG 2.1 AA contrast. Server-rendered HTML assertions, CSS changes and builds do not certify browser/mobile/accessibility compliance. Help is linked from authenticated screens; unauthenticated help/discovery needs review.
- Verify end-to-end browser account, configuration, import, publish/archive, manual adjustment/undo, cancel acknowledgement and download/save-dialog behavior against disposable backend data.
- Verify extreme-density/grouped PDF readability and Urdu/CJK font/shaping behavior; prior Latin-Unicode content checks are not complex-script typography acceptance.

## Deployment / concurrency / performance (Not Verified)

- PostgreSQL migrations, transactions, constrained grants and simultaneous saves/cancel/publication/import/configuration operations require an isolated PostgreSQL instance. No production credentials or existing database were accessed for testing.
- Existing installations require reviewed migrations **001–005 in order**; 005 is once-only. **This batch introduces no new migration or dependency.** Retain explicit operator database selection, backups and reviewed grants; application startup does not silently upgrade an existing schema.
- Use file-backed SQLite or PostgreSQL and a spawn-compatible default FastAPI entrypoint. Keep lazy package imports, real separate workers, the two-worker per-API-process bound, absolute deadlines, leases and commit fences. Do not stretch the 10-second tests or accept partial output to obtain success.
- Cross-process/host cancellation, distributed global capacity/queueing, restart/lease-expiry under operational load, reference-size import/export/scheduling deadlines and P-8's measured API slowdown limit remain unverified. Tiny regression fixtures do not establish performance acceptance.
- Define import-stage retention/purge policy. Stages expire after one hour, but retained preview/report data is not automatically purged.
- Production TLS/CORS/proxy settings, database DDL ownership, secrets handling, backup/restore and deployment operational checks remain operator acceptance tasks. No production deployment was performed.

## Other separately tracked SRS gap

- FR-9.5 duplicate-to-new-draft is not implemented by clone-configuration or manual undo. Any future implementation must allocate a new version and preserve original official inputs/history.

Original audit probes are **28/28 passing**, but that is not a declaration of complete SRS/deployment compliance. Preserve all tests and hard constraints. Stop after this requested batch; do not automatically start deployment or another batch.
