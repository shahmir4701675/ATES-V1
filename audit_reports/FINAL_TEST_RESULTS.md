# Final acceptance test results

Assessment: 2026-11-21, Asia/Karachi. Audit-only; application and existing tests unchanged. [Requirement verdicts](FINAL_SRS_COMPLIANCE.md) and [acceptance gaps](REMAINING_ACCEPTANCE_GAPS.md) are separate from regression pass counts.

## Executed versus retained evidence

| Verification | Result | Evidence boundary |
| --- | --- | --- |
| Existing full project suite | **604 passed, 0 failed — retained baseline** | `batch4_project_tests.xml`; not rerun during this audit |
| Targeted fresh Python suite | **62 passed, 0 failed; 154 deselected; 54.19s** | 37 auth, 19 validator, 6 additional migration cases; seven migration cases in total are included within these 62 |
| Original audit suite, fresh once | **28 passed, 0 failed; 37.29s** | `final_acceptance/original_audit.xml` |
| Frontend rendering/resources/timezone tests | **5 passed, 0 failed** | Node/React SSR, not browser testing |
| Frontend application TypeScript | **Passed, exit 0** | Fresh `tsconfig.app.json --noEmit` |
| Frontend tooling TypeScript | **Passed, exit 0** | Fresh `tsconfig.node.json --noEmit` |
| Production frontend bundle | **Passed, exit 0** | Vite 6.4.5; 1,608 modules; build 3.43s; output confined to audit directory |
| Disposable SQLite migrations 001–005 | **7 passed, 0 failed** | Included in fresh 62; upgrade preservation, repeatable migrations where supported, failure rollback and fail-closed legacy snapshots |
| Five-role backend journey | **80 HTTP observations completed; no unexpected script assertions** | Real API/DB/workers; includes deliberately observed SRS failures, not 80 passing SRS requirements |
| Browser / keyboard / 360px / cross-browser | **Not Verified** | Two CUA initialization attempts failed before interaction |
| PostgreSQL migrations/transactions/concurrency | **Not Verified** | No safe isolated instance supplied; postgres/initdb/pg_ctl/psql/docker not discovered |

There are **90 distinct freshly executed Python test cases** (62 project subset + 28 original audit), not 604 + 62 additional independent project cases. Seven migration cases and the authentication cases overlap those totals. Five Node tests are reported separately. No failed existing test was removed, weakened or edited. The earlier baseline 604 and audit 28 are not combined with repetitions into inflated totals.

The full-suite baseline module counts are: B001 auth 37; B002 grid 87; B003 enrollment 60; B004 integrity 99; B005 labs 45; Batch 1 generation 23; Batch 2 accounts/access/publication/import/export 98; Batch 3 adjustments/integrity/validation-concurrency 49; Batch 4 configuration/generation/documentation 27; other core solver/validator/API/database tests 79. These sum to 604, not separate extra tests. The retained short-deadline/worker regression cases pass in that baseline; fresh reference-size trials below expose a different performance limit and do not establish a reappearance of the earlier import-boundary bug.

## Commands and reproducibility

Commands ran from the repository root unless noted. No production environment file, credentials or existing user database was loaded.

```powershell
.venv\Scripts\python.exe -B -m pytest tests/test_auth.py tests/test_validator.py tests/test_schedule_integrity.py tests/test_batch1_generation.py tests/test_batch2_imports.py tests/test_batch3_integrity.py -k 'test_auth or test_validator or migration or 005_upgrade' -p no:cacheprovider -q --junitxml=audit_reports/final_acceptance/targeted_security_constraints_migrations.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py audit_reports/test_extra_probes.py -p no:cacheprovider -q --junitxml=audit_reports/final_acceptance/original_audit.xml
.venv\Scripts\python.exe -B audit_reports/final_acceptance/api_acceptance.py
.venv\Scripts\python.exe -B audit_reports/final_acceptance/reference_server.py
.venv\Scripts\python.exe -B audit_reports/final_acceptance/measure_reference.py
# Stop first disposable reference server, preserve its result JSON, then:
.venv\Scripts\python.exe -B audit_reports/final_acceptance/reference_server.py --zero-soft
.venv\Scripts\python.exe -B audit_reports/final_acceptance/measure_reference.py
```

The second reference trial used buffered SQL timing rather than synchronous per-query file writes; the checked-in audit fixture contains this final instrumentation. `reference_default_results.json` preserves the first trial; `zero_soft/reference_results.json` preserves the separate zero-weight trial. Running the measurement driver writes `reference_results.json`; copy results into a new evidence directory between runs, and stop the prior disposable instance using its generated temporary `stop` file before starting another. Both modes generate fresh temporary SQLite data and random credentials. Passwords were not copied into retained artifacts; temporary credential files were removed after graceful shutdown.

From `frontend`:

