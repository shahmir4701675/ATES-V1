"""Produce the audit's explicit, independently classified requirement register.

Audit artifacts only. No imports from or writes to application modules/databases.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
inventory = json.loads((HERE / 'requirement_inventory.json').read_text(encoding='utf-8'))
F, P, N, I, U = ('Fully verified', 'Partially verified', 'Not implemented', 'Incorrect', 'Not verified')
rows = {}

def add(ids, status, evidence):
    for rid in ids.split():
        assert rid not in rows, rid
        rows[rid] = (status, evidence)

add('FR-1.1 FR-1.2 FR-1.3 FR-1.4 FR-1.5', F, 'A: real JWT/session, bcrypt, lockout, expiry, logout and role-negative tests; backend/auth.py and routers/auth.py.')
add('FR-1.6 FR-1.7', F, 'B: tests.test_batch2_accounts (17 cases); J: accounts for all roles created through authenticated administration; backend/routers/accounts.py.')
add('FR-1.8', P, 'J/A verify server permission enforcement; role-aware navigation exists. Actual menu/button visibility and keyboard traversal were not browser-tested (W).')
add('FR-2.1 FR-2.2 FR-2.4 FR-2.5', F, 'B: tests.test_backend_api, tests.test_batch3_validation_concurrency; J: authenticated CRUD and invalid-input responses; backend/routers/master_data.py and schemas.py.')
add('FR-2.3', P, 'CRUD, uniqueness/workload bounds implemented and exercised (B/J); R accepted instructor email not-an-email with HTTP 201. Email-format validation remains incomplete.')
add('FR-2.6', P, 'J/B verify dates and at-most-one Active guard. Closing the only term leaves zero Active; FR wording exactly one conflicts with SRS database at-most-one wording (G04).')
add('FR-2.7 FR-2.9', F, 'B: tests.test_weekly_grid (87 cases), tests.test_lab_contiguity (45); V/J: actual fixed-grid generation and exact required session counts; engine/weekly_grid.py and engine/validator.py.')
add('FR-2.8', P, 'Creation/duplicate checking verified (B/J). A referenced offering instructor change returns 409 under the historical composite FK (X); a future-assignment/revision workflow is unresolved.')
add('FR-2.10', F, 'B: tests.test_exam_membership (60 cases); J/R: explicit enrollments persisted and used; L: 5,000 new enrollment links independently counted in SQL.')
add('FR-2.11', P, 'Referenced deletions are refused and ordinary entities deactivate (B). CourseOffering has no active/deactivation field; referenced offerings can only be retained (master_data.py delete_offering).')
add('FR-2.12', P, 'List search/sort/pagination code exists; not every master list/default-25 browser interaction has executed acceptance evidence (W).')
add('FR-3.1', P, 'J/B verify own-instructor read/write and deny other/unlinked identities. Weekly-grid availability UI has not been exercised in a browser (W).')
add('FR-3.2 FR-3.3', F, 'B: tests.test_batch2_schedule_access ownership/availability cases; J: Coordinator/Faculty access; V/R: absent availability rows default available and marked rows respected.')
add('FR-3.4', P, 'Immutable snapshots preserve original availability (B/R); actual frontend warning visibility/wording was not browser-tested (W).')
add('FR-4.1 FR-4.2 FR-4.3 FR-4.4 FR-4.5', F, 'B: tests.test_batch2_imports (28) covers all six types, UTF-8/size/template/ownership/rollback/history. J: valid/rejected row confirmation; R/L: genuine 5,000-row persistence; backend/csv_imports.py and routers/imports.py.')
add('FR-5.1 FR-5.2 FR-5.4 FR-5.5 FR-5.6 FR-5.7 FR-5.8', F, 'B: tests.test_batch4_config_generation (25), tests.test_batch3_validation_concurrency; J: persisted configurations/exam sessions and rejected malformed grid; backend/routers/master_data.py, schemas.py and rule catalogue validation.')
add('FR-5.3', P, 'Mandatory protection/config audit verified (A/B); optional-rule confirmation UI exists but has no browser acceptance execution; direct API has no explicit confirmation token (W).')
add('FR-6.1', I, 'J: empty Planned-term generation accepted (202) and becomes Infeasible, whereas SRS Figure 12 requires input defects before solve with status staying Draft; no complete Draft preflight workflow (G03).')
add('FR-6.2 FR-6.3 FR-6.4 FR-6.5 FR-6.7 FR-6.8 FR-6.9 FR-6.10', F, 'B: tests.test_timetable_solver (25), test_batch1_generation (23), Batch3/4 fencing; J: real worker generation, lock-preserving regeneration and persistence; R/V: 210 generated entries independently satisfy H01-H10. Default-weight reference performance is separately not accepted (P-2).')
add('FR-6.6', P, 'R: real server cancellation stops worker in 0.133s and saves no entries; B verifies races/deadlines. Browser elapsed/progress/loading/cancel messaging not executed (W).')
add('FR-7.1 FR-7.2 FR-7.3 FR-7.4', F, 'B: tests.test_exam_scheduler (13), test_exam_membership (60); J/V: generated exams checked using independent explicit student-set, interval, capacity and exact-seat oracle. Reference-size completion not verified successfully (P-3).')
add('FR-7.5', P, 'B covers fallback/session shortfall and conflicts. Reference timeouts expose terminal TimedOut but schedule header Infeasible; useful per-course/session-shortfall explanations for every failure were not demonstrated.')
add('FR-7.6', P, 'B tests ES objectives and room selection. J/O proves a hard-feasible alternative improves enabled ES01 while returned greedy result does not; global soft optimality is unproven.')
add('FR-7.7', P, 'J persists correct exam entries/allocations, but DSATUR returns solver_status=optimal without an optimality proof, including a strictly improvable ES01 example (O/G02).')
add('FR-8.1', P, 'Independent gates work during generation/publication/edits (B/J). Complete user-triggered validate-any-version/report workflow is not demonstrated; historical untrusted versions fail closed.')
add('FR-8.2', P, 'B verifies conflict API; frontend client CSV code exists. Browser filtering/download unexecuted; conflict CSV bypasses backend export audit (G05/W).')
add('FR-8.3 FR-8.5 FR-8.6', F, 'B: tests.test_batch3_adjustments (21); J: Generated-only real room move, persisted override, lock/unlock, undo and regeneration; Published editing refused. backend/manual_edits.py.')
add('FR-8.4', P, 'J real small-fixture move validates; R reference lock-validation=0.483s. Complete physical lab/exam move at reference size was not timed; P-4 remains partial.')
add('FR-8.7', P, 'J exact undo succeeds; B validates revision checksums/concurrent edits. Pre-upgrade versions restore first tracked pre-edit state, not provable original pre-upgrade generation state.')
add('FR-9.1', I, 'J: closing term leaves Published status unchanged; SRS Table 26 requires Archived. Draft creation/duplicate/preflight transitions are also incomplete (G03/G04).')
add('FR-9.2 FR-9.3 FR-9.4', F, 'B: test_batch2_publication (12), schedule_access (23), integrity (99). J: Approver-only snapshot validation, atomic previous archival and own-scope Published-only access; second-client restart sees state.')
add('FR-9.5', P, 'B/J retain numbered history and archive views. No complete duplicate-to-Draft/return-to-earlier-version workflow; legacy rollback baseline cannot be inferred.')
add('FR-9.6', P, 'Review data/receipt API exists (B); actual Approver review summary and confirmation before publishing were not browser-tested (W).')
add('FR-10.1 FR-10.2 FR-10.3 FR-10.4 FR-10.5 FR-10.6 FR-10.7', P, 'Source and D server-rendered tests support grid stacking, filters, role defaults and metadata. J proves backend filters/scopes; actual rendered browser workflows, statuses and refresh behavior remain untested (W).')
add('FR-10.8', U, 'W: no browser initialized; 360px horizontal overflow, interaction and readability were not measured. Responsive classes are insufficient evidence.')
add('FR-11.1 FR-11.2 FR-11.3 FR-11.4', F, 'B: test_batch2_exports (18), including scope/filter/long Unicode/grouping cases. J/R/F: real CSV and A4 landscape PDF, filenames, metadata, allocation rows and representative rendered pages; 30 batch pages. Local-time footer caveat tracked under DB-8/I18N.')
add('FR-11.5', P, 'Schedule export endpoint logs real exports (B/J). ConflictReportPage.tsx creates its CSV locally without any backend EXPORT event (G05).')
add('FR-12.1', P, 'A/B/J cover authenticated CRUD, account, import, config, generation, movement and publication events. Client-only conflict CSV export has no authoritative audit event (G05).')
add('FR-12.2 FR-12.3', F, 'B: accounts and Batch3 integrity tests; J: Administrator-only audit retrieval; M: append-only update/delete guards and transactional audit persistence. backend/mutation_audit.py and db/migrations/005*.')

for n in range(1,28):
    add(f'UR-{n:02}', P, 'Related FRs above have backend/test evidence (A/B/J/R); end-user completion across browser login, navigation, forms, feedback and downloads was not executed (W). Specific functional gaps also apply where noted in the related FR.')
for n in range(1,18):
    add(f'UC-{n:02}', I if n==10 else P, 'J executes real backend workflow portions with authenticated roles; no browser basic/alternative-flow acceptance (W). UC-10 additionally has wrong input-defect lifecycle (FR-6.1/G03).' if n==10 else 'J/B execute backend basic/negative workflow portions; actual complete UI basic/alternative flows, focus and feedback were not executed (W). Consult matching FR rows for known gaps.')
for n in range(1,11):
    add(f'H{n:02}', F, f'A: tests.test_validator negative case for H{n:02}; B: weekly-grid/lab/timetable suites; V independently recomputes actual intervals, references, counts, availability, rooms and workloads on 210 real generated entries. Enabled hard constraints only; no source helper reused by oracle.')
for n in range(1,7):
    add(f'S{n:02}', F, f'B: tests.test_timetable_solver dedicated S{n:02} expected-placement/objective tests and zero-weight/disabled/hard-priority cases; S05 additionally has real API test_batch1_generation previous-unlocked/locked/absent-history cases. This verifies soft preference behavior on fixtures, not universal optimality.')
for n in range(1,6):
    add(f'E{n:02}', F, f'A: tests.test_validator negative case for E{n:02}; B: membership/exam suites; J/V independently check actual exam intervals, explicit shared students, daily limits, room capacity/seats, exclusive rooms and complete course counts. Reference 80-course completion failed separately (P-3).')
add('ES01', P, 'O/J: distinct-day alternative has zero hard violations and improves the only positive soft preference; returned DSATUR result is nevertheless labelled optimal. Preference tests exist (B); complete API optimization guarantee is unproven.')
add('ES02 ES03', F, 'B: tests.test_exam_scheduler dedicated room-count and same-building expected-result cases; engine/exam_scheduler.py allocation preferences. These are preferences, not mathematical optimality claims.')
add('P-1', I, 'R: 50 distinct authenticated users, four waves, 200/200 HTTP200; p95 12.239s exceeds <=2s. Single local Windows/SQLite instance, real published own-batch schedule read.')
add('P-2', P, 'R: default-weight feasible reference input times out at 120.348s with no schedule. Zero-soft diagnostic generates in 91.387s (<120 but >typical60). One sample cannot establish typical performance; default soft workload not accepted.')
add('P-3', I, 'R: 80-course reference exam timed out without a schedule at 30.225s default and 30.273s zero-soft. V supplies a hard-feasible independent witness; timeout is not a proof of infeasibility.')
add('P-4', P, 'J: small actual move works. R: reference lock-only validation 0.483s; full physical multi-slot move at reference size not measured.')
add('P-5', F, 'R/L: buffered-instrumentation real preview+confirmation of 5,000 courses=4.008s and 5,000 enrollment rows=8.355s, all persisted; <=15s. Initial synchronous per-query logging trial=15.803s is retained as perturbed diagnostic, not a passing run.')
add('P-6', P, 'R/F: reference timetable CSV .225s, PDF .771s, 30-batch PDF .900s meet targets. Tiny real exam exports inspected, but reference 80-course exam export unavailable because generation timed out.')
add('P-7', P, 'R: 100 indexed schedule-entry lookups p95 .996ms/max6.959ms. Not all SQL statements behind every schedule view or PostgreSQL plans were measured.')
add('P-8', P, 'R: separate actual solver process; paired 30-read trial mean slowdown18.84% but p95 slowdown27.57%. SRS aggregation is unspecified; no unconditional <=20% acceptance claimed.')
add('SAF-1 SAF-2', F, 'B: integrity, cancellation/concurrency/publication/rollback negatives; J/R: stale publication 409, real worker cancellation leaves zero entries and earlier version intact. Independent validator and fenced atomic save remain enforced.')
add('SAF-3', P, 'Confirmation components/source exist; destructive/irreversible consequence wording and keyboard confirmation were not browser-tested (W).')
add('SAF-4', P, 'B/J/R prove modern snapshots immutable across room edits/restarts and Published/Archived direct edits denied. Legacy versions lacking recoverable original context remain unverified; no automatic rewrite was attempted (G08).')
add('SAF-5', U, 'No daily/7-retention operational backup scheduler or completed restore drill was executed. Installation guidance alone is insufficient operational evidence.')
add('SAF-6', P, 'J/B retain and read history; restoring an older Published version through a reviewed new version is not a complete demonstrated workflow; legacy original inputs may be unavailable.')
add('SEC-1 SEC-2 SEC-3 SEC-4', F, 'A: 37 fresh authentication/session/forgery/inactive/lockout/role tests. B/J: real account and role workflows; no password/token values copied into audit outputs. Public login/docs are intentional entrypoints, not protected business functions.')
add('SEC-5', U, 'Local disposable server used HTTP only. Production TLS>=1.2, redirect/refusal, proxy/header/cookie settings and certificates were not tested.')
add('SEC-6', P, 'A/B verify many malformed values/ORM transactions; malformed instructor email is accepted (R). Browser escaping/injection acceptance was not executed (W).')
add('SEC-7', F, 'B: tests.test_batch2_imports file-size/type/encoding/staging ownership cases; J/R/L real UTF-8 CSV parsed as data and staged in relational storage, not executable/public uploads.')
add('SEC-8', P, 'A verifies no fallback secret; fixture supplies random settings without loading production credentials. PostgreSQL restricted grants and deployment secret management were not exercised.')
add('SEC-9', P, 'A/B/M verify immutable actor-attributed security logs and denied modifications. Required action completeness has conflict-export gap (FR-12.1); PostgreSQL triggers unexecuted.')
add('SEC-10', F, 'A/B/J/R: trusted linked identity, own-batch/own-instructor Published filtering and cross-scope403; account password hashes never returned. Personal fields match scheduling purpose in inspected schema.')
add('DB-1', F, 'B/M/X: relational models cover all 21 SRS business tables plus seven supporting tables; real imports, snapshots, runs, approvals/history persist in SQLite across client/application restart (J). Exports/guides are derived files, not sole business storage.')
add('DB-2', P, 'Relational decomposition/composite assignment FK inspected (B/X); no exhaustive functional-dependency/3NF proof or PostgreSQL enforcement run. Snapshot JSON is a deliberate versioned archival denormalization requiring documented exception.')
add('DB-3', P, 'B/M verify integer business PKs and enforced FKs. Supporting import_stages uses VARCHAR(64) nonce PK; literal all-tables integer-key clause needs an accepted exception (X).')
add('DB-4', P, 'B/M exercise CHECK/UNIQUE/NOT NULL/FK negatives in SQLite. Full every-column parity and PostgreSQL constraints were not executed.')
add('DB-5', P, 'B/M prove referenced deletion and append-only log guards. Referenced offerings lack the required deactivation alternative (FR-2.11); PG behavior unexecuted.')
add('DB-6', F, 'B: failed save/validation/cancellation/concurrent version tests; M: transactional migration rollback. J/R: authoritative entries/receipt commit together, cancelled result has zero entries.')
add('DB-7', P, 'M/X inspect FK/schedule indexes; R confirms actual indexed lookup. Composite offering FK has individual component indexes, not a matching full composite index; do not infer an unindexed FK from that alone. All-view/PG performance unverified.')
add('DB-8', P, 'D verifies frontend Asia/Karachi formatter; real UTF-8 CSV accepted. F shows human-readable PDF generated-at footer in UTC, not specified Asia/Karachi; complex-script shaping remains untested.')
add('DB-9', P, 'M: seven disposable SQLite upgrade/idempotency/rollback cases across001-005. ORM create_all also exists; real upgraded PostgreSQL and deployment migration-only policy are unverified.')
add('C-1', F, 'Inspected requirements/lock/package files and actual B/J/R executions use Python, OR-Tools CP-SAT, NetworkX, FastAPI/SQLAlchemy, React and Tailwind; no substitute solver or mock scheduling results used.')
add('C-2', P, 'J/R prove REST/JSON authority and real downloads; production HTTPS unverified (SEC-5), and client conflict export has no authoritative export event.')
add('C-3', P, 'Windows SQLite executed; SQLAlchemy/dialect migrations present. Linux/PostgreSQL compatibility is source-supported only, not executed.')
add('C-4', F, 'B: shared end-to-end deadline/cancellation races/startup tests; R observes terminal TimedOut with no valid result. Measured ~0.2-0.35s polling/cleanup overhead is reported; no late result saved.')
add('C-5', P, 'A verifies salted hashes and protected API authorization. Encrypted production traffic was not verified (SEC-5).')
add('C-6', F, 'B: 87 weekly-grid and45 lab regressions; A/V: actual clock-time continuity, equal duration, no malformed/cross-midnight slot acceptance and whole-session counts.')
add('C-7', U, 'Team composition, semester delivery and complete free-tool/licensing history are external project facts not independently verified.')
add('C-8', P, 'Existing62-page SRS and UML/requirement inventory inspected; complete original LaTeX build/UML2 validation was not reproduced.')
add('C-9', U, 'W: no actual Chrome/Firefox/Edge/Safari run; no cross-browser acceptance evidence.')
add('Q-01', P, 'A supplies one negative for every H/E; V validates real reference timetable and tiny exams. No completed reference-size application exam output; independent witness is not an app output.')
add('Q-02', P, 'B verifies startup recovery/idempotency and safe failures. No statistically defined99% valid-run campaign; reference workloads timed out and heuristic optimal metadata is incorrect.')
add('Q-03', U, 'No month-long08:00-18:00 uptime measurements or deployment monitoring supplied.')
add('Q-04', P, 'Useful backend errors and role defaults verified (A/B/J). <15min novice task, <=2click own view and WCAG contrast were not measured with real users/browser.')
add('Q-05', P, 'Layered modules/constraint tests exist (B); >=70%engine line coverage not measured; full exporter/constraint extensibility and pinned-environment acceptance not independently demonstrated.')
add('Q-06', P, 'WindowsSQLite/frontend build executed. Linux, PostgreSQL, four browsers and one-command production packaging were not verified.')
add('Q-07', P, 'B has deterministic-seed and expected fixtures; this report supplies traceability. Repeatability under different hardware/deadline search outcomes and every SRS UI scenario remains unverified.')
add('Q-08', F, 'J/R/F/X: genuine UTF-8 CSV import/export, JSON APIs, generated OpenAPI (HTTP200/51 paths), binary PDF content and independently inspected pages.')
add('Q-09', P, 'J/B persist new terms/data/configs. Per-term week-start absent; referenced offering reassignment refused (X); future-course/assignment adaptation needs review.')
add('Q-10', P, 'Constraint interface/unit extensions exist; adding a role/exporter still touches catalogues/routes/UI. Full localized-change extensibility was not demonstrated.')
add('Q-11', P, 'A/B/J safe rollback/invalid rows/cancellation proven. G02/G03/email/timeout explanation and browser feedback gaps prevent full robustness acceptance.')
add('Q-12', P, 'Engine/validator run independently of HTTP and documented schema/templates exist (B/D). Whole CSV subsystem depends on DB/role context; reuse/adoption by another institution was not executed.')
add('Q-13', U, 'No double-reference300-offering/120-room scalability run executed; reference exam already fails completion target.')
add('UI-01 UI-02 UI-03 UI-04 UI-05 UI-07', P, 'Shared components, error IDs, confirmation/pagination and labels inspected; D verifies selected SSR error/resource output. Every form, contrast/icon/status/focus/keyboard behavior not browser-tested (W).')
add('UI-06 UI-08', U, 'W: browser startup unavailable; no measured contrast ratios or360px rendered interaction/overflow acceptance.')
add('DOC-01', P, 'D: role-based five-page PDF exists. Screenshot-based task manual remains explicitly incomplete; frontend/public/help/user-manual.pdf.')
add('DOC-02', P, 'D: role-specific help exists and selected field labels/tooltips tested. Every-field/every-screen tooltip/help coverage and browser discoverability remain incomplete.')
add('DOC-03 DOC-04 DOC-05', F, 'D/B: six CSV example files and csv-fields.md, two-page quick-start.pdf and installation.md/installation.pdf inspected; baseline tests.test_batch4_documentation verifies packaged documentation. Documentation presence is not deployment verification.')
add('DOC-06', P, 'X: /openapi.json and /docs HTTP200,51 resource paths; interactive Swagger authorization/try-it-out not exercised in browser (W).')
add('IF-01', P, 'Ordinary HTML/REST/download design; no special hardware apparent. Browser input/OS printing workflow not actually executed (W).')
add('IF-02', F, 'B/J/R: actual spawned worker processes, cancellation and files/DB/environment integration exercised on Windows. Reference workers are genuine CP-SAT/DSATUR executions.')
add('IF-03', P, 'J/R/F verify JSON/JWT, multipart CSV and PDF/CSV MIME. TLS1.2 production channel is unverified (SEC-5).')
add('IF-04', P, 'frontend/src polling source uses2s. No browser network trace confirms actual polling/lifecycle behavior (W).')
add('IF-05', F, 'X/B/J: OpenAPI resource inventory and real calls cover SRS Table9 login/master/availability/config/import/generation/status/entries/conflicts/publish/archive/export/audit;51 paths. Draft/preflight gaps assessed separately, not hidden as REST coverage.')
add('LEGAL-01', P, 'Inspected minimal scheduling PII and open-source dependencies. University privacy-policy signoff, complete delivered third-party licence notices and operational compliance were not verified.')
add('I18N-01', P, 'D: UTF-8/English resources and Karachi frontend formatting. Source scan finds447 static JSX display nodes/attributes outside resources across21 files (not447 unique phrases); week-start field absent; PDF footerUTC; Urdu shaping unverified.')
add('REUSE-01', P, 'B/D: independent engine/constraint modules and schema/templates documented. Complete external adoption, full web-independent import reuse and deployment were not executed.')

expected = {x['id'] for x in inventory['items']}
assert set(rows) == expected, (expected-set(rows),set(rows)-expected)
counts = Counter(s for s,e in rows.values())
fr = Counter(s for rid,(s,e) in rows.items() if rid.startswith('FR-'))
register = [dict(id=x['id'],requirement=x['description_from_original_matrix'],status=rows[x['id']][0],evidence=rows[x['id']][1]) for x in inventory['items']]
summary = dict(total=len(register),counts=dict(counts),strict_verified_percent=round(100*counts[F]/len(register),2),functional_total=sum(fr.values()),functional_counts=dict(fr),functional_verified_percent=round(100*fr[F]/sum(fr.values()),2),method='One unit per inherited traceability ID; all applicable; only Fully verified earns1, all other statuses0; no partial-credit score; overlapping FR/UR/UC are disclosed.')
(HERE/'requirement_statuses.json').write_text(json.dumps(dict(summary=summary,requirements=register),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

evidence = '''- **A — fresh security/negative hard-constraint tests:** [62-case JUnit](final_acceptance/targeted_security_constraints_migrations.xml), [log](final_acceptance/targeted_security_constraints_migrations.log). Includes37 authentication,19 validator and6 other migration cases; one authentication case is also a migration case. Thus7 migration cases are already within62, not additive.
- **B — retained full-suite evidence:** [604-case JUnit](batch4_project_tests.xml), [module counts](batch4_project_module_results.json). Reused baseline, not a fresh604-case run. [120-file preservation check](final_acceptance/source_preservation.json) establishes no assessed application/existing-test edits during this audit. Existing prior bug labels were not inherited as requirement verdicts.
- **J — fresh five-role backend journeys:** [80 HTTP observations](final_acceptance/api_journey_results.json), [executable probe](final_acceptance/api_acceptance.py). Real FastAPI TestClient, file SQLite, real spawned solvers; **not browser testing**. Zero unexpected HTTP expectations does not erase deliberately observed SRS defects. Initial exploratory expectation corrected transparently; see test-results report.
- **R — fresh reference HTTP/worker/performance results:** [default-weight trial](final_acceptance/reference_default_results.json), [zero-soft diagnostic](final_acceptance/zero_soft/reference_results.json), [environment](final_acceptance/environment.json), [fixture](final_acceptance/reference_server.py), [measurement driver](final_acceptance/measure_reference.py). Real loopback Uvicorn/SQLite; all hard rules enabled in both configurations.
- **V — independent oracle:** [implementation](final_acceptance/independent_oracle.py), [zero-soft generated timetable](final_acceptance/zero_soft/reference_1_entries.json), [independent feasibility witness](final_acceptance/independent_feasibility_witness.json). Oracle imports no application solver/validator/constraint helpers. Witness is never persisted as an application solution. Positive and negative evidence is deliberately combined; no claim of exhaustive mathematical proof for all inputs.
- **O — false-optimality counterexample:** [raw original/alternative outputs](final_acceptance/heuristic_optimal_counterexample.json). Two courses, disjoint explicit students, same batch, two days/rooms, only ES01 weight8; independently hard-valid alternative strictly improves spread. DSATUR result says optimal without proof.
- **L — supplemental import benchmark:** [5,000 enrollments](final_acceptance/enrollment_import_performance.json); independent SQL row-count increase5000, not just HTTP acceptance.
- **M — fresh migration cases:** seven cases across001–005 within A, including preservation/idempotence/rollback. PostgreSQL scripts inspected only; **not executed**.
- **D — frontend/resources/docs:** [five fresh SSR tests](final_acceptance/frontend_render_tests.log), [localization scan](final_acceptance/localization_scan.json), `frontend/public/help/*`, `frontend/src/locales/*`, [fresh build](final_acceptance/frontend_build.log); both fresh TypeScript checks passed. SSR is not browser, keyboard, mobile or screen-reader acceptance.
- **F — files/layout:** [PDF/CSV inspection](final_acceptance/export_inspection.json), [rendered grouped timetable](final_acceptance/reference_group_preview.png), [rendered exam](final_acceptance/exam_preview.png). Real A4-landscape/English files inspected, not browser print dialogs or Urdu shaping.
- **W — unavailable browser:** [two actual initialization failures](final_acceptance/browser_availability.json), before any UI interaction. No360px, desktop browser, keyboard, cross-browser or WCAG signoff.
- **X — schema/API narrow inspection:** [schema observations](final_acceptance/schema_inspection.json), [actual final HTTP probes](final_acceptance/final_narrow_probes.json). Individual FK indexes must not be confused with absence of every full composite index.
'''
intro = f'''# Final SRS compliance assessment

Assessment date:2026-11-21 (Asia/Karachi). **Acceptance decision: NOT ACCEPTED for complete SRS/production acceptance.** Strong automated regression evidence does not establish the remaining performance, lifecycle, browser, operational or legacy guarantees. No application code, existing tests or production database were changed; no deployment/recovery was performed.

## Scope and calculation

Authoritative SRS: `docs/SRS.pdf`,62 pages, SHA256 `{inventory['source_sha256']}`. Read persistent context and relevant current source; reused the existing traceability inventory, **not its verdicts**. Native SRS identifiers FR/UR/UC/H/S/E/ES/P/SAF/SEC/C are retained. DB/Q/UI/DOC/IF/LEGAL/I18N/REUSE are supplemental labels from the earlier matrix for the corresponding schema, quality, interface, documentation and sections5.2–5.4 clauses; they are not additional invented SRS obligations. Compound rows are full only when all clauses have sufficient execution or directly inspectable artifact evidence. Baseline tests are identified explicitly and remain valid evidence within their narrow scope. Browser-specific/user-journey rows are not full based on source/SSR/API tests.

Denominator: **{len(register)} applicable traceability rows**, zero exclusions. Each Fully verified row earns1; all other classifications earn0. No assumed50% partial credit and no denominator removal for unavailable environments. This is strict evidence coverage of overlapping traceability rows, **not a percentage of unique features or a production-readiness probability**. FR/UR/UC overlap intentionally; high-level UI journeys need evidence beyond their backend FRs.

- Fully verified:{counts[F]}
- Partially verified:{counts[P]}
- Not implemented:{counts[N]}
- Incorrect:{counts[I]}
- Not verified:{counts[U]}
- **Strict overall coverage:{counts[F]}/{len(register)} = {summary['strict_verified_percent']:.2f}%.**
- **Primary functional coverage:{fr[F]}/{sum(fr.values())} = {summary['functional_verified_percent']:.2f}%.**

Zero whole rows receive Not implemented because their compound obligations have some implementation; explicit missing subcriteria include Draft duplication/preflight, per-term week-start, offering deactivation and screenshot-based manuals. These are identified as **Not implemented subcriteria** in the gaps report; they are not treated as accepted.

## Evidence index

{evidence}
## Requirement-level register

Descriptions summarize the SRS/earlier inventory; they are not verbatim quotations. Failing or unverified clauses remain in the denominator. Full status is limited to the evidence and assessed Windows/SQLite environment; PostgreSQL/browser/operations clauses remain separate and unverified.

| ID | Requirement | Status | Evidence and limits |
| --- | --- | --- | --- |
'''
table='\n'.join('| '+ ' | '.join(str(r[k]).replace('|','/').replace('\n',' ') for k in ['id','requirement','status','evidence'])+' |' for r in register)
tail='''

## Acceptance boundaries

Fresh original audit is28/28, but those probes do not cover the full SRS. TimedOut/Cancelled are durable generation states even though the schedule header uses Infeasible; this is **not evidence of mathematical infeasibility**. Default reference timetable and both reference exam runs produced no valid result. The zero-soft timetable is a diagnostic success, not a replacement default-configuration acceptance run. CP-SAT optimal for a constant zero objective proves no useful soft-quality optimum. DSATUR feasible output must never be called mathematically optimal without proof; the recorded counterexample disproves that label.

B001–B003/B005 and Batch1–4 regression protections have retained604-case evidence plus fresh security/negative constraints/audit/backend journeys. B004 modern immutable context/save/publication safeguards are supported, but historical recovery and PostgreSQL verification remain **partially verified**. No automatic legacy repair or historical reinterpretation was attempted.

See [exact executions and measurements](FINAL_TEST_RESULTS.md) and [ranked acceptance gaps / deployment prerequisites](REMAINING_ACCEPTANCE_GAPS.md). A production acceptance decision requires closing or formally accepting each remaining criterion, not simply increasing a test total.
'''
(OUT/'FINAL_SRS_COMPLIANCE.md').write_text(intro+table+tail,encoding='utf-8')
print(json.dumps(summary,indent=2))
