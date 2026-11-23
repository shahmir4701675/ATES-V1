# B004 — Published version input integrity

21 November 2026, Asia/Karachi. B004 only. B005 was not started. No production or existing user database was read, migrated, seeded or modified.

## A. Root cause

Schedule entries referenced mutable rooms, offerings, courses, instructors, batches and slots. `load_term_dataset` and the enriched schedule views re-read those current records for historical schedules. Generated results also retained neither an authoritative input version nor a comparison between their loaded inputs and the inputs at save time. Existing read-only entry checks did not protect the meaning of referenced data. Consequently, reducing a room's capacity after publication could introduce H04 violations without changing any published entry or approval.

The existing SQL schema contained some integrity triggers, but ORM-created development databases did not install all SQL-only protections. There was no authoritative publication HTTP endpoint; the frontend publication overlay remains the separately tracked B008 issue.

## B. Chosen architecture

Each successfully persisted version now has an immutable database-backed scheduling input snapshot. It contains the term, schedule type, selected configuration and rules, relevant courses, offerings, batches, instructors, availability, clock windows, blocked periods, room attributes and the shared candidate room pool. Exam contexts also retain raw explicit enrollments and the data used by B003's conservative A-4 inference. Timetable contexts exclude exam-only data; exam contexts exclude weekly timetable grids and availability. Relevant term references are filtered explicitly.

The snapshot records format/policy identifiers, engine source SHA-256 identities, installed OR-Tools/NetworkX versions, selected source version/locks and API solver overrides. It contains no passwords, signing keys or user authentication sessions. Canonical sorted JSON and a SHA-256 input hash bind the context. Decoding checks its scope, exact dataset field types, checksum, policy, implementation identity and configuration consistency before independent validation. Historical Published/Archived contexts must also match their persistent validation receipt.

Historical loading with an explicit `schedule_id` reads frozen master inputs plus only that version's entry/allocation rows. Historical views, labels, filters and validation use that context. They do not enrich entries from current master data. A bulk load that could mix official historical versions with live inputs is rejected unless the caller explicitly selects a version or requests current generation inputs.

New generation explicitly uses current data. It captures the context under the same database serialization lock used by source writes, releases the transaction before CPU solving, and supplies that exact captured dataset and its configuration parameters to the existing solver. Before result persistence, the adapter takes the lock again and compares a newly captured, equivalently scoped input hash with the original. A changed input rejects the result even if it might still happen to be hard-valid. Seconds/microseconds are preserved at the adapter boundary, so a clock change cannot evade hashing through minute truncation; malformed weekly precision remains rejected by B002.

Header, entries, allocations, snapshot and audit rows are committed together. A stale input, independent validation failure, reference error or database failure rolls back the result transaction. A failed worker records an Infeasible/interrupted run and a diagnostic, without saving its result entries or overwriting an earlier version. Result persistence into an existing header requires the matching Generating term/type/configuration; existing Generated, Published or Archived headers cannot be reused as solver output targets.

`schedule_input_state` supplies a common write-lock boundary. SQLite uses its transactional write serialization. PostgreSQL DDL uses a singleton row lock and BEFORE STATEMENT revision triggers, before source/entry row mutation. Input capture, saving, manual edits and publication review cooperate with that lock. Hashes determine relevant input equality; unrelated state changes do not become part of a historical context. ORM identity-map entries are explicitly refreshed/expired where needed, including publication review after another writer changes a cached entry.

### Publication foundations, not a B008 endpoint

`publication_eligibility` requires Generated status and independently validates the persisted entries against their authoritative context. It checks references and active resources in that context, mandatory and enabled hard constraints, and unresolved hard conflicts. A trusted ORM Generated-to-Published transition invokes this review before flushing. A legacy Generated version without context can establish one only at explicit review while independently valid against the current reviewed inputs; this is not proof of its original generation inputs.

