# B005 — Physical lab-block contiguity

21 November 2026 (Asia/Karachi). Scope: B005 only. No production data, database migration or legacy snapshot recovery was performed. B006 was not started.

## Root cause

H09 previously collected lab slot indexes, weekdays and rooms. Consecutive indexes were treated as evidence of a contiguous lab, without comparing the underlying end/start clock times. The CP-SAT constraint and its feasibility diagnosis made the same assumption. A valid equal-length weekly grid can contain nonteaching gaps, so B002's grid validation alone cannot establish lab continuity.

The old H09 validator also ignored missing slot references and derived consecutiveness from the number of entries it happened to receive rather than checking the required block size independently. Mandatory H08 already checked session counts; it remains in force.

## Exact changes

`engine/constraints.py`, H09 `add_to_model`: candidate lab chains must now use slots in the requested term and satisfy `previous.end == next.start` for every boundary. Existing CP-SAT assignment variables, room coupling, exactly-one placements and other constraints remain. No scheduling algorithm was replaced.

H09 `validate`: independently resolves every lab slot, checks unique references, the offering's academic term, one weekday, one room, consecutive indexes, exact required slot count and every physical clock boundary. A completely missing required lab block is checked too. Missing, malformed, duplicate, extra or foreign-term references produce a hard H09 violation. The validator compares resolved intervals independently of the model's candidate-chain enumeration; it does not trust selected slot IDs or a shared contiguity predicate. Conflict metadata includes expected and actual lab slot counts.

`engine/timetable_solver.py`: the existing H09 pre-solve feasibility check now rejects chains crossing a physical clock gap or term boundary, consistent with the CP-SAT model. B002's complete-grid preflight and H01–H03 physical exclusions remain unchanged.

H09 and H07 retain their SRS configurable status. A physically adjacent block containing a blocked slot is rejected by enabled H07. Explicitly disabling H07 still has the existing documented effect; this fix does not silently make optional constraints mandatory. H08 remains mandatory even if a configuration attempts to disable it. Disabling H09 does not disable H08 or B002 grid validation.

## Manual adjustments

The backend represents a lab block as several `TimetableEntry` rows for one offering. Manual adjustment currently changes one entry and revalidates the entire candidate timetable before writing it. That call now uses corrected H09 and rejects a single-row move that breaks clock continuity, room/day/index relationships or required size. The regression constructs a valid grid with a real clock gap, preserves a valid original lab, attempts a move whose resulting indexes are still consecutive, verifies H09 in the HTTP 409 response and checks the persisted entry is unchanged.

Atomic multi-slot lab movement and its UI remain B015 limitations. No unrelated block-movement endpoint or UI was added.

## Immutable snapshots and compatibility

B004 pins snapshots to engine fingerprints. Merely changing H09 would otherwise make all previous B004 snapshots unreadable, even when their original labs are valid. `backend/schedule_integrity.py` therefore permits one explicitly reviewed compatibility transition, described in `backend/snapshot_compatibility/b004_to_b005.json`.

Both the complete recorded B004 identity and the current B005 identity must match the manifest exactly, including all engine file hashes and OR-Tools/NetworkX versions. Only the identity field is accommodated during normalization; snapshot scope, JSON field types, original checksum, policy, configuration, frozen input values and publication receipt checks remain intact. Unknown predecessor fingerprints and unreviewed future engines still fail closed. A missing/corrupt compatibility file fails closed rather than permitting unchecked interpretation.

The corrected validator always reads the snapshot's original time-slot definitions. It never substitutes current master clock times. No stored snapshot JSON, hash, approval, receipt or historical entry is rewritten by compatibility handling. A formerly accepted clock-gapped lab with enabled H09 is now rejected on independent review; its entries/context are retained rather than repaired silently.

`tests/fixtures/b004_timetable_context.json` preserves an actual checksum-verified valid input context from an isolated B004 regression database created before this fix. Its literal original hash is asserted independently with Python's JSON/SHA-256 primitives. Tests load that context through real snapshot persistence and verify Published and Archived views after conflicting edits to current clock times, without changing the stored context/hash/receipt.

This is not general legacy recovery. B004 remains partially resolved for already official versions lacking trustworthy snapshots; PostgreSQL execution remains Not Verified. Different old builds/dependency sets require their pinned reader or another reviewed compatibility transition. Deployments must include the manifest; no blanket fingerprint bypass was introduced.

## Modified-file list

Existing application files changed:

- `engine/constraints.py`: H09 physical chain selection, reference/term/count checks and independent boundary validation.
- `engine/timetable_solver.py`: matching H09 clock/term feasibility diagnosis.
- `backend/schedule_integrity.py`: exact B004-to-B005 reader compatibility and fail-closed handling of compatibility-file errors.

New files:

- `backend/snapshot_compatibility/b004_to_b005.json`: exact reviewed source/target implementation identities.
- `tests/test_lab_contiguity.py`: 45 new B005 cases.
- `tests/fixtures/b004_timetable_context.json`: preserved valid B004 test context and its original hash.
- `audit_reports/B005_FIX_REPORT.md` and `audit_reports/b005_*.log`, `.xml`, `.json`: report and verification evidence.

`audit_reports/BUG_REPORT.md` receives a resolution annotation while retaining the original audit evidence. Generated frontend output is locally excluded via `.git/info/exclude`.

