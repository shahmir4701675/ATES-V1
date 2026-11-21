# ATES scheduling algorithm audit

21 November 2026 (Asia/Karachi). Audit-only. Real algorithms are present; ordinary supplied fixtures pass, but enabled hard constraints are not guaranteed for every input the application accepts. Overall project is not ready for acceptance.

## Evidence and execution

The supplied timetable25, exam13 and validator19 cases all passed, in addition to backend integration tests exercising actual engines. Added regression probes demonstrate actual timetable clock-time overlap, lab-adjacency validator failure and missing mixed-enrollment conflict edge. See direct_tests.xml/log and final_audit_probes.xml/log. No reference-size or long-running stress benchmark was performed. Static deadline/concurrency findings are not claims of measured reference-size violations.

## Timetable pipeline

engine/timetable_solver.py imports ortools.sat.python.cp_model, creates CpModel and BoolVar assignment indicators x[(session,slot,room)], builds per-session variables over encoded slot/room pairs and enforces exactly one placement. H01/H02/H03 use AddAtMostOne for instructor/room/batch slot usage. H04/H05/H06/H07 prune/restrict invalid assignments, H08 enforces required session counts, H09 links lab offsets to consecutive slot indexes in one day/room, and H10 sums teaching minutes against instructor limits. Course.required_lecture_sessions/required_lab_slots derives whole-slot requirements by ceiling contact-hours minutes divided by term slot duration. TimeSlot duration comes from clock times, while term_slot_length_minutes simply uses the first term slot.

The model adds S01-S06 via a shared constraint interface and maximizes weighted satisfaction. Weight0/disabled soft rules are ignored by the timetable objective; weights are clamped0-10 in engine and validated at API/database boundaries. CP-SAT search uses a chosen seed and one search worker. This is genuine optimization rather than random/mock timetable generation. The small-fixture deterministic-seed and each preference test passed.

After feasible/optimal Solve, raw entries are passed to TimetableValidator. A nonempty violation result is discarded and the run becomes Infeasible. The supplied injected-validator rejection test passed. Infeasible and unknown results carry reasons; unknown/time-limit-without-solution is retained as solver_status unknown with application status Infeasible. Existing tests demonstrate failure preservation and atomic persistence.

### Constraints H01-H10

| Requirement ID | Description | Implementation Location | Status | Evidence | Required Action |
|---|---|---|---|---|---|
| H01 | Instructor at most one session per slot (mandatory) | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Partially Implemented | Existing H01 tests pass; API accepts overlapping clock slots and both model/validator key by slot_id | Validate nonoverlapping grid and physical-time conflicts |
| H02 | Room at most one session per slot (mandatory) | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Partially Implemented | Existing H02 tests pass; distinct overlapping slots bypass slot_id exclusivity | Reject overlapping grid or use interval overlap |
| H03 | Batch at most one session per slot (mandatory) | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Partially Implemented | Existing H03 tests pass; distinct overlapping slots bypass exclusivity | Reject overlapping grid and validate actual intervals |
| H04 | Room capacity at least offering enrolled count | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Fully Implemented | Existing H04 solver toggle and validator tests pass; capacity constraints inspected | Retain; guard post-publication metadata separately |
| H05 | Labs in Lab rooms and lectures in Lecture rooms | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Fully Implemented | Existing H05 toggle/validator tests pass and strict type model constraints inspected | Retain type checks |
| H06 | No teaching in instructor unavailable slot | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Fully Implemented | Existing H06 toggle/validator tests pass; missing availability defaults available | Retain availability checks |
| H07 | No sessions in blocked slots | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Fully Implemented | Existing H07 toggle/validator tests pass | Retain blocked-slot checks |
| H08 | Exact lecture and lab session counts per offering (mandatory) | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Partially Implemented | Ordinary H08 tests pass; inactive courses skipped by validator and no immutable published snapshot | Validate all required offerings against stable version inputs |
| H09 | Lab consecutive clock slots on one day and one room | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Incorrectly Implemented | Audit lab test changes last slot to18:00-19:00; validator returns[] | Check temporal adjacency as well as slot_index |
| H10 | Daily and weekly instructor teaching hours respected | engine/constraints.py; engine/timetable_solver.py; engine/validator.py | Fully Implemented | Existing H10 toggle/validator tests pass; actual slot duration sums inspected | Retain and validate uniform grid |