A persistent validation receipt binds review to the input hash. Every entry/allocation mutation invalidates that receipt. The database rejects publication without the matching snapshot and fresh receipt, prevents Published/Archived entry edits and history deletion, protects version/approval metadata and prohibits returning official versions to editable states. Snapshot rows are immutable in every lifecycle state; official receipts are immutable too. New context may be established only for Generated versions.

There is deliberately no new publish HTTP route or frontend publication mechanism. B008 remains incomplete. A future authoritative endpoint must enforce Approver authorization, perform this review, archive the previous official version in the correct transaction order, set approval metadata and audit the action. The internal eligibility function grants no user role or publication permission.

### Changes to Generated versions

New Generated versions already use frozen inputs. Current master edits affect subsequent generation. Manual entry moves within a version remain supported and are independently checked against its frozen context. A room or slot created later cannot be added silently to that context; generation of a new version is required. The existing manual-move regression still asserts H04 rejection and a successful move/lock, with its test rooms now created before generation.

## C. Modified-file list

Application files:

- `backend/models.py`: three supplemental ORM models and the exact model inventory.
- `backend/database.py`: initialize B004 objects/guards on explicitly initialized new or disposable databases; deployment migrations remain explicit.
- `backend/adapter.py`: historical snapshot loading, exact clock serialization, original-context persistence, stale-input rejection, atomic validation/snapshot writes and serialized version allocation.
- `backend/routers/schedules.py`: captured current inputs for workers; frozen historical enrichment/filtering; manual-edit locking/context checks; historical status validation.
- `backend/main.py`: HTTP 409 handling for invalid version contexts and database integrity rejections. Existing B001 authentication gates remain intact.
- `backend/schedule_integrity.py` (new): canonical contexts, strict decoding, implementation identities, freshness checks, independent validation and review/receipt foundations.
- `backend/snapshot_schema.py` (new): shared additive SQLite/PostgreSQL DDL definitions for revision, immutability and lifecycle guards.

Database and test files:

- `db/migrations/002_schedule_snapshots.sqlite.sql` (new).
- `db/migrations/002_schedule_snapshots.postgresql.sql` (new).
- `tests/test_schedule_integrity.py` (new): 99 B004 cases; each integration test gets a separate disposable file-backed SQLite database copied from an immutable test-only seed template.
- `tests/test_backend_db.py`: preserve the strict 21-business-table schema comparison and also account for auth plus the three B004 tables.
- `tests/test_backend_api.py`: create capacity/valid-move test rooms before generation. Existing security, H04 and successful move/lock assertions are retained.
- `tests/test_auth.py`: the migration-001 fixture explicitly builds its original schema instead of using today's initializer. Its exact 21-table assertion and all security assertions are retained.

Documentation/evidence:

- `audit_reports/BUG_REPORT.md`: B004 implementation/status annotation; original evidence remains historical.
- `audit_reports/B004_FIX_REPORT.md` (this report).
- `audit_reports/b004_*.log`, `.xml`, `.json`: execution, comparison and preservation evidence. Generated frontend output is locally excluded in `.git/info/exclude`.

No engine, frontend source, prior B002/B003 regression file, authentication implementation, authentication dependency or authentication router was changed for B004. Prior uncommitted fixes remain in the working tree.

## D. Schema and upgrade behavior

The original 21 business tables and migration 001 remain. The total ORM inventory becomes 25 tables: 21 business, one authentication session table and three new B004 tables.

- `schedule_input_state`: singleton primary key `state_id=1`, non-null revision counter. This is the serialization point.
- `schedule_snapshots`: schedule primary key/FK with restrictive deletion, term FK, schedule type, format version, 64-character input hash, canonical JSON text and creation timestamp. Type, format and hash-length checks and a term/type index are supplied.
- `schedule_validation_receipts`: schedule primary key/FK to the snapshot, reviewed input hash and review timestamp. Entry/allocation triggers invalidate it; official receipt mutation is rejected.

