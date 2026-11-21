# ATES security and database audit

21 November 2026 (Asia/Karachi). Audit only. **Critical authentication/authorization bypass and published-data integrity defects verified against isolated SQLite.** No production database, secret values, external deployment or credentials were accessed.

## Security findings with executed evidence

1. **B001:** GET /courses without login200; POST /rooms without login201; forged X-User-Role:Administrator also201. get_current_user trusts X-User-Id/Role/Instructor-Id/Batch-Id; require_roles adapts missing identity to a privileged allowed role. Explicit Student403 on a mutation is only a voluntary caller-supplied restriction. No JWT parser/verification, active-account lookup, token revocation, password hashing, rate-limited login or inactivity session exists.
2. **B006:** Student reading /schedules/1/entries receives Generated timetable with 26 entries despite X-Batch-Id1; list exposes Generated schedules. batch/instructor query filters are optional and not enforced from the caller. GET /enrollments permits all Student callers with no own-student restriction (static inspection). Faculty/Student schedule defaults are all, and version selection can include unpublished/archived versions. Administrator is allowed generation202 despite SRS separation of administrative duties.
3. **B007:** Faculty header without X-Instructor-Id updates instructor2 availability200. The own-record guard runs only when the untrusted optional link is not None. Reading availability is likewise not ownership-restricted.
4. **B004:** after creating a valid Published fixture with approved_by/published_at, PUT /rooms/1 capacity1 succeeds200 and revalidation of its existing timetable finds H04 violations. Direct Published entry edits are correctly rejected409; that isolated guard does not freeze referenced room/config/course/slot/enrollment data.
5. **B017:** malformed time and cross-midnight grids return500; invalid day returns misleading409. Pydantic time fields are unparsed strings, working_days is an unrestricted integer list, and _parse_time_str/time constructors can raise unhandled errors.

Auth login/logout, users/audit, import, publish and schedule export endpoint probes return404. The frontend mock login accepts a known username and any nonempty password; account save discards passwords and lock text is fixed. No actual lockout/expiry is proven by mock account fields. Security functions must not rely on role menus or a client role selector.

## Positive controls and their limits

- SQLAlchemy query expressions are used instead of constructing SQL from user text; the inspected routes provide a parameterized ORM boundary. React renders ordinary text with escaping; no claim of a comprehensive XSS/injection penetration test is made.
- Executed CORS tests accept the configured localhost React origins and reject an unknown origin. CORS is a browser-origin policy, not caller authentication or permission enforcement; it does not prevent direct API callers.
- Pydantic field bounds plus DB checks reject several negative/zero values, duplicate codes and FK errors; ordinary tests pass. There are important remaining domain and error-handling gaps.
- Foreign keys are enabled on SQLite connections; composite offering references and timetable conflict UNIQUEs were tested. Published entry updates are rejected by the API and approval metadata is required by a DB CHECK.
- Result persistence and rollback are transactional. They do not establish immutable solve-input snapshots, role-aware publication or a concurrency-safe version allocator.
- Database URL loading from environment and .gitignore/.env.example protection checks passed. No actual .env secret values were printed/read for this audit. Source confidentiality is not proof of deployed least-privilege grants or encrypted connections.

## Database schema and relationships

Runtime metadata confirms **21 relational ORM tables**, with integer surrogate PKs, ordinary FKs, relationships and application/domain checks. The existing12 database tests pass repository table-name/expected-column checks, FK restriction/cascade, ordinary uniqueness/checks, seed/adaptation, generation/save and rollback. This establishes tested SQLite behavior and expected ORM table/column shapes; the parity test extracts SQL table names but uses hard-coded ORM column expectations. It does not compare SQL indexes/triggers or all database behavior.