```powershell
node --test tests/batch4.test.cjs
node node_modules/typescript/bin/tsc -p tsconfig.app.json --noEmit
node node_modules/typescript/bin/tsc -p tsconfig.node.json --noEmit
node node_modules/vite/bin/vite.js build --outDir ../audit_reports/final_acceptance/frontend_build
```

Vite's outside-root output notice was informational; no existing output directory was emptied. The fresh checks and logs are in `final_acceptance/`; application `dist` was not overwritten. PDF contents were inspected with installed pypdf; actual selected PDF pages were rendered with installed `pdftoppm`, then visually inspected. PNG evidence: `reference_group_preview.png` and `exam_preview.png`. No new dependencies were installed.

The supplemental enrollment measurement used inline Python through `.venv\Scripts\python.exe -B -`, the same real HTTP helper and an independent `sqlite3` before/after count. Its original inline program was not retained as a standalone command file: this is a reproducibility limitation, not an invented test run. Procedure: restore the disposable reference's 80-course/3,000-student dimensions after the unrelated course-import trial, select 5,000 absent cross-batch student/offering pairs, submit UTF-8 `offering_id,student_id` rows to `/import/enrollments`, confirm the persisted preview, and independently count the increment. Exact measured outputs are retained in `enrollment_import_performance.json`. No production cleanup or deletion was performed.

## Reference dataset and environment

[Machine details](final_acceptance/environment.json): Windows 11 Pro 10.0.22621; four physical/eight logical CPU cores; 15.69 GiB RAM; one genuine Uvicorn API process and spawned solver processes; disposable file-backed SQLite; loopback HTTP. This meets/exceeds the SRS reference hardware minimum; it is not a Linux/PostgreSQL/TLS production benchmark. Synthetic but real persisted records, not mocked scheduling output:

- 150 offerings, 80 courses, 40 instructors, 30 batches of 100 students, 60 rooms, 48 one-hour weekly slots across six weekdays; lunch slots blocked; explicit instructor unavailability.
- 3,000 linked student accounts; 15,010 enrollment links including ten cross-batch repeater/elective links; 80 exam courses and ten exam sessions across five dates.
- 210 required timetable entry rows, including two-slot labs. All hard constraints enabled; seed 42. Timetable limit 120s; exam limit 30s. Trial one uses catalogue soft weights; trial two deliberately sets soft weights zero as a diagnostic.
- After the supplemental import, the disposable enrollment count increased from 15,010 to 20,010; that later mutation was **not** part of generation inputs. The 5,000-course import is also a separate workload, not falsely included in the original reference-size model.

Independent oracle/witness code imports no application constraint, solver or validator helper. It uses minute intervals, concrete room capacities/types, explicit memberships, workload totals, exact session/seat counts and lab continuity. A first-fit/modular witness confirms both reference problems have a hard-feasible solution. Witness construction is outside the application's measured time and never used to save a fake Generated result.

## Measured performance and scheduling outcomes

| Workload | Observed result | SRS decision |
| --- | --- | --- |
| Reference timetable, default soft weights | 120.348s end-to-end; `TimedOut`, no Generated result; reported run 120.21s | P-2 incomplete; no default-weight reference success; overhead includes polling/terminal cleanup |
| Reference timetable, zero soft weights | 91.387s; Generated, 210 entries; zero independent H01–H10 violations; reported run 84.33s | Under120s, above typical60s target; diagnostic only |
| Reference exams, default soft weights | 30.225s; `TimedOut`, no Generated result | P-3 failed completion target |
| Reference exams, zero soft weights | 30.273s; `TimedOut`, no Generated result | P-3 still failed; removing soft weights did not resolve it |
| 50 distinct authenticated users, four waves of50 schedule reads | 200/200 HTTP200; mean8.153s, p95 **12.239s**, max12.600s | **P-1 failed**, target p95<=2s |
| Ordinary reads during generation | 30 baseline vs30 during; means .208s/.248s, mean slowdown18.84%; p95 .269s/.344s, slowdown27.57% | P-8 partial; mean passes but p95 exceeds20%; metric must be specified |
| Reference timetable CSV / PDF | .225s / .771s | Tested exports meet5s |
| Reference all-batch PDF | .900s;30 pages | Tested export meets30s |
| Tiny exam CSV / PDF | .042s / .058s; actual contents inspected | Meets5s on tiny case; 80-course exam export not measured |
| Reference lock-only independent revalidation | .483s, HTTP200 | Meets1s for this operation; full reference lab/exam movement not timed |
| 5,000 courses, buffered query instrumentation | Preview .511s + confirm3.496s = **4.008s**, 5,000 persisted | Meets15s |
| 5,000 enrollments, buffered instrumentation | Preview .379s + confirm7.975s = **8.355s**, SQL increment5,000 | Meets15s |
| Original 5,000-course trial with synchronous per-query disk logging | **15.803s** | Perturbed diagnostic retained; not claimed to isolate an app defect or a pass |
|100 direct indexed entry lookups | mean .899ms, p95 .996ms, max6.959ms | This query meets500ms; other view queries/PG plans unverified |
| Genuine worker cancellation | HTTP200 in .133s; stateCancelled; worker stopped; **0 entries saved** | Verified for exercised run; existing race/lease/commit fencing tests retained |