Migration 002 also installs source/entry revision triggers, snapshot/receipt immutability, entry/allocation read-only guards, context scope checks, approval/version metadata guards, publication receipt requirements and official lifecycle/history protections. SQLite and PostgreSQL scripts are additive and transactional. The scripts are repeatable; no old entry, approval, status or source record is rewritten or deleted by migration. The Python DDL definition and checked-in scripts are kept consistent.

**Existing Published/Archived versions without a trustworthy snapshot are not backfilled from current data.** That would invent their original meaning. Their historical reads fail closed with HTTP 409, and source-write guards prevent further master/entry mutations while such official versions exist. This guard is deliberately conservative and database-wide; it can block unrelated master changes until recovery is reviewed. Authentication/audit storage is outside that source guard.

Those legacy records and their relationships remain intact. Recovering usable historical context requires a separate, reviewed recovery using trustworthy original inputs/backups and independent per-version validation. No such inputs were supplied and no production recovery was attempted. Already official legacy versions cannot silently establish a new context through normal application helpers or the migration.

Deployment must explicitly review/apply migrations 001 and 002 to an operator-selected target before enabling this code. `init_db` is a new/test database bootstrap, not an unattended production-upgrade mechanism. Original foreign keys still restrict identity changes/deletion of referenced master rows; some offering batch/instructor edits are therefore rejected rather than rewriting history. Such changes require compatible new records/new versions.

## E. Verification evidence

Final project, preservation, audit and migration results are recorded in the `b004_*` evidence files. Project totals and regression subsets are reported separately; repeated/focused executions are not added as distinct tests.

- Full project: **362 passed, 0 failed**, 363.41 seconds (`b004_project_tests.log` / `.xml`).
- B001 authentication regressions: **37 passed, 0 failed** (included in the project run).
- B002 weekly-grid/physical-overlap regressions: **87 passed, 0 failed** (included).
- B003 enrollment regressions: **60 passed, 0 failed** (included).
- B004 integrity regressions: **99 passed, 0 failed** (included).
- Original B004 audit regression: **1 passed, 0 failed** (included in the full audit).
- Full original audit: **16 passed, 12 failed** (`b004_audit_regressions.log` / `.xml`); no newly failing audit case.
- Frontend application TypeScript, tooling TypeScript and production build: **all passed** (`b004_frontend_checks.log`).
- SQLite migration tests: **2 passed, 0 failed** (a subset of the 99 B004 cases, also run separately in `b004_migration_tests.log` / `.xml`).
- PostgreSQL migration/transaction tests: **Not Verified** (`b004_postgresql_verification.json`).

`b004_test_results.json` contains the separate result ledger. Existing Starlette/httpx and HTTP-422-name deprecation warnings remain; they are not failures. Focused context-validation tests also passed 12 cases, and the original auth-migration fixture correction passed its focused test before the final full run.

Commands from the repository root:

~~~powershell
.venv\Scripts\python.exe -B -m pytest tests -p no:cacheprovider -q --junitxml=audit_reports/b004_project_tests.xml
.venv\Scripts\python.exe -B -m pytest tests/test_schedule_integrity.py -p no:cacheprovider -q -k migration --junitxml=audit_reports/b004_migration_tests.xml
.venv\Scripts\python.exe -B -m pytest tests/test_schedule_integrity.py -p no:cacheprovider -q -k 'cached_entries or invalid_snapshot or corrupt_persisted' --junitxml=audit_reports/b004_context_validation.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py audit_reports/test_extra_probes.py -p no:cacheprovider -q --junitxml=audit_reports/b004_audit_regressions.xml
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.app.json --noEmit
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.node.json --noEmit
node frontend/node_modules/vite/bin/vite.js build frontend --outDir ../audit_reports/b004_frontend_build
~~~

The final full audit has **16 passed, 12 failed** versus B003's 15 passed/13 failed. The original `test_generated_schedule_immutable_through_master_data` passes; no original audit case newly fails. Its result is a subset of the full audit, not an extra distinct test.

Frontend application TypeScript, tooling TypeScript and the production Vite build passed. No frontend source change was required.

