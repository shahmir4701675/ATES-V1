# B001 authentication and authorization fix

Date: 21 November 2026 (Asia/Karachi). Baseline: local/GitHub commit fb4cab6. Scope: B001 only; no B002 implementation started. The SRS, bug register, algorithm audit, roadmap and functional test report were read before changes. The original audit counts/evidence remain baseline records; this report records the subsequent fix.

## Result

**B001 is resolved in the implemented code and isolated regression verification.** Anonymous access, forged identity/role headers, caller-selected actor IDs and endpoint-adapted privileged defaults no longer authorize business operations. A successful database-backed login is required. This is not a claim that the whole SRS, all authorization row scopes, or the deployed installation is ready.

- **Existing project cases: 79 passed, 0 failed.** Their algorithm/constraint expectations remain intact.
- **New authentication cases: 37 passed, 0 failed.** Together the project run is **116 passed, 0 failed**, 128.35 seconds.
- **Relevant B001/identity/RBAC audit subset: 5 passed, 0 failed.** These are included in the broader audit run, not counted again.
- **Full retained audit suite: 28 executed, 8 passed, 20 failed**, 19.98 seconds. All remaining failures are existing out-of-scope findings, listed below. They were not removed, skipped, xfailed or converted into passing expected-failure assertions.
- Combined distinct final pytest cases: **144 executed, 124 passed, 20 failed**. Repeated development runs are not added to this total.
- **Application TypeScript, tooling TypeScript and Vite production build all passed** after the final frontend edits. The bundle is redirected to audit_reports/b001_frontend_build; existing frontend/dist is untouched.
- Operator password-enrollment/revocation/real-login smoke check passed against a disposable SQLite file. This is a separate smoke check, not one of the 144 pytest cases.

No production database, credentials, environment file or existing account/password was modified. No scheduling-engine or input-dataset changes: SHA-256 comparisons confirm all 10 engine/data files in the original source manifest remain unchanged. All database writes/migration verification used isolated SQLite targets. Dependencies added to the development virtual environment and requirements: bcrypt5.0.0 and PyJWT2.15.1 only.

## Security changes

1. **Trusted identity boundary:** the shared dependency verifies a JWT with fixed HS256 algorithm, expected issuer/audience, required issued-at/expiry/subject/session claims, then verifies the persisted session and current user record. X-User-Role, X-User-Id, X-Instructor-Id and X-Batch-Id are not parsed as identity. Role claims in JWTs are not authorization grants; current role/status/links are read from storage every request.
2. **Fail closed before business access:** both root business routers and their /api aliases have a router-level authentication gate. This runs before route database dependencies/business validation, including when no deployment database or signing key is configured. Individual handlers additionally enforce their role allowlists. Missing/invalid/expired/revoked credentials return401 with a Bearer challenge; authenticated inactive or disallowed roles receive403. Broken/missing signing-key configuration returns503 rather than an insecure fallback.
3. **Real credential verification:** /auth/login verifies a salted bcrypt cost12 hash and issues a signed JWT bound to a stored session. Unknown/incorrect/unavailable accounts get a generic401; no default account password or production signing secret is introduced. Password enrollment rejects fewer than8 characters or more than72 UTF-8 bytes. Malformed seed placeholder hashes fail closed.
4. **Session lifetime and revocation:** the new supporting auth_sessions table records a random token ID, user binding, password-hash fingerprint, last activity and idle expiry. Sessions expire after30 minutes inactivity and have an additional8-hour JWT maximum. /auth/logout revokes the current session across API instances. Password changes invalidate old sessions. Five failed logins impose a15-minute lock and revoke current sessions; the failed counter uses an atomic SQL update. Correct login clears the counter after a timed lock expires.
5. **Role and actor integrity:** Coordinator is the scheduling/master/config mutation role; Faculty availability writes use the stored instructor identity. Administrator, Approver and Student cannot gain scheduling mutation privileges. created_by/generated_by body inputs remain accepted for old-client compatibility but are ignored; authenticated user ID is persisted. All former default-role adaptation is removed.
6. **Minimal frontend integration:** login now calls the real backend and stores its bearer credential only in memory; protected pages cannot mount before successful login. The default Administrator identity and role selector are removed, logout revokes server state, and protected-request401 returns the UI to login. The obsolete mock-login implementation is deleted, even when demo data mode is selected. Other unfinished mock data workflows are not rebuilt.
7. **Deployment and enrollment:** additive PostgreSQL/SQLite migration files and an explicit-target, password-prompt operator tool are supplied. They do not execute against a configured production database at startup. The original21 SRS business tables/columns remain unchanged; the22nd table supports persistent security sessions. Login/failure/lock/logout/operator-enrollment events are recorded without password/token contents.