No existing test file, frontend source, database model, migration, authentication implementation, enrollment implementation, snapshot persistence guard or publication endpoint was modified.

## Regression coverage

The 45 new cases cover one/two/three-slot adjacent labs; large clock gaps; overlapping intervals; split weekdays and rooms; missing intermediate indexes; duplicate/missing slot references; foreign-term slots; short, absent and oversized blocks; malformed clock strings; a third-slot gap; blocked periods; insufficient supply; unrelated parallel lectures; configurable H09 with mandatory H08; malformed external grids; manual-edit rejection/rollback; real B004 Published/Archived snapshots; rejection of old gapped contexts without rewriting; unknown/future fingerprints; and a missing compatibility manifest.

Tests use hand-specified expected outcomes, literal required counts and a `datetime` boundary oracle instead of the solver/H09 interval helpers. Standalone CP-SAT tests force proposed assignments and check feasibility directly. Public solver tests use real OR-Tools results and verify their labs against the separate oracle. API tests authenticate through the real B001 login path against disposable SQLite files. There are no mocked scheduling results or permanent mock snapshots.

## Commands and results

Run from the repository root:

~~~powershell
.venv\Scripts\python.exe -B -m pytest tests -p no:cacheprovider -q --junitxml=audit_reports/b005_project_tests.xml
.venv\Scripts\python.exe -B -m pytest tests/test_lab_contiguity.py -p no:cacheprovider -q --junitxml=audit_reports/b005_lab_tests.xml
.venv\Scripts\python.exe -B -m pytest tests/test_validator.py tests/test_timetable_solver.py -p no:cacheprovider -q --junitxml=audit_reports/b005_initial_engine.xml
.venv\Scripts\python.exe -B -m pytest audit_reports/test_audit_probes.py audit_reports/test_extra_probes.py -p no:cacheprovider -q --junitxml=audit_reports/b005_audit_regressions.xml
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.app.json --noEmit
node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.node.json --noEmit
node frontend/node_modules/vite/bin/vite.js build frontend --outDir ../audit_reports/b005_frontend_build
~~~

Final project/subset results are recorded in `b005_project_tests.log` / `.xml` and `b005_test_results.json`. Regression subsets are included in the project total and are not added again as separate tests.

- Full project: **407 passed, 0 failed**, 309.05 seconds.
- B001 regressions: **37 passed, 0 failed** (included).
- B002 regressions: **87 passed, 0 failed** (included).
- B003 regressions: **60 passed, 0 failed** (included).
- B004 regressions: **99 passed, 0 failed** (included).
- New B005 regressions: **45 passed, 0 failed** (included).
- Original B005 audit regression: **1 passed, 0 failed**, included in the full audit.
- Full original audit: **17 passed, 11 existing failures**, with no newly failing audit case.
- Frontend application TypeScript, tooling TypeScript and production build: **all passed**.

Five pre-existing Starlette/httpx and HTTP-422-name deprecation warnings remain; they are not failed checks.

The first focused run passed 43 new cases; two compatibility failure cases were then added for the final full suite. All 44 existing timetable solver/validator cases passed their focused run. No existing assertion was removed or weakened.

The original `test_lab_contiguity_uses_clock_time` passes in the complete retained audit. Full original audit results: **17 passed, 11 failed**, improved from B004's 16 passed/12 failed. The sole changed audit outcome is B005; no audit case newly fails. See `b005_audit_comparison.json` and `b005_audit_regressions.log` / `.xml`.

Application TypeScript, tooling TypeScript and the production Vite build passed (`b005_frontend_checks.log`). No browser or live-deployment testing is claimed.

## Previous fix preservation

`b005_preservation_baseline.json` / `b005_preservation_results.json` compare the pre-change workspace with the completed implementation. Only the three existing application files listed above changed. All pre-existing regression files, frontend sources, database schema/migrations, B001 authentication code, B002 grid module and B003 enrollment module remain byte-for-byte unchanged.

H01–H08/H10 and exam constraint implementations are preserved. B004's immutable storage, original-input hashing, receipt invalidation, stale-result rejection, read-only historical entry guards and missing-context safeguards remain. Its 99 tests are part of final project verification. The compatibility exception is bound to exact reviewed identities and is tested against unknown source builds, future builds and unavailable manifests.

## Remaining limitations and audit failures

The 11 remaining original audit failures concern student draft visibility/list filtering (two); missing user, audit, import, publish and CSV/PDF export endpoints (six); exam manual-override metadata; master-data mutation auditing; and lazy-app recovery of interrupted generations. They remain genuine prior findings and were not changed to expected failures.

Atomic multi-slot lab movement remains B015. B004's missing legacy snapshot recovery and unverified PostgreSQL execution remain unchanged. Compatibility covers only the exact reviewed B004 profile and B005 reader; missing/unknown profiles fail closed. The existing representation treats the required lab slots for one offering as one block; no new multiple-block model was introduced.

## Final B005 status

**B005 is resolved and verified in the implementation and isolated regression suites.** H09 rejects clock-time gaps as well as the other required block defects; CP-SAT, diagnosis, manual validation and authoritative snapshot validation agree. No production schedule or immutable snapshot was rewritten. B004 retains its previously documented partial status. B006 was not started.
