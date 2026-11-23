# B003 — Mixed explicit and inferred exam enrollment fix

21 November 2026 (Asia/Karachi). Scope: B003 only. No production database, account, environment file or persisted schedule was modified. Tests use isolated SQLite databases and in-memory datasets. B004 was not started.

**B003 is resolved in the implementation and isolated regression verification, under the SRS A-3/A-4 enrollment assumptions described below.** This does not clear unrelated audit findings or establish deployment acceptance.

## Root cause and correction

The old membership builder counted enrollment rows rather than distinct students. Fully enumerated offerings received `student:*` identities, while missing/partial offerings received a `batch:*` marker without the known students of that batch. Intersecting these sets missed required mixed-enrollment graph edges. The E01 and E02 validators reused the same helper, so they reproduced its omissions.

Membership now follows SRS A-4 with these explicit rules:

- Enrollment completeness is determined per offering, using distinct student IDs compared with its declared `enrolled_count`.
- A fully enumerated offering retains exactly its explicit students. Two complete disjoint electives do not conflict merely because they share a batch.
- A missing/partial offering includes its explicit students, all students evidenced by raw enrollments in the same term/batch's offerings, and a `batch:*` witness for anonymous students. Evidence from an inactive course remains useful without scheduling that inactive course.
- Cross-batch students and repeaters keep the same global `student:*` identity. Multiple offerings of one course are unioned for exam membership; that course contributes one exam to a student's daily count.
- Inferred membership is not fed back into other batches' rosters. There is no transitive expansion through a course offered to several batches.
- Duplicate enrollment rows cannot falsely establish completeness, inflate shared-student metadata or change scheduling counts. Existing declared offering counts remain the source of E03 seat requirements.

The existing sorted NetworkX graph construction now consumes the corrected sets. DSATUR, colour/session mapping, CP-SAT fallback and its E01/E02 model constraints use the same consistent identities. Their algorithms were not rewritten. E01 remains mandatory even if the configuration says disabled; E02 remains configurable and uses its configured maximum when enabled.

E01/E02 validation now uses a separate raw-record relational calculation in `engine/exam_membership_validation.py`. It joins each explicit enrollment to incompletely enumerated offerings in the same term/batch and builds independent student-to-course relationships, including anonymous cohort witnesses. It never calls the solver's `course_students`, conflict graph, colouring or assignment model. Validation selects enrollment evidence using each exam session's term. Tests deliberately replace the solver helper with an empty result and still require exact expected E01/E02 violations.

## Files modified for B003

- `engine/models.py`: distinct-student completeness and conservative exam membership representation. The surrounding B002 interval/duration implementation is unchanged.
- `engine/constraints.py`: E01/E02 validation reads the independent enrollment oracle; one import was added. H01–H10, S01–S06, E03–E05 and exam soft-constraint code are unchanged.
- `engine/exam_membership_validation.py` (new): independent raw-enrollment oracle.
- `data/seed_exam.json`: moved only saved sample exams 4 and 5 to sessions 4 and 6. This repairs a sample schedule that becomes invalid under the correct A-4 semantics; no actual database was updated.
- `tests/test_exam_scheduler.py`: assert all ten required edges and five colours for the partial-enrollment sample, rather than its old seven-edge assumption.
- `tests/test_validator.py`: retain the E02/E04 and mandatory-rule checks while additionally asserting the newly detected student/daily violations; explicitly construct the intended room collision after the sample repair.
- `tests/test_exam_membership.py` (new): hand-specified membership/edge oracles, real scheduling through both paths, independent validator rejection, duplicate/order invariance, term isolation and inactive-source evidence.
- `audit_reports/BUG_REPORT.md`: resolution annotation with historical evidence preserved.
- This report and `audit_reports/b003_*` logs/XML/JSON verification artifacts. Generated frontend output is locally excluded from Git.

`engine/exam_scheduler.py`, the backend, frontend source, authentication code and existing B001/B002 regression test files were not modified for B003. All earlier uncommitted work remains present.

## Regression coverage and verification

New cases cover two missing same-batch offerings; complete/missing and partial enrollment mixtures; complete disjoint electives; cross-batch/repeater students; duplicate records that would falsely imply completeness; multiple offerings; unrelated batches; avoiding transitive roster expansion; zero-student membership; term isolation; and inactive-course evidence. Completed schedules are checked against manually specified student/course relationships, exact course completeness, session exclusivity and daily counts, independently of production membership helpers.