**Demonstrated physical conflict (B002):** fresh engine dataset contains one offering requiring two lectures and two different slot IDs/indexes, both Monday08:00-09:00. solve_timetable returns optimal with instructor1, batch1 and room2 in both entries; violations=[]. Each index is used once, but all real resource intervals overlap. Separately POST /terms/1/slots with a new index overlapping an existing slot returns201, making the precondition reachable through the public API. It is not sufficient to argue the solver assumes a valid grid when that invariant is not enforced at input or independently checked.

**Demonstrated lab gap (B005):** changing the last slot of an otherwise valid two-slot lab to18:00-19:00 leaves slot_index adjacency unchanged; validator returns[]. H09 model and validator check slot indexes rather than end/start adjacency. H09 must include clock-time contiguity for accepted data. Ordinary split-room/day/index negative tests still pass.

H08 counts rows of active course offerings but skips an inactive course. Master-data deactivation therefore changes which historical obligations are validated. Required offerings should be evaluated against a stable version input snapshot. Missing referenced room/offering checks in some individual constraint validators skip records; database FK guards reduce that risk for persisted schedules but standalone validator input completeness is not comprehensively checked. The extra audit did not execute every corrupt-reference case.

### Preferences S01-S06

| Requirement ID | Description | Implementation Location | Status | Evidence | Required Action |
|---|---|---|---|---|---|
| S01 | Minimize idle batch gaps | engine/constraints.py:1018-1806; engine/timetable_solver.py:844-881 | Fully Implemented | Executed test_s01_minimises_batch_idle_gaps_on_a_day and score tests | Retain objective/metric tests |
| S02 | Spread offering sessions over days | engine/constraints.py:1018-1806; engine/timetable_solver.py:844-881 | Fully Implemented | Executed test_s02_spreads_offering_sessions_across_different_days | Retain tests |
| S03 | Prefer at most configured batch sessions per day | engine/constraints.py:1018-1806; engine/timetable_solver.py:844-881 | Fully Implemented | Executed test_s03_keeps_batch_daily_sessions_at_or_below_parameter | Retain tests |
| S04 | Prefer at most configured consecutive instructor slots | engine/constraints.py:1018-1806; engine/timetable_solver.py:844-881 | Fully Implemented | Executed test_s04_keeps_instructor_consecutive_teaching_slots_within_limit | Retain tests; enforce valid slot topology |
| S05 | Prefer prior version slot and room | engine/constraints.py:1018-1806; engine/timetable_solver.py:844-881 | Partially Implemented | Direct-engine S05 tests pass; worker omits prior timetable argument | Pass complete prior entries, not just locks |
| S06 | Prefer smallest fitting room | engine/constraints.py:1018-1806; engine/timetable_solver.py:844-881 | Fully Implemented | Executed test_s06_prefers_smallest_fitting_room | Retain tests |

**API stability integration (B014):** direct-engine S05 tests pass when previous_schedule is supplied. run_schedule_generation_worker loads the latest Generated/Published prior version, removes every unlocked timetable entry, and calls solve_timetable without previous_schedule or previous_entries. The solver normalizes only those explicit arguments for stability, yielding an empty prior list. Locks are preserved by a different dataset path, so passing lock tests does not prove the stability objective works through the API.

## Exam pipeline

build_conflict_graph constructs a real networkx.Graph. Vertices are active offered course IDs from course_student_counts. For each pair, it intersects course_students sets and adds an edge with shared-student metadata. colour_conflict_graph_dsatur calls nx.coloring.greedy_color(graph,strategy='DSATUR'). Ordinary graph/proper-colouring tests passed.

