"""Pytest test suite for the ATES examination scheduler (`engine/exam_scheduler.py`).

Covers:
1. Step 1: Conflict graph construction with NetworkX (`build_conflict_graph`).
2. Step 2: DSATUR graph colouring and session mapping respecting E01 and E02.
3. Step 3: Exact OR-Tools CP-SAT fallback and infeasible shortfall / unplaced courses reporting.
4. Step 4: Room seat allocation respecting E03 (exact student count & room capacity) and E04.
5. Feasible dataset (`data/seed_exam.json`) and over-constrained dataset (`data/overconstrained_exam.json`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.exam_scheduler import (
    ExamScheduler,
    build_conflict_graph,
    colour_conflict_graph_dsatur,
    schedule_exams,
)
from engine.models import (
    Course,
    CourseOffering,
    Enrollment,
    ExamSlot,
    TimetableDataset,
    load_dataset_from_json,
)
from engine.validator import validate_exam_schedule

SEED_EXAM_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_exam.json"
OVERCONSTRAINED_EXAM_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "overconstrained_exam.json"
)


@pytest.fixture()
def feasible_exam_dataset() -> TimetableDataset:
    """Load a fresh copy of the feasible exam dataset (`data/seed_exam.json`)."""
    return load_dataset_from_json(SEED_EXAM_PATH)


@pytest.fixture()
def overconstrained_exam_dataset() -> TimetableDataset:
    """Load a fresh copy of the over-constrained exam dataset (`data/overconstrained_exam.json`)."""
    return load_dataset_from_json(OVERCONSTRAINED_EXAM_PATH)


def test_step1_build_conflict_graph(feasible_exam_dataset: TimetableDataset) -> None:
    """Step 1: Conflict graph has courses as vertices and edges where students overlap."""
    graph = build_conflict_graph(feasible_exam_dataset)
    assert sorted(graph.nodes()) == [1, 2, 3, 4, 5]
    assert graph.nodes[1]["student_count"] == 85
    assert graph.nodes[2]["student_count"] == 45
    assert graph.nodes[4]["student_count"] == 40

    # Enrollment information is partial for every offering. A-4 conservatively
    # includes known student 9001 throughout both linked batches: all five exams
    # conflict, rather than only the two courses with explicit repeater links.
    expected_edges = {(u, v) for u in range(1, 6) for v in range(u + 1, 6)}
    actual_edges = {(min(u, v), max(u, v)) for u, v in graph.edges()}
    assert actual_edges == expected_edges
    assert "student:9001" in graph.edges[2, 4]["shared_students"]


def test_step2_dsatur_colouring_produces_valid_proper_colouring(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """Step 2: DSATUR colours the conflict graph such that no adjacent courses share a colour."""
    graph = build_conflict_graph(feasible_exam_dataset)
    colouring = colour_conflict_graph_dsatur(graph)
    assert set(colouring.keys()) == {1, 2, 3, 4, 5}
    for u, v in graph.edges():
        assert colouring[u] != colouring[v]
    # The corrected partial-enrollment graph is K5.
    assert len(set(colouring.values())) == 5


def test_feasible_seed_exam_dataset_scheduled_and_validated(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """Feasible dataset (`data/seed_exam.json`) produces an optimal/feasible schedule passing E01–E05."""
    # Clear pre-existing entries to ensure the scheduler generates everything from scratch
    feasible_exam_dataset.exam_entries = []
    feasible_exam_dataset.exam_room_allocations = []

    result = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert result.status in ("optimal", "feasible")
    assert result.schedule is not None
    assert len(result.entries) == 5
    assert result.shortfall == 0
    assert result.unplaced_courses == []
    assert result.reasons == []
    assert result.violations == []

    # Verify independent validator passes with zero violations
    violations = validate_exam_schedule(
        feasible_exam_dataset,
        entries=result.entries,
        allocations=result.room_allocations,
    )
    assert violations == []

    # Verify E03 & E04 explicitly on returned allocations
    allocs_by_entry = {}
    for alloc in result.room_allocations:
        allocs_by_entry.setdefault(alloc.exam_entry_id, []).append(alloc)

    rooms_by_id = feasible_exam_dataset.rooms_by_id
    for entry in result.entries:
        e_allocs = allocs_by_entry.get(entry.exam_entry_id, [])
        assert sum(a.seats_allocated for a in e_allocs) == entry.student_count
        for a in e_allocs:
            room = rooms_by_id[a.room_id]
            assert room.room_type in ("Exam Hall", "Lecture")
            assert 1 <= a.seats_allocated <= room.capacity


def test_overconstrained_exam_dataset_falls_back_to_cpsat_and_reports_shortfall(
    overconstrained_exam_dataset: TimetableDataset,
) -> None:
    """Over-constrained dataset (`data/overconstrained_exam.json`) triggers CP-SAT fallback and reports shortfall."""
    result = schedule_exams(overconstrained_exam_dataset, time_limit_s=30.0, random_seed=1)

    assert result.status == "infeasible"
    assert result.schedule is None
    assert result.entries == []
    assert result.room_allocations == []
    assert result.used_cpsat_fallback is True
    # 5 mutually conflicting courses in 3 defined exam_slots -> shortfall = 2 sessions, 2 unplaced courses
    assert result.shortfall == 2
    assert len(result.unplaced_courses) == 2
    assert len(result.unplaced_course_codes) == 2
    assert len(result.reasons) >= 1
    assert any("shortfall=2" in r or "Unplaced courses" in r for r in result.reasons)


def test_cpsat_fallback_succeeds_when_dsatur_colour_group_exceeds_room_or_daily_limits(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """Step 3: Direct verification that `_solve_with_cpsat` produces a valid schedule passing E01–E05."""
    scheduler = ExamScheduler(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    rule_states = scheduler._enabled_rule_map()
    student_counts = feasible_exam_dataset.course_student_counts()
    course_students = feasible_exam_dataset.course_students()
    course_batches = feasible_exam_dataset.course_batches()
    course_ids = sorted(student_counts.keys())
    exam_slots = scheduler._exam_slots_for_term()
    eligible_rooms = scheduler._eligible_rooms()
    conflict_graph = build_conflict_graph(feasible_exam_dataset)

    status, course_to_slot, course_to_rooms = scheduler._solve_with_cpsat(
        course_ids=course_ids,
        exam_slots=exam_slots,
        eligible_rooms=eligible_rooms,
        conflict_graph=conflict_graph,
        student_counts=student_counts,
        course_students=course_students,
        course_batches=course_batches,
        rule_states=rule_states,
        remaining_time_s=15.0,
    )
    assert status in ("optimal", "feasible")
    assert course_to_slot is not None
    assert course_to_rooms is not None
    assert set(course_to_slot.keys()) == {1, 2, 3, 4, 5}
    for u, v in conflict_graph.edges():
        assert course_to_slot[u] != course_to_slot[v]


def test_infeasible_when_single_course_exceeds_total_exam_room_capacity(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """E03 Infeasibility: A course with more students than all eligible exam rooms combined is infeasible."""
    # Total eligible room capacity in seed_exam.json is 60 + 50 + 45 + 30 = 185.
    # Set offering 1 enrolled_count = 200 so CS-326 has 240 students > 185.
    feasible_exam_dataset.course_offerings[0].enrolled_count = 200

    result = schedule_exams(feasible_exam_dataset, time_limit_s=15.0, random_seed=1)
    assert result.status == "infeasible"
    assert 1 in result.unplaced_courses
    assert "CS-326" in result.unplaced_course_codes
    assert any("E03" in r for r in result.reasons)


def test_optional_constraint_e02_can_be_disabled(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """When all exam slots are on the same day, E02 (max 2/day) is infeasible when enabled, feasible when disabled."""
    # Put all 6 exam slots on the same date (2026-12-14)
    times = [
        ("S1", "08:00", "09:30"),
        ("S2", "09:45", "11:15"),
        ("S3", "11:30", "13:00"),
        ("S4", "13:30", "15:00"),
        ("S5", "15:15", "16:45"),
        ("S6", "17:00", "18:30"),
    ]
    for slot, (label, st, et) in zip(feasible_exam_dataset.exam_slots, times):
        slot.exam_date = "2026-12-14"
        slot.session_label = label
        slot.start_time = st
        slot.end_time = et

    # With E02 enabled (limit=2/day), Batch 1 has 3 courses on 2026-12-14 -> infeasible
    res_enabled = schedule_exams(feasible_exam_dataset, time_limit_s=15.0, random_seed=1)
    assert res_enabled.status == "infeasible"
    assert any("E02" in r for r in res_enabled.reasons)

    # Disable E02 -> feasible
    for rule in feasible_exam_dataset.constraint_rules:
        if rule.rule_code == "E02":
            rule.is_enabled = False

    res_disabled = schedule_exams(feasible_exam_dataset, time_limit_s=15.0, random_seed=1)
    assert res_disabled.status in ("optimal", "feasible")
    assert len(res_disabled.entries) == 5


# ==============================================================================
# Soft Examination Preferences Tests (ES01–ES03)
# ==============================================================================


def test_es01_soft_preference_spreads_batch_exams_across_different_days(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """ES01: Spread the exams of one batch over different days."""
    feasible_exam_dataset.exam_entries = []
    feasible_exam_dataset.exam_room_allocations = []

    res_es01_on = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert res_es01_on.status in ("optimal", "feasible")
    assert res_es01_on.soft_penalties["ES01"] == 0

    slots_by_id = feasible_exam_dataset.exam_slots_by_id
    course_batches = feasible_exam_dataset.course_batches()
    for batch_id in (1, 2):
        batch_dates = [
            slots_by_id[e.exam_slot_id].exam_date
            for e in res_es01_on.entries
            if batch_id in course_batches[e.course_id]
        ]
        # Each batch has 3 exams and they are spread across 3 distinct dates
        assert len(batch_dates) == 3
        assert len(set(batch_dates)) == 3


def test_es02_soft_preference_minimises_rooms_per_exam(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """ES02: Use as few rooms as possible per exam."""
    feasible_exam_dataset.exam_entries = []
    feasible_exam_dataset.exam_room_allocations = []

    result = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert result.status in ("optimal", "feasible")

    allocs_by_entry = {}
    for alloc in result.room_allocations:
        allocs_by_entry.setdefault(alloc.exam_entry_id, []).append(alloc)

    entries_by_course = {e.course_id: e for e in result.entries}
    # Course 1 (CS-326, 85 students) requires minimum 2 rooms (max single room is 60)
    assert len(allocs_by_entry[entries_by_course[1].exam_entry_id]) == 2
    # Courses 2, 3, 4, 5 (40–45 students each) each fit in 1 room
    for cid in (2, 3, 4, 5):
        assert len(allocs_by_entry[entries_by_course[cid].exam_entry_id]) == 1

    # Only 1 extra room used across the entire exam schedule (weight=5 -> penalty=5)
    assert result.soft_penalties["ES02"] == 5


def test_es03_soft_preference_keeps_exam_rooms_in_same_building(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """ES03: Keep the rooms of one exam in the same building."""
    from engine.models import Room

    # Configure rooms so Annex Block has a 50-seat Exam Hall, while Main Block has
    # two Lecture rooms (45 and 40 seats) that together hold CS-326 (85 students).
    feasible_exam_dataset.rooms = [
        Room(
            room_id=10,
            room_code="Annex Hall",
            building="Annex Block",
            capacity=50,
            room_type="Exam Hall",
            is_active=True,
        ),
        Room(
            room_id=11,
            room_code="Main 101",
            building="Main Block",
            capacity=45,
            room_type="Lecture",
            is_active=True,
        ),
        Room(
            room_id=12,
            room_code="Main 102",
            building="Main Block",
            capacity=40,
            room_type="Lecture",
            is_active=True,
        ),
    ]
    feasible_exam_dataset.exam_entries = []
    feasible_exam_dataset.exam_room_allocations = []

    # With ES03 enabled, CS-326 (85 students) uses Main 101 (45) + Main 102 (40) in Main Block
    res_es03_on = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert res_es03_on.status in ("optimal", "feasible")
    assert res_es03_on.soft_penalties["ES03"] == 0

    rooms_by_id = feasible_exam_dataset.rooms_by_id
    cs326_entry = next(e for e in res_es03_on.entries if e.course_id == 1)
    cs326_buildings = {
        rooms_by_id[a.room_id].building
        for a in res_es03_on.room_allocations
        if a.exam_entry_id == cs326_entry.exam_entry_id
    }
    assert cs326_buildings == {"Main Block"}

    # When ES03 is disabled, Exam Hall preference picks Annex Hall (50) + Main 101 (35) across 2 buildings
    for rule in feasible_exam_dataset.constraint_rules:
        if rule.rule_code == "ES03":
            rule.is_enabled = False

    res_es03_off = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert res_es03_off.status in ("optimal", "feasible")
    cs326_entry_off = next(e for e in res_es03_off.entries if e.course_id == 1)
    cs326_buildings_off = {
        rooms_by_id[a.room_id].building
        for a in res_es03_off.room_allocations
        if a.exam_entry_id == cs326_entry_off.exam_entry_id
    }
    assert cs326_buildings_off == {"Annex Block", "Main Block"}


def test_exam_soft_breakdown_objective_score_and_ui_summary(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """Milestone 4: Verify objective_score, max_score, soft_breakdown, and UI score_summary for ES01–ES03."""
    feasible_exam_dataset.exam_entries = []
    feasible_exam_dataset.exam_room_allocations = []

    result = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert result.status in ("optimal", "feasible")
    assert result.objective_score is not None
    assert result.max_score > 0
    assert result.max_possible_score == result.max_score
    assert 0 <= result.objective_score <= result.max_score
    assert result.score_summary.startswith(f"score {int(result.objective_score)} (")
    assert result.score_summary.endswith("% of maximum)")

    for code in ("ES01", "ES02", "ES03"):
        assert code in result.soft_breakdown
        bd = result.soft_breakdown[code]
        assert bd.rule_code == code
        assert bd.description != ""
        assert bd.satisfied_count + bd.violated_count == bd.total_count
        assert bd.weighted_contribution == bd.weighted_score
        assert bd["satisfied_count"] == bd.satisfied_count
        assert bd["violated_count"] == bd.violated_count
        assert bd["weighted_contribution"] == bd.weighted_contribution

    # ES01 and ES03 have 0 violations on seed_exam.json; ES02 has 1 extra room above single-room (CS-326 uses 2 rooms)
    assert result.soft_breakdown["ES01"].violated_count == 0
    assert result.soft_breakdown["ES02"].satisfied_count == 4
    assert result.soft_breakdown["ES02"].violated_count == 1
    assert result.soft_breakdown["ES03"].violated_count == 0

    total_weighted = sum(
        bd.weighted_contribution for bd in result.soft_breakdown.values()
    )
    assert total_weighted == int(result.objective_score)
    total_max = sum(
        bd.max_weighted_score for bd in result.soft_breakdown.values()
    )
    assert total_max == result.max_score


def test_exam_locked_sessions_are_preserved(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """FR-6.10: Locked exam entries stay in their fixed exam_slot_id and room_allocations."""
    from engine.models import ExamEntry, ExamRoomAllocation

    # Lock Course 2 (CS-310, 45 students) to exam_slot_id=6 and room_id=2 (Rm 301, cap 50)
    feasible_exam_dataset.exam_entries = [
        ExamEntry(
            exam_entry_id=1,
            schedule_id=2,
            course_id=2,
            exam_slot_id=6,
            student_count=45,
            is_locked=True,
            is_manual_override=False,
        )
    ]
    feasible_exam_dataset.exam_room_allocations = [
        ExamRoomAllocation(
            allocation_id=1,
            exam_entry_id=1,
            room_id=2,
            seats_allocated=45,
        )
    ]

    result = schedule_exams(feasible_exam_dataset, time_limit_s=30.0, random_seed=1)
    assert result.status in ("optimal", "feasible")
    assert validate_exam_schedule(
        feasible_exam_dataset,
        entries=result.entries,
        allocations=result.room_allocations,
    ) == []

    c2_entry = next(e for e in result.entries if e.course_id == 2)
    assert c2_entry.is_locked is True
    assert c2_entry.exam_slot_id == 6
    c2_rooms = [
        (a.room_id, a.seats_allocated)
        for a in result.room_allocations
        if a.exam_entry_id == c2_entry.exam_entry_id
    ]
    assert c2_rooms == [(2, 45)]


def test_exam_deterministic_seed_and_extensible_soft_constraint_interface(
    feasible_exam_dataset: TimetableDataset,
) -> None:
    """FR-6.9 & SRS 4.3.5: Deterministic seed repeatability and extensible BaseConstraint for exams."""
    from engine.constraints import BaseConstraint, SOFT_EXAM_CONSTRAINTS
    from engine.models import ConstraintRule, SoftConstraintBreakdown

    class ES04PreferMorningExamSessions(BaseConstraint):
        rule_code = "ES04"
        rule_type = "Soft"
        conflict_type = "MorningExamPreference"
        mandatory = False
        default_weight = 5
        description_text = "Prefer scheduling exams in morning sessions."

        def add_to_model(self, model, context, param_value=None, weight=None):
            return None

        def evaluate_score(
            self,
            dataset,
            entries=None,
            *,
            weight=None,
            param_value=None,
            is_enabled=True,
            previous_entries=None,
            allocations=None,
            term_id=None,
        ):
            active_entries = dataset.exam_entries if entries is None else entries
            w = (self.default_weight if weight is None else int(weight)) if is_enabled else 0
            slots_by_id = dataset.exam_slots_by_id
            satisfied = sum(
                1
                for e in active_entries
                if slots_by_id[e.exam_slot_id].session_label == "Morning"
            )
            total = len(active_entries)
            violated = total - satisfied
            return SoftConstraintBreakdown(
                rule_code=self.rule_code,
                description=self.describe(),
                is_enabled=is_enabled and w > 0,
                weight=w,
                param_value=param_value,
                satisfied_count=satisfied,
                violated_count=violated,
                total_count=total,
                weighted_score=float(w * satisfied),
                max_weighted_score=float(w * total),
                weighted_penalty=float(w * violated),
            )

        def validate(self, dataset, entries=None, param_value=None):
            return []

    feasible_exam_dataset.exam_entries = []
    feasible_exam_dataset.exam_room_allocations = []
    exam_cfg_id = next(
        (c.config_id for c in feasible_exam_dataset.scheduling_configs if c.schedule_type == "Exam"),
        1,
    )
    feasible_exam_dataset.constraint_rules.append(
        ConstraintRule(
            rule_id=99,
            config_id=exam_cfg_id,
            rule_code="ES04",
            rule_type="Soft",
            is_enabled=True,
            weight=4,
            param_value=None,
        )
    )
    custom_soft = dict(SOFT_EXAM_CONSTRAINTS)
    custom_soft["ES04"] = ES04PreferMorningExamSessions()

    res1 = schedule_exams(
        feasible_exam_dataset,
        time_limit_s=30.0,
        random_seed=7,
        soft_constraints=custom_soft,
    )
    res2 = schedule_exams(
        feasible_exam_dataset,
        time_limit_s=30.0,
        random_seed=7,
        soft_constraints=custom_soft,
    )
    assert res1.status in ("optimal", "feasible")
    assert "ES04" in res1.soft_breakdown
    assert res1.soft_breakdown["ES04"].weight == 4
    assert [
        (e.course_id, e.exam_slot_id) for e in res1.entries
    ] == [(e.course_id, e.exam_slot_id) for e in res2.entries]