## Verification commands and evidence

Run from the repository root with existing installed tools:

~~~powershell
.venv\Scripts\python.exe -B -m pytest tests -p no:cacheprovider -q --junitxml=audit_reports/b001_project_tests.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py audit_reports/test_extra_probes.py -p no:cacheprovider -q --junitxml=audit_reports/b001_audit_regressions.xml
.venv\Scripts\python.exe -B -m audit_reports.b001_password_smoke
node frontend/node_modules/typescript/bin/tsc --project frontend/tsconfig.app.json --noEmit --incremental false
node frontend/node_modules/typescript/bin/tsc --project frontend/tsconfig.node.json --noEmit --incremental false
node frontend/node_modules/vite/bin/vite.js build frontend --outDir ../audit_reports/b001_frontend_build
~~~

The full project run contains10 existing API,12 existing database,13 exam,25 timetable and19 validator cases plus37 new auth cases. Root conftest.py creates random test-only signing keys/passwords and enrolls users only in the isolated fixture database; tests exercise the actual login/JWT/session/role path without authentication dependency overrides. No test connects to .env's database. The SQLite migration was executed on an isolated database after removing only its disposable auth table, then verified against ORM columns/indexes. The password smoke tool selected a fresh TemporaryDirectory SQLite file, enrolled an existing fixture account, checked session revocation, then authenticated through the actual API.

Authoritative current evidence: [project log](b001_project_tests.log), [project JUnit](b001_project_tests.xml), [audit log](b001_audit_regressions.log), [audit JUnit](b001_audit_regressions.xml), [frontend checks](b001_frontend_checks.log), [operator smoke](b001_password_smoke.log), [machine-readable test ledger](b001_test_results.json), [engine/data scope hashes](b001_scope_verification.json). Standalone b001_auth_tests.xml/log is the final37-case focused auth run; b001_initial_backend.xml/log records22 passing updated backend cases before the final router-level gate. The first auth development run exposed DB dependency ordering; it was fixed and the final focused/full runs pass. Initial development failures are not unresolved regressions.

The existing Starlette TestClient/httpx and HTTP422-name deprecation warnings persist. Vite warns that redirected output is outside its project root and will not be emptied. None of these are failed checks. No extra packages were installed to silence warnings.

## Intentionally replaced assumptions

- The old API test treated no-header requests as an authenticated milestone mode and used X-User-Role to choose identity. It now logs in through the server, separately asserts anonymous401, and supplies real Student/Faculty JWTs plus forged Coordinator headers to prove they do not elevate permissions.
- Existing legitimate integration tests now use a real Coordinator token by default. Their CRUD/generation/move/constraint assertions were preserved, not relaxed.
- Audit checks needing legitimate business access now log in. Student visibility probes use real Student credentials, so the remaining B006 failures cannot be hidden by a new401. Administrator generation uses a real Administrator credential and correctly receives403. Anonymous/forged-header probes deliberately remain unauthenticated.
- The table/column test still asserts the original21 business tables and their column sets, then also asserts the auth migration and22nd model/table fields. FK, uniqueness, rollback and scheduling checks remain active.
- No final failure is attributed merely to the retired unauthenticated/header-only assumptions. All20 remaining failures below reproduce pre-existing audit findings with the appropriate authenticated setup.

## Passing audit subset

- test_unauthenticated_read_requires_login
- test_unauthenticated_write_requires_login
- test_forged_role_is_not_authentication
- test_faculty_without_identity_cannot_edit_any_instructor
- test_administrator_cannot_generate
- test_required_endpoint_exists[post-/auth/login-payload0]
- test_required_endpoint_exists[post-/auth/logout-payload1]
- test_published_direct_edit_rejected