Colour classes are split when room availability/capacity requires it, then mapped injectively onto exam sessions using backtracking while considering daily limits and batch day-spread. Rooms are allocated via per-session CP-SAT, disjoint per exam session, covering the required total capacity; extracted seat allocations sum to each course student count and do not exceed room capacities. Eligible generation rooms are active Lecture or Exam Hall rooms. Tests cover exact seats, room clashes, infeasible course capacity and soft room preferences.

If colour groups need too many sessions, mapping/allocation fails, or locked exams must be preserved, _solve_with_cpsat models integrated course/session and course/session/room decisions. Real fallback success and infeasible cases passed. Candidate ExamEntry and ExamRoomAllocation objects are checked with ExamValidator before returning a Generated-capable result. That validator checks E01-E05, not just graph colouring validity.

### Exam hard rules

| Requirement ID | Description | Implementation Location | Status | Evidence | Required Action |
|---|---|---|---|---|---|
| E01 | Shared-student courses use different sessions (mandatory) | engine/constraints.py:1824-2294; engine/exam_scheduler.py; engine/models.py:523-550 | Incorrectly Implemented | Ordinary E01 tests pass; mixed enrollment/fallback graph has no expected edge | Represent inferred cohort students consistently in solver and validator |
| E02 | Daily student exam count <= configured maximum | engine/constraints.py:1824-2294; engine/exam_scheduler.py; engine/models.py:523-550 | Partially Implemented | Ordinary E02 tests pass; mixed explicit/cohort identities undercount | Use consistent identity in every daily count |
| E03 | Exact seats equal students and do not exceed capacity | engine/constraints.py:1824-2294; engine/exam_scheduler.py; engine/models.py:523-550 | Fully Implemented | Existing E03 validator, capacity-infeasibility and allocation tests pass | Retain; validate inactive/type room eligibility too |
| E04 | Room used by at most one exam per session (mandatory) | engine/constraints.py:1824-2294; engine/exam_scheduler.py; engine/models.py:523-550 | Fully Implemented | Existing E04 validator and fallback allocation tests pass | Retain; reject overlapping exam sessions at input |
| E05 | Each required course exactly one valid exam session (mandatory) | engine/constraints.py:1824-2294; engine/exam_scheduler.py; engine/models.py:523-550 | Fully Implemented | Existing E05 validator/mandatory tests pass; unique(schedule,course) exists | Retain term-scoped validation |

**Mixed enrollment error (B003):** an offering whose explicit enrollments meet enrolled_count gets only student:ID memberships. A missing/partial enrollment offering receives an additional batch:ID membership. For two courses of one batch, a fully enumerated course and a missing-data course can have disjoint identity sets even though A-4 says the latter includes the batch's students. The executed probe constructs this condition for courses1 and2, batch1; graph.has_edge(1,2) is false. E01 validation and E02 daily counting reuse the same course_students helper, so they cannot independently recover the lost relationship. This is a demonstrated graph defect and a consequent possible exam-clash path, not a claim that an actual production student's exams were observed to clash.

E03 correctly recomputes expected counts from offerings as well as checking per-entry seat totals and per-room capacity. These ordinary cases were executed. Course counts sum enrolled_count over offerings; full student-set reconciliation and duplicate enrollment across offerings of one course were not exercised. E04 checks room use per exam_slot_id, relying on nonoverlapping exam windows; API creates exam sessions with overlap rejection, unlike the weekly slot path. Concurrent exam-session creation was not tested and the overlap check is application-side.

E05 checks required course presence and existence of exam session IDs. Core validators rely on term-scoped input supplied by the adapter; standalone multi-term datasets are not comprehensively validated for cross-term membership. No standalone engine invalid-input proof beyond the added probes is claimed.

### Exam preferences