| SRS table | Implemented relationships/guards | Audit finding |
|---|---|---|
| academic_terms | Unique name, date order, status enum, partial single-Active index. | At-most-one differs from exactly-one FR wording. Activation uses separate frontend close/activate calls; closing does not drive full published archive lifecycle. |
| departments | Unique code; courses/instructors/batches FK parents. | Live list/create/update; create/update role grants include Administrator beyond stated scheduling ownership. |
| rooms | Unique code, positive capacity, Lecture/Lab/Exam Hall enum, active flag. | Mutation capacity1 invalidated Published timetable; labels/types/capacities are mutable across historical schedules. |
| batches | Department FK; unique programme/year/section; positive strength and active flag. | CRUD partly tested; old schedules resolve live mutable batch metadata; own-batch visibility missing. |
| courses | Department FK; unique code; nonnegative hours; positive contact sum; active flag. | CRUD/negative cases tested; contact-hour/active changes affect historical validation without immutable snapshots. |
| exam_slots | Term FK, term/date/start UNIQUE, end>start. | API checks same-day overlap at creation; schema.sql:492-516 also defines a PostgreSQL overlap trigger; ORM create_all omits it. Concurrent insertion behavior was not tested. |
| instructors | Department FK; unique email; daily>0 and weekly>=daily; active flag. | Email only string length at API; no trusted identity/ownership; editing limits can invalidate historical schedules. |
| time_slots | Term FK, unique term/day/index, positive index/day range, end>start, blocked reason CHECK. | No overlap/equal-duration/temporal-grid invariant; API accepts malformed topology and invalid time paths yield500. |
| course_offerings | Term/course/batch/instructor FKs; positive count; unique term/course/batch and offering/instructor/batch composite identity. | Composite entry FK rejects instructor/batch mismatch; course/term/count edits can affect historical schedules. No inactive column/retirement route. |
| instructor_availability | Instructor/slot FKs; unique pair; boolean available flag. | Default available implemented; partial ownership guard is bypassed when instructor link omitted; duplicate new slots in same request not exhaustively tested. |
| users | Unique username/email, allowed roles/statuses, Faculty/Student link CHECKs, failed-attempt fields. | No authentication/hash/account API. Seed password_hash values are placeholders; no actual credential verification. Production grants/row policies not inspected. |
| audit_logs | Nullable user FK, action/entity/details/UTC timestamp; user/date indexes. | Generation/manual/rule events exist; security/import/publication/export services absent; no live query API; PostgreSQL SQL-only immutable trigger installation unverified. |
| enrollments | Offering/user FKs and unique offering/student. | API checks Student role, but FK alone does not encode role. Identity/own-scope privacy missing; optional fallback logic inconsistent. |
| import_logs | User FK; nonnegative counts and totals CHECKs; filename/type/time. | No authoritative import write/query service; immutable-log trigger exists only in PostgreSQL SQL script and is not installed by ORM init. |
| scheduling_configs | Term/created_by FKs; unique term/type/name; time limit10-600 and type enum. | created_by supplied by client; no real delete route; no immutable per-run config snapshot. |
| constraint_rules | Config FK; unique config/code; Hard/Soft and weight0-10 checks; mandatory-rule disable guard. | Unknown rule code/type/parameter domain unchecked; changing rules changes meaning of existing version validation. |
| schedules | Term/config/user FKs; term/type/version UNIQUE; status/solver/runtime checks; Published requires approval metadata; partial one-Published index. | Approval role not a DB invariant; publish service absent; max+1 race, generated_by forgeable, missing creator/approver FK indexes; default startup recovery fails. |
| conflict_log | Schedule FK with cascade; Hard/Warning CHECK; timestamp/resolved flag. | Stored reasons exist; no standalone validate-any endpoint; health/review can rely on stale stored counts. |
| exam_entries | Schedule/course/slot FKs; unique schedule/course; student_count>0; locked flag. | Manual-override marker absent despite engine dataclass support; course FK has no leading index. Session/schedule same-term consistency needs service validation. |
| timetable_entries | Schedule/offering/instructor/batch/room/slot FKs; offering-triplet FK; schedule/resource/slot UNIQUEs; type and flags. | Ordinary clashes rejected by DB; distinct overlapping slots bypass exclusivity. Same-term membership not fully encoded. No stable metadata snapshot; missing resource-leading FK indexes. |
| exam_room_allocations | Exam-entry/room FKs; unique entry/room; positive seats. | Validators enforce seat totals/disjointness; schema.sql:518-541 adds a PostgreSQL per-room capacity trigger absent from ORM create_all. Missing/inactive/type cases not comprehensively executed. |

Parent/child FK coverage in SRS Table30 is represented by the model metadata: departments to batches/courses/instructors; terms to slots/offerings/configs/schedules/exam slots; users to enrollments/config creators/schedule generators/approvers/import/audit records; offerings to enrollments/timetable entries; instructor/slot to availability; schedules to timetable/exam/conflict rows; courses and exam slots to exam entries; exam entries/rooms to allocations; rooms/slots/instructors/batches to timetable entries. runtime_inventory.json records every FK column, target and delete policy. FK existence does not establish that a child and its schedule/config/slot belong to the same term. API manual moves check term membership, but general schema/standalone save routines do not enforce all such combinations.

### Divergent schema initialization and missing ORM indexes (DB-7)

The PostgreSQL script already defines all six indexes below (schema.sql:444-457), while SQLAlchemy ORM metadata/create_all omits them. Therefore the verified defect is initialization-path divergence, not absence from all repository SQL. Installed production indexes were not queried. Metadata inspection checked whether each FK column is the **first column** of an index or unique/primary key. Unique(schedule_id,instructor_id,slot_id) is not a substitute for an index beginning with instructor_id when looking up that FK alone. Deduplicated uncovered FK columns:

- schedules.generated_by
- schedules.approved_by
- exam_entries.course_id
- timetable_entries.instructor_id
- timetable_entries.batch_id
- timetable_entries.room_id

The raw inventory lists instructor/batch twice because each participates in multiple FK constraints. No query-plan/latency benchmark was executed, so actual P-7 compliance is Not Verified rather than a measured failure.

### Integrity and lifecycle gaps

- No versioned migration scripts/framework are present; init_db calls metadata.create_all without executing schema.sql functions/triggers. A standalone schema.sql is not a reproducible sequence of forward schema changes, and create_all does not safely upgrade existing tables. No migration was run.
- DB single-Active and one-Published partial indexes and approval CHECKs are positive. An actual atomic activation/publication/archive transaction is absent. UI activation closes the current term then activates another in a separate request, permitting an intermediate/no-active state or partial failure. Closing a term does not implement the required full archive state transition.
- Existing schedule rows reference current master data/config rules rather than immutable version input. Capacity, hours, availability, room type, slot times, course title, offering counts and config rules can change after generation/publication. Demonstrated H04 failure is one instance of this larger model issue. Frozen data/version hashes or restrictive version-aware updates are needed.
- The worker loads input and releases its read transaction before solving, then saves later. The save routine trusts result.status and result.violations; it does not independently reload and validate under a consistent current snapshot. Static analysis identifies stale-input risk. Concurrent edits/runs were not load-tested.
- _next_schedule_version reads max(version_no)+1. Concurrent requests can choose the same version and hit the DB unique guard. The guard preserves uniqueness, but the API commit path has no explicit retry/serialization/error mapping here. This is a plausible static race, not an executed concurrency failure.
- Schedule deletion cascades child entries as designed by schema/tests; the API does not expose arbitrary schedule deletion. Master physical deletion is generally RESTRICTed, while offering deletion has only a referenced-entry409 guard, without requested retirement/deactivation. Indirect dependence of exam schedules on offerings/enrollments is not a frozen historical relationship.
- schema.sql:472-490 defines PostgreSQL append-only audit/import triggers, :492-516 exam-slot overlap trigger, :518-541 exam capacity trigger and :543-589 Published/Archived entry protection triggers. ORM models/create_all do not install those SQL-only functions/triggers. No HTTP audit mutation route is exposed, but trigger deployment and SQL grants were not inspected, so production immutability/least privilege cannot be certified. A manually SQL-initialized PostgreSQL database has intended guards absent from a create_all-initialized database. Persistent room creation produced no audit event; more significantly mandatory login/account/import/publication/export events have no real service implementation.
- Event timestamps use UTC helpers; some API formatters appendZ for naive values. UI locale formatting follows the client timezone instead of explicitly Asia/Karachi. UTF-8 and Urdu-name roundtrips were not executed. Frontend interface strings are embedded rather than isolated translation resources.

## CSV/import/export and file handling

All apparent import services in real frontend mode call mock data. Client file extension/size checks are bypassable, do not establish UTF-8 validity, and are not a server upload boundary. There is no multipart parser endpoint, upload storage isolation, authoritative row FK validation, persistent ImportLog or transaction/confirmation service. Mock confirmImport has no offering/enrollment insert branches yet reports rows imported. The local CSV parser accepts unfinished quotes without a reported parse error by static inspection.

Schedule PDF/CSV exports are absent. Buttons emit status messages and required GET export path returns404. The conflict report has a separate local Blob CSV generator, but no server audit or authorization certificate for that download. PDF A4 landscape/filter/date metadata, batch/instructor multi-page output and timing are unverified/absent.

## Production controls not verified

No external connection or intrusive scan was attempted. Application default frontend URL is plain HTTP localhost, and engine creation does not itself force sslmode/verify server certificates; actual deployment may add TLS via database URL/reverse proxy. HTTPS redirect/refusal, TLS version, PostgreSQL account privileges/RLS, source-secret history, dependency CVEs/licence inventory, backup automation/7-day retention/restoration, monitoring/uptime and operating-system hardening require deployment evidence. Their absence from the snapshot is not proof that external controls do not exist. No dependency installation, credential/environment change, production migration, backup restore or source fix occurred.

## Required remediation

Resolve B001/B004/B006/B007 before deployment; then complete mandatory auth/import/publication/export and trusted immutable audit services. Introduce versioned migrations, missing indexes, cross-term/input validation and snapshot/concurrency controls. Validate with isolated PostgreSQL and SQLite, full role/ownership tests, fresh publish-time independent validation, restore drill and deployment TLS/grant evidence. Prioritization follows IMPLEMENTATION_ROADMAP.md, which preserves the user's requested order.