Both DSATUR and naturally triggered CP-SAT fallback are exercised with real algorithms. A locked exam forces fallback without mocking a schedule. Two mixed-membership exams can share a date under a daily limit of two; three cannot. A configured maximum of three permits three, and disabling E02 preserves its SRS configurable behavior. E01 cannot be disabled, and a one-session mixed-enrollment run fails rather than returning conflicting exams. Existing room allocation, soft preference, lock and determinism tests remain in the verification suite.

The final focused exam suite passed **92 tests**, including **60 new B003 cases** and all 32 existing exam/validator cases. See `b003_exam_tests.log` and `.xml`.

The original `test_mixed_enrollment_fallback_has_cohort_conflict` passed. See `b003_targeted_audit.log` and `.xml`.

Full audit results: **15 passed, 13 failed**, compared with B002's 14 passed/14 failed. The only changed audit outcome is the fixed B003 regression; no audit test newly fails. See `b003_audit_comparison.json` and `b003_audit_regressions.log` / `.xml`.

The final full project suite passed **263 tests, 0 failed**, including all **60 B003**, **37 B001 security**, and **87 B002 grid/scheduling** regressions. Final runtime was 295.98 seconds. See `b003_project_tests.log` / `.xml` and `b003_test_results.json`. Combined distinct final pytest cases across the project and full audit: **291 executed, 278 passed, 13 failed**. Focused/repeated runs are not added again. Five existing Starlette/httpx and HTTP-422-name deprecation warnings are not failures.

Frontend application and tooling TypeScript checks and the Vite production build passed, with unchanged frontend sources. See `b003_frontend_checks.log`.

Verification commands from the repository root:

~~~powershell
.venv\Scripts\python.exe -B -m pytest tests -p no:cacheprovider -q --junitxml=audit_reports/b003_project_tests.xml
.venv\Scripts\python.exe -B -m pytest tests/test_exam_membership.py tests/test_exam_scheduler.py tests/test_validator.py -p no:cacheprovider -q --junitxml=audit_reports/b003_exam_tests.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py -p no:cacheprovider -q -k mixed_enrollment --junitxml=audit_reports/b003_targeted_audit.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py audit_reports/test_extra_probes.py -p no:cacheprovider -q --junitxml=audit_reports/b003_audit_regressions.xml
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.app.json --noEmit
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.node.json --noEmit
node frontend/node_modules/vite/bin/vite.js build frontend --outDir ../audit_reports/b003_frontend_build
~~~

The first development run exposed obsolete sample assumptions: seven graph edges, three colours, and saved simultaneous exams valid only under the faulty membership helper. These were corrected with stricter edge/violation assertions and valid sample placements. No failing case was removed, skipped, xfailed, or relaxed to allow a conflicting schedule. Initial logs are historical development results, not final verification evidence.

## B001/B002 preservation

`b003_preservation_baseline.json` and `b003_preservation_results.json` confirm 16 preserved authentication, API, frontend and weekly-grid files are unchanged. `b003_preserved_sections.json` and `b003_preserved_section_results.json` confirm the sections surrounding `course_students` in `engine/models.py`, all timetable constraint code before E01, and all constraints from E03 onwards are unchanged. The sole additional oracle import is excluded from that section comparison. All 17 original B001 preservation hashes match, recorded in `b003_b001_hash_verification.json`. All 37 B001 and 87 B002 tests passed in the final full run.

## Remaining audit failures and limitations

The 13 retained failures concern:

- Student access to generated schedules and unpublished schedule lists (two tests).
- Missing user, audit, import, publish and CSV/PDF export endpoints (six tests).
- Published master-data immutability (B004).
- Lab clock-time contiguity (B005).
- Exam manual-override metadata persistence.
- Master-data mutation auditing.
- Default lazy-app recovery of interrupted generation.

They remain genuine unresolved SRS findings and are not excused as B003 assumptions. The full audit is not green and institutional acceptance is not claimed.

The schema has no explicit enrollment-completeness flag or authoritative batch roster in engine inputs. The fix therefore relies on distinct count versus truthful declared enrollment counts (A-3), and conservatively uses known raw enrollment evidence within each term/batch (A-4). Missing information may create additional required conflicts, particularly around repeaters; supplying complete enrollment lists preserves genuinely disjoint electives. Unrecorded cross-batch enrollment cannot be reconstructed without institutional evidence. Anonymous cohort witnesses are not individual seat counts. No E03 seat-count redesign or reconciliation of inconsistent declared counts was attempted.

The saved sample schedule repair is not an automatic production migration. Previously saved schedules based on incomplete enrollment assumptions may now fail validation and need regeneration. Live PostgreSQL, production data, reference-size performance and deployment acceptance were not tested. No unrelated roadmap feature was implemented, and B004 was not started.
