# Weekly grid save duplication fix

## Root cause and change

The real frontend `TermsSlotsTab` sent one valid parameter object through `generateSlotGrid`: working days1–5, first time, length and six slots/day. It did not send duplicate rows or combine existing rows. It always called `POST /terms/{term_id}/slots/generate`, including when a grid already existed. That endpoint builds30 **new** candidates and correctly validates `existing + candidates`. The existing30 and candidate30 therefore produced duplicate indexes/clock overlaps. Validation rejected the request before persistence; the reproduced error does not establish that the user's database contains duplicate stored rows. No production database was inspected or repaired.

- Added `PUT /terms/{term_id}/slots/generate` for atomic complete-grid saves. Match existing rows by term/weekday/index, update their clocks in place and return the original IDs; add only missing keys. Repeating unchanged input is a no-op. Keep the POST endpoint's strict create-only duplicate rejection.
- Preserve existing block flags/reasons when the form does not explicitly supply block settings; retain instructor availability and schedule references. Refuse any save omitting existing keys, rather than deleting slots or truncating the term. Keep the existing configured duration and unchanged B002 validation for malformed times/days, duplicate indexes, physical overlaps and unequal durations.
- Validate the complete candidate state **before** mutating persistent rows, then commit once. Integrity failures roll back the entire edit. Use the shared input lock before term-row locks consistently with generation/publication; no schema/migration change.
- Frontend now calls the PUT save service, initializes fields from the selected term's existing grid, remounts state when switching terms and prevents save before loading succeeds. Existing mock-data mode mirrors in-place save semantics; real mode continues using the authenticated backend.
- Immutable snapshot readers/guards, independent validators, authentication and engine code are unchanged. Generated, Published and Archived history retains original clock definitions; changed current inputs make an old Generated version stale for publication. No schedules, slots, master data or snapshots were deleted.

## Modified implementation/tests

- `backend/routers/master_data.py`
- `frontend/src/services/api.ts`
- `frontend/src/services/mockApi.ts`
- `frontend/src/pages/data/TermsSlotsTab.tsx`
- `tests/test_weekly_grid_save.py` (17 new cases)
- `frontend/tests/weekly-grid.test.cjs` (three new cases)

Tracking: `audit_reports/PROGRESS.md`, `audit_reports/REMAINING_WORK.md` and this report. XML/build evidence is scoped under `audit_reports/weekly_grid*`; pre-existing uncommitted changes were preserved.

## Verification

All backend tests use disposable file-backed/in-memory SQLite with real JWT authentication. New cases cover fresh30-slot creation, twice saving, editing/resaving without ID/count changes, break/availability preservation, valid expansion, invalid/removing payload rollback, genuine duplicate/overlap rejection, all role exclusions/forged anonymous headers, Generated/Published/Archived snapshots, stale publication and whole-transaction failure rollback.

```powershell
.venv\Scripts\python.exe -B -m pytest tests/test_weekly_grid_save.py -p no:cacheprovider -q --junitxml=audit_reports/weekly_grid_save_tests.xml
# 17 passed
.venv\Scripts\python.exe -B -m pytest tests/test_weekly_grid.py tests/test_auth.py -p no:cacheprovider -q --junitxml=audit_reports/weekly_grid_preservation_tests.xml
# 124 passed (87 B002 + 37 authentication)
.venv\Scripts\python.exe -B -m pytest tests/test_weekly_grid_save.py tests/test_weekly_grid.py -k 'weekly_grid_save or create or update or bulk or adjacent' -p no:cacheprovider -q --junitxml=audit_reports/weekly_grid_final_targeted.xml
# Final verification after consistent lock-order change: 65 passed, 39 deselected
```

The final65 repeat17 new and48 existing affected mutation tests; they are **not**65 additional distinct cases. Across targeted Python runs:141 distinct cases passed, no remaining failures. Initial test-first reproduction of the missing PUT contract failed as expected; it passed after implementation. Framework deprecation warnings remain; no dependencies were changed.

From `frontend`:

```powershell
node --test tests/weekly-grid.test.cjs tests/batch4.test.cjs
# 8 passed:3 new +5 existing, not additional counts from preliminary reruns
node node_modules/typescript/bin/tsc -p tsconfig.app.json --noEmit
node node_modules/typescript/bin/tsc -p tsconfig.node.json --noEmit
node node_modules/vite/bin/vite.js build --outDir ../audit_reports/weekly_grid_frontend_build
```

Both TypeScript checks passed (exit0); production build passed (1,608 modules,8.44s). Output went to a new audit directory, preserving existing frontend build output. The outside-root Vite notice is informational. No full-suite rerun, production data access, database reset, migration or deployment was performed. Frontend request/initialization regressions are transport/unit tests; actual browser interaction and PostgreSQL were not executed in this fix.

Restart the running backend if it does not auto-reload, and reload the frontend so the form uses the new save endpoint. Current grid saves intentionally cannot delete existing days/indexes or change the previously fixed slot length; those requests receive controlled errors and leave records unchanged. Existing broader acceptance gaps remain separate.