The first five cases are the B001/identity/role subset. Endpoint-existence successes for login/logout alone are not proof of security; the37 substantive auth tests verify the full boundary. Published-entry immutability was already a passing baseline check.

## Remaining audit failures (not implemented in this task)

- test_student_cannot_read_generated_schedule
- test_student_list_contains_published_only
- test_required_endpoint_exists[get-/users-None]
- test_required_endpoint_exists[get-/audit-None]
- test_required_endpoint_exists[post-/import/courses-payload4]
- test_required_endpoint_exists[post-/schedules/1/publish-payload5]
- test_required_endpoint_exists[get-/schedules/1/export?format=csv-None]
- test_required_endpoint_exists[get-/schedules/1/export?format=pdf-None]
- test_weekly_slot_overlap_rejected
- test_unequal_slot_length_rejected
- test_bad_time_returns_validation_error
- test_grid_over_midnight_returns_validation_error
- test_invalid_day_returns_validation_error
- test_generated_schedule_immutable_through_master_data
- test_lab_contiguity_uses_clock_time
- test_mixed_enrollment_fallback_has_cohort_conflict
- test_exam_manual_override_persisted
- test_mutation_audit_written
- test_solver_rejects_overlapping_clock_slots
- test_default_app_recovers_orphan_on_startup

These cover B006 student unpublished/all-batch access, missing users/audit/import/publish/export endpoints, B002 invalid weekly topology/physical clashes, B017 malformed grid input, B004 published metadata mutation, B005 lab clock gaps, B003 mixed-enrollment graph, B015 exam override persistence, B016 incomplete master mutation auditing and B013 lazy startup recovery. Returning correct401 for anonymous access does not fix row-level disclosure to an authenticated Student. **No B002 work was begun.**

## Deployment prerequisites and practical limits

Follow [docs/authentication.md](../docs/authentication.md): set a unique strong JWT_SECRET_KEY, apply the selected additive auth-session migration after review, and enroll real passwords for existing trusted accounts. Existing seed hashes are placeholders, not a new default production credential. These prerequisites were prepared but not applied to production, as requested. Without the signing key or new table the existing deployment is not ready to serve authenticated sessions.

PostgreSQL runtime/migration execution, production TLS/grants, browser end-to-end interaction, multi-process load and deployment operations were not verified. The supporting table/migration is necessary for persistent revocation/idle expiry, not a broad schema rewrite. Expired rows need periodic deployment maintenance. Frontend reload requires login because tokens stay in memory; unreachable-server logout can clear only the local credential until remote expiry. Account management/audit screens still use mock data and do not administer real server accounts; self-service password-change UI/API and full row visibility/privacy controls are separate work. This report does not mark all FR-1/security requirements or other audit findings resolved.

## Modified and added files

Paths below are repository-relative; the machine-readable changed-file ledger also includes verification artifacts. No pre-existing test was deleted.

- .env.example
- audit_reports/BUG_REPORT.md
- audit_reports/test_audit_probes.py
- audit_reports/test_extra_probes.py
- backend/database.py
- backend/dependencies.py
- backend/main.py
- backend/models.py
- backend/routers/master_data.py
- backend/routers/schedules.py
- backend/schemas.py
- frontend/src/App.tsx
- frontend/src/components/AppShell.tsx
- frontend/src/pages/LoginPage.tsx
- frontend/src/services/api.ts
- frontend/src/services/http.ts
- frontend/src/services/mockApi.ts
- requirements.txt
- tests/test_backend_api.py
- tests/test_backend_db.py
- backend/auth.py
- backend/auth_password.py
- backend/routers/auth.py
- conftest.py
- db/migrations/001_auth_sessions.postgresql.sql
- db/migrations/001_auth_sessions.sqlite.sql
- docs/authentication.md
- tests/test_auth.py
- audit_reports/B001_FIX_REPORT.md (this report)
- audit_reports/b001_password_smoke.py (isolated operator-flow smoke check)
- audit_reports/b001_*.log, b001_*.xml, b001_test_results.json, b001_scope_verification.json and b001_changed_files.json (verification evidence).

The local .git/info/exclude also excludes the redirected B001 frontend build, without changing application files. Changes are left in the working tree for review; no B001 commit/push or next roadmap phase was performed automatically.