No 80-course application exam solution was produced. The oracle's feasible witness cannot substitute for that missing output. TimedOut/Cancelled with an Infeasible schedule header does not prove the CSP unsatisfiable. No unexecuted double-size, sustained multi-hour, distributed, PostgreSQL or production load test is claimed.

## Correctness, workflow and safety observations

Fresh negative validator tests cover each H01–H10/E01–E05, mandatory non-disablement and valid seeds. Retained weekly-grid/lab/membership tests cover physical overlap, adjacent/gapped/duplicate slots, malformed external grids, cross-midnight values, three-slot labs, availability and mixed/repeater enrollments. The fresh 210-entry timetable and actual tiny generated timetable/exams pass a separately implemented oracle. Enabled optional hard constraints were checked on those outputs; disabled hard-rule semantics and soft behavior retain dedicated expected-result test evidence.

The real five-role journey verified account creation through Administrator API, Coordinator CRUD/config/import/generation, Faculty own availability, Student own batch, Approver publication, regeneration locks, actual room movement/override, exact undo, publication persistence, prior archival, Published-edit denial, CSV/PDF and actor-attributed audit. Wrong-role generation/publication, unrelated instructor/batch and stale publication requests were refused. Relevant room capacity change prevents stale publication (409); unrelated unused-course edit correctly does not. A fresh application/client session sees persisted history. Reference publication followed by current capacity reduction retains original capacity150 and unchanged valid historical entries.

Important negative acceptance evidence:

1. **False optimum:** tiny hard-valid DSATUR exam result says `optimal`; an independently hard-valid alternative improves the only positive ES01 preference. See `heuristic_optimal_counterexample.json`. A heuristic feasible result is not a mathematical optimum. Zero-objective CP-SAT optimality is only trivial objective optimality.
2. **Lifecycle:** closing the term leaves a Published schedule Published, contrary to SRS Table26. An empty Planned-term generation creates Infeasible instead of reporting defects while remaining Draft.
3. **Input/administration:** instructor email `not-an-email` receives201; historical offering instructor reassignment receives409 due to the composite FK; no offering deactivation alternative exists. The latter refusal protects history and must not be “fixed” by disabling guards.
4. **Audit/time/localization:** conflict CSV is downloaded locally without backend EXPORT audit; PDF generated-at footer is UTC; complete resource extraction/week-start/manual screenshots remain unfinished.

The first exploratory journey incorrectly expected a409 after importing an **unused** course. Inspection showed that edit is outside the captured scheduling inputs; publication200 was correct. The initial JSON/log is preserved. The audit-only probe was corrected to distinguish unrelated edits from relevant room capacity changes, then rerun; no application/existing-test assertion was weakened.

## Database, browser and preservation limits

Seven migration cases ran on disposable SQLite only, exercising 001 auth,002 snapshots/atomic failure,003 runs,004 imports and005 integrity/rollback. Preserve original001–004 and apply005 only according to its upgrade preconditions. Tests do not authorize running a migration on an existing user database. Supporting stage nonce PK and snapshot archival denormalization need approved schema exceptions if literal SRS key/3NF wording is retained. A scan finding no full composite FK index does **not** prove an unindexed lookup: individual component indexes exist, and the measured schedule lookup uses its schedule index.

No safe PostgreSQL service/toolchain was available. PostgreSQL migration syntax, triggers, transactions, publication, rollback, connection grants and concurrency remain **Not Verified**, not inferred passes from dialect source files. SQLite concurrency/race tests retain baseline evidence; no fresh cross-process PostgreSQL claim is made.

Browser tool inventory and, after reset, direct tab creation both failed with `failed to write kernel assets: The system cannot find the path specified. (os error 3)`. No user workflow, browser refresh, desktop layout,360px, keyboard focus, screen reader, WCAG, mobile or browser-print interaction executed. API restart persistence and SSR are distinct narrower evidence. Actual PDF files were rendered and inspected for representative English layouts; complex-script shaping and printing remain unverified.

[Source preservation](final_acceptance/source_preservation.json): all120 application/existing-test/migration/frontend source hashes captured at audit start match audit end. Existing dirty work was preserved. Only this acceptance package, audit-only drivers/results, PDF previews and scoped audit build output were created. The temporary Uvicorn server shut down, and its plaintext disposable password files were removed. No production DB, legacy schedule, credentials, application code, existing test or deployment was modified.