Both disposable SQLite migration tests passed: additive upgrade with preserved legacy records and fail-closed behavior, and complete rollback after an injected migration syntax failure. The tests never run migrations against an existing user database. SQLite source-write serialization and stale-generation windows are exercised with independent sessions, a real writer thread and real solver results. Database-failure injection verifies no partial new version, entries, snapshot or audit survives.

**PostgreSQL migration/transaction/concurrency execution: Not Verified.** No safely isolated PostgreSQL test instance was available; PostgreSQL tools and Docker were not found on PATH. No existing database was contacted. The PostgreSQL DDL is supplied and reviewed in source, but SQLite execution is not evidence of PostgreSQL runtime correctness.

Development failures are retained in initial/pre-final logs. They exposed incorrect new fixture assumptions about the seeded capacity, a seed helper that initialized modern DDL instead of a pre-migration database, room setup outside a frozen generation context, and the old auth-migration fixture's schema count. These fixture corrections preserve the original hard/security assertions. No test was removed, skipped, xfailed or weakened to accept an invalid schedule.

## F. Previous regression preservation

The full final suite includes all 37 B001, 87 B002 and 60 B003 cases. File hashes in `b004_preservation_baseline.json` / `b004_preservation_results.json` confirm all engine files, frontend source and prior B002/B003 regression files remain unchanged. The only modified pre-existing test files are the three schema/resource fixture adaptations listed above. The original B001 security behavior and assertions remain intact.

## G. Remaining original audit failures

The 12 retained failures concern student draft visibility/list filtering (two tests); missing user, audit, import, publish and CSV/PDF export endpoints (six tests); lab clock adjacency (B005); exam manual-override metadata; master-data mutation auditing; and lazy-app interrupted-run recovery. These remain genuine unresolved findings, not B004 failures or intentionally relaxed tests. The actual B008 publication endpoint remains absent.

## H. Known limitations

- Existing official versions with no original snapshot require reviewed recovery; they remain unchanged and unavailable for authoritative interpretation rather than being assigned fabricated history. This is the principal incomplete deployment path.
- PostgreSQL execution and transaction behavior are Not Verified. Operational database grants, live deployment and reference-size concurrency/performance were not tested.
- Snapshot readers pin engine implementation and dependency identities. Future releases must retain a compatible versioned reader/validator or a reviewed migration; this implementation fails closed on incompatible code rather than silently applying new rules to old history. Do not hot-replace engine files in active worker processes.
- Master changes affect future versions. Deactivating a room does not change the original plan recorded in an official snapshot; institutional operational changes require a newly generated/reviewed/published version.
- Snapshot inputs are immutable; adding a newly created resource to an existing Generated version requires a new generation. Some identity edits remain restricted by original foreign keys.
- Direct successful adapter persistence requires the original captured context. The high-level `TermScheduleAdapter` retains the loaded context; lower-level callers must pass `source_context` captured before solving. API generation records actual overrides; standalone callers are responsible for recording their own search overrides if exact search replay is required. Independent hard-validity replay uses frozen data/configuration and persisted entries.
- The serialization point is coarse. Contention can delay writes; database lock/transaction failures roll back rather than falling back to unchecked inputs. PostgreSQL retry/performance behavior has not been measured.
- Checksums and database triggers protect ordinary application/database writes and detect corruption; they are not protection against a database administrator deliberately disabling all safeguards and rewriting every proof record. Production least-privilege database grants remain an operational requirement.

## I. Final B004 status

**Partially resolved overall.** The implemented snapshot, stale-result, independent-review, receipt and read-only guarantees protect new versions and independently reviewed legacy Generated versions, and the original B004 regression passes. Already Published/Archived legacy versions whose original inputs are missing cannot yet be independently reconstructed/validated; they fail closed pending trusted recovery. PostgreSQL execution remains Not Verified. Complete historical deployment resolution is not claimed.

No production migration or historical rewrite was attempted. B005 and unrelated roadmap items were not started.