| Requirement ID | Description | Implementation Location | Status | Evidence | Required Action |
|---|---|---|---|---|---|
| ES01 | Spread one batch exams across days | engine/constraints.py:2297-2640; engine/exam_scheduler.py | Fully Implemented | Executed ES01 preference test and score-breakdown test | Retain |
| ES02 | Minimize rooms per exam | engine/constraints.py:2297-2640; engine/exam_scheduler.py | Fully Implemented | Executed ES02 preference test | Retain; respect weight0 in all allocation paths |
| ES03 | Keep rooms for one exam in same building | engine/constraints.py:2297-2640; engine/exam_scheduler.py | Fully Implemented | Executed ES03 preference test | Retain |

The DSATUR path does not prove globally optimal weighted schedules. It initializes solver_status='optimal' on heuristic success, while chromatic_number is the number of DSATUR colours, not an exact chromatic-number proof. Diagnostics and UI should distinguish a feasible heuristic result from a globally proved optimum, and a heuristic colour bound from a proven minimum session shortfall. Per-session allocation may time out with FEASIBLE while the top-level DSATUR path still labels the run optimal. This labeling issue is established by static flow; no adversarial counterexample for the exact optimum was benchmarked.

## Time limits, cancellation and infeasible behavior

- Timetable default constant120s and API/config limit10-600s are genuine. solver.parameters.max_time_in_seconds uses the effective limit. The API passes explicit configured overrides correctly.
- The public solve_timetable wrapper defaults time_limit=120, which is forwarded even when a dataset config has a different limit unless time_limit_s/another explicit argument is passed. Direct TimetableSolver.solve can resolve config limits; callers should not assume these two entrypoints have identical default semantics.
- Model construction, input diagnosis, post-solve validation and persistence lie outside the CP-SAT solver timer. Combinatorial infeasibility diagnosis can launch one2-second solve per optional rule. Thus CP-SAT's timer is not an end-to-end run deadline. Some runtime fields are captured before diagnosis finishes, understating actual response time.
- Exam per-session room allocation has its own fixed5-second limit and may be invoked repeatedly during splitting and final allocation. Backtracking colour-to-session mapping has no monotonic deadline/cancellation check. Extra diagnostics have5-second solves; fallback uses max(1,remaining), which grants at least another second even after the budget is consumed. These are static budget escapes; reference-size30s compliance is Not Verified.
- There is no real cancellation endpoint or worker signal. Frontend cancellation changes local tracking only; server eventually saves a new version. FastAPI BackgroundTasks executes the synchronous callable in a threadpool in the API process, not a separately isolated solver worker.
- Structural timetable defects currently become Infeasible after the API creates Generating, rather than remain Draft as Figure12 describes. Empty exam course input returns an optimal empty result, which needs explicit product acceptance semantics rather than silently implying a populated exam schedule.
- Infeasible fixture tests passed and previous results survived rollback/failure. However pending generations use an input snapshot read before Solve; current mutable DB/config values are not revalidated under the final save transaction. A changed room capacity/availability can invalidate saved results or old published versions.

## Independent validation assessment

There is a separate validation call path and no need to trust CP-SAT variable values for checks. It detects all 15 ordinary per-rule negative fixtures, and an injected rejection prevents generation. However each rule's modeling and validation live in methods of the same constraint class, and both exam graph construction and validator share enrollment helpers. Shared data assumptions produced demonstrated common-mode failures. A passing validator is evidence for the checks actually encoded, not proof of all SRS constraints.

At minimum, add an oracle that checks physical time overlaps, full lab temporal chains, mandatory offering completeness against frozen version inputs and explicit/inferred enrollment membership independently. Generation and publication should both reject hard-invalid or stale results. Optional H04/H05/H06/H07/H09/H10/E02/E03 may intentionally be disabled under the SRS with warning; those permitted disables are separate from the enabled-rule violations reported here.

## Acceptance criteria

Re-run the79 supplied cases and28 audit cases after fixes, add reference-size and mixed-enrollment oracle datasets, test all hard-rule mutations and generated candidates independently, verify locked block/session pinning and S05 through API, enforce an end-to-end deadline/cancellation signal, and demonstrate no stale or invalid result reaches Generated/Published. No fixes were performed in this audit.
