"""Pytest test suite for Milestone 2: `engine/timetable_solver.py` (OR-Tools CP-SAT).

Covers:
1. Solving the feasible seed dataset (`data/seed_timetable.json`) and verifying zero hard violations via the independent validator.
2. Solving the deliberately infeasible dataset (`data/infeasible_timetable.json`) and verifying `infeasible` status and explanatory reasons.
3. Enforcing hard constraints H01–H10, respecting mandatory rules (H01, H02, H03, H08 per FR-5.2) and optional toggles (H04, H05, H06, H07, H09, H10).
4. Time limit parameter (default 120 s per C-4) and deterministic random seed repeatability (FR-6.9).
5. Locked session pinning (FR-6.10) and independent validator rejection gate (FR-6.7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.models import (
    InstructorAvailability,
    TimetableDataset,
    TimetableEntry,
    Violation,
    load_dataset_from_json,
)
from engine.timetable_solver import (
    SOLVER_LIMIT_DEFAULT,
    TimetableSolver,
    solve_timetable,
)
from engine.validator import TimetableValidator, validate_timetable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEED_JSON_PATH = DATA_DIR / "seed_timetable.json"
INFEASIBLE_JSON_PATH = DATA_DIR / "infeasible_timetable.json"


@pytest.fixture()
def seed_dataset() -> TimetableDataset:
    """Load a fresh copy of the feasible seed dataset with cleared schedule entries."""
    ds = load_dataset_from_json(SEED_JSON_PATH)
    ds.timetable_entries = []
    return ds


@pytest.fixture()
def infeasible_dataset() -> TimetableDataset:
    """Load a fresh copy of the deliberately infeasible dataset."""
    return load_dataset_from_json(INFEASIBLE_JSON_PATH)


def _set_rule_enabled(dataset: TimetableDataset, rule_code: str, enabled: bool) -> None:
    for rule in dataset.constraint_rules:
        if rule.rule_code == rule_code:
            rule.is_enabled = enabled
            return


def test_default_time_limit_constant() -> None:
    """Constraint C-4 & Appendix A.1: Default solver time limit is 120 seconds."""
    assert SOLVER_LIMIT_DEFAULT == 120.0


def test_solve_seed_dataset_feasible_and_validated(seed_dataset: TimetableDataset) -> None:
    """Solve `data/seed_timetable.json` from scratch and verify all H01–H10 hold."""
    result = solve_timetable(seed_dataset, time_limit=120, random_seed=1)

    assert result.solver_status in ("optimal", "feasible")
    assert result.solver_status == "optimal"
    assert result.is_feasible is True
    assert result.run_time >= 0.0
    assert result.run_time < 120.0
    assert result.reasons == []
    assert result.violations == []
    assert result.schedule_record is not None
    assert result.schedule_record.status == "Generated"

    # 4 offerings: Off 1 (3 Lec + 2 Lab), Off 2 (3 Lec + 2 Lab), Off 3 (3 Lec), Off 4 (3 Lec + 2 Lab) = 18 entries
    assert len(result.schedule) == 18

    # Independent validator must find 0 violations
    violations = validate_timetable(seed_dataset, result.schedule)
    assert violations == []


def test_solve_result_tuple_unpacking(seed_dataset: TimetableDataset) -> None:
    """Verify `(schedule, solver_status, run_time, reasons)` unpacking works."""
    schedule, solver_status, run_time, reasons = solve_timetable(
        seed_dataset, time_limit=30, random_seed=42
    )

    assert solver_status in ("optimal", "feasible")
    assert len(schedule) == 18
    assert isinstance(run_time, float)
    assert reasons == []
    assert validate_timetable(seed_dataset, schedule) == []


def test_solve_deliberately_infeasible_dataset(infeasible_dataset: TimetableDataset) -> None:
    """Solve `data/infeasible_timetable.json` and verify infeasible status and reasons."""
    result = solve_timetable(infeasible_dataset, time_limit=30, random_seed=1)

    assert result.solver_status == "infeasible"
    assert result.is_feasible is False
    assert result.schedule == []
    assert result.run_time >= 0.0
    assert result.schedule_record is not None
    assert result.schedule_record.status == "Infeasible"
    assert len(result.reasons) >= 3

    joined_reasons = " | ".join(result.reasons)
    # Must report H04 room capacity, H06 instructor availability, and H10 instructor workload
    assert "H04" in joined_reasons
    assert "CS-310" in joined_reasons
    assert "H06" in joined_reasons or "Availability" in joined_reasons
    assert "Prof. Sara Khan" in joined_reasons
    assert "H10" in joined_reasons
    assert "Dr. Fakhra Aftab" in joined_reasons


def test_deterministic_seed_produces_identical_schedule() -> None:
    """FR-6.9: Same dataset, configuration, and random seed produce the exact same schedule."""
    ds1 = load_dataset_from_json(SEED_JSON_PATH)
    ds1.timetable_entries = []
    ds2 = load_dataset_from_json(SEED_JSON_PATH)
    ds2.timetable_entries = []

    res1 = solve_timetable(ds1, time_limit=30, random_seed=7)
    res2 = solve_timetable(ds2, time_limit=30, random_seed=7)

    assert res1.solver_status == "optimal"
    assert res2.solver_status == "optimal"

    tuples_1 = [
        (e.offering_id, e.session_type, e.slot_id, e.room_id) for e in res1.schedule
    ]
    tuples_2 = [
        (e.offering_id, e.session_type, e.slot_id, e.room_id) for e in res2.schedule
    ]
    assert tuples_1 == tuples_2


def test_mandatory_constraints_always_enforced_even_if_disabled(
    seed_dataset: TimetableDataset,
) -> None:
    """FR-5.2: Mandatory constraints (H01, H02, H03, H08) cannot be bypassed by setting is_enabled=False."""
    # Restrict dataset to only 2 time slots total, while Batch 1 requires 13 session slots (H03)
    # and Instructor 1 requires 10 session slots (H01).
    seed_dataset.time_slots = seed_dataset.time_slots[:2]
    _set_rule_enabled(seed_dataset, "H01", False)
    _set_rule_enabled(seed_dataset, "H02", False)
    _set_rule_enabled(seed_dataset, "H03", False)
    _set_rule_enabled(seed_dataset, "H08", False)

    result = solve_timetable(seed_dataset, time_limit=10, random_seed=1)
    assert result.solver_status == "infeasible"
    assert result.schedule == []
    assert len(result.reasons) > 0


def test_optional_constraint_h04_capacity_toggle(seed_dataset: TimetableDataset) -> None:
    """H04 (non-mandatory): Infeasible when enrolled_count > max room capacity, feasible when H04 disabled."""
    # Set Offering 1 enrolled_count to 80 (max room capacity is 50)
    seed_dataset.course_offerings[0].enrolled_count = 80

    res_enabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_enabled.solver_status == "infeasible"
    assert any("H04" in r for r in res_enabled.reasons)

    # Disable H04 and re-solve
    _set_rule_enabled(seed_dataset, "H04", False)
    res_disabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_disabled.solver_status == "optimal"
    assert len(res_disabled.schedule) == 18
    assert validate_timetable(seed_dataset, res_disabled.schedule) == []


def test_optional_constraint_h05_room_type_toggle(seed_dataset: TimetableDataset) -> None:
    """H05 (non-mandatory): Infeasible when no Lab rooms exist and H05 enabled; feasible when H05 disabled."""
    for room in seed_dataset.rooms:
        if room.room_type == "Lab":
            room.is_active = False

    res_enabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_enabled.solver_status == "infeasible"
    assert any("H05" in r for r in res_enabled.reasons)

    _set_rule_enabled(seed_dataset, "H05", False)
    res_disabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_disabled.solver_status == "optimal"
    assert len(res_disabled.schedule) == 18
    assert validate_timetable(seed_dataset, res_disabled.schedule) == []


def test_optional_constraint_h06_availability_toggle(seed_dataset: TimetableDataset) -> None:
    """H06 (non-mandatory): Infeasible when instructor unavailable in all slots; feasible when H06 disabled."""
    seed_dataset.instructor_availability = [
        InstructorAvailability(
            availability_id=idx,
            instructor_id=3,
            slot_id=slot.slot_id,
            is_available=False,
        )
        for idx, slot in enumerate(seed_dataset.time_slots, start=1)
    ]

    res_enabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_enabled.solver_status == "infeasible"
    assert any("H06" in r for r in res_enabled.reasons)

    _set_rule_enabled(seed_dataset, "H06", False)
    res_disabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_disabled.solver_status == "optimal"
    assert len(res_disabled.schedule) == 18
    assert validate_timetable(seed_dataset, res_disabled.schedule) == []


def test_optional_constraint_h07_blocked_slot_toggle(seed_dataset: TimetableDataset) -> None:
    """H07 (non-mandatory): Infeasible when all slots are blocked; feasible when H07 disabled."""
    for slot in seed_dataset.time_slots:
        slot.is_blocked = True
        slot.block_reason = "Holiday"

    res_enabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_enabled.solver_status == "infeasible"
    assert any("H07" in r for r in res_enabled.reasons)

    _set_rule_enabled(seed_dataset, "H07", False)
    res_disabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_disabled.solver_status == "optimal"
    assert len(res_disabled.schedule) == 18
    assert validate_timetable(seed_dataset, res_disabled.schedule) == []


def test_optional_constraint_h09_lab_contiguity_toggle(seed_dataset: TimetableDataset) -> None:
    """H09 (non-mandatory): Infeasible when no 2 consecutive unblocked slots exist; feasible when H09 disabled."""
    # Block slot_index 2 and 4 (in addition to 5), leaving slot_index {1, 3, 6} (15 unblocked slots/week)
    # with no two consecutive unblocked slots on any day.
    for slot in seed_dataset.time_slots:
        if slot.slot_index in (2, 4):
            slot.is_blocked = True
            slot.block_reason = "Alternating break"

    res_enabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_enabled.solver_status == "infeasible"
    assert any("H09" in r for r in res_enabled.reasons)

    _set_rule_enabled(seed_dataset, "H09", False)
    res_disabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_disabled.solver_status == "optimal"
    assert len(res_disabled.schedule) == 18
    assert validate_timetable(seed_dataset, res_disabled.schedule) == []


def test_optional_constraint_h10_workload_toggle(seed_dataset: TimetableDataset) -> None:
    """H10 (non-mandatory): Infeasible when instructor workload exceeds max_weekly_hours; feasible when H10 disabled."""
    # Instructor 1 needs 10 weekly hours (Offering 1: 5h, Offering 4: 5h); cap at 6h
    seed_dataset.instructors[0].max_weekly_hours = 6

    res_enabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_enabled.solver_status == "infeasible"
    assert any("H10" in r for r in res_enabled.reasons)

    _set_rule_enabled(seed_dataset, "H10", False)
    res_disabled = solve_timetable(seed_dataset, time_limit=15, random_seed=1)
    assert res_disabled.solver_status == "optimal"
    assert len(res_disabled.schedule) == 18
    assert validate_timetable(seed_dataset, res_disabled.schedule) == []


def test_locked_sessions_are_preserved_in_new_run() -> None:
    """FR-6.10: Locked entries stay in their assigned slot and room when regenerating."""
    ds = load_dataset_from_json(SEED_JSON_PATH)
    # Keep only 2 locked entries: Offering 3 Lecture in (slot_id=27, room_id=2)
    # and Offering 1 Lab block in (slot_id=8, 9, room_id=5)
    locked_entries = [
        TimetableEntry(
            entry_id=1,
            schedule_id=1,
            offering_id=3,
            instructor_id=3,
            batch_id=1,
            room_id=2,
            slot_id=27,
            session_type="Lecture",
            is_locked=True,
        ),
        TimetableEntry(
            entry_id=2,
            schedule_id=1,
            offering_id=1,
            instructor_id=1,
            batch_id=1,
            room_id=5,
            slot_id=8,
            session_type="Lab",
            is_locked=True,
        ),
        TimetableEntry(
            entry_id=3,
            schedule_id=1,
            offering_id=1,
            instructor_id=1,
            batch_id=1,
            room_id=5,
            slot_id=9,
            session_type="Lab",
            is_locked=True,
        ),
    ]
    ds.timetable_entries = locked_entries

    result = solve_timetable(ds, time_limit=30, random_seed=1)
    assert result.solver_status == "optimal"

    # Check that the locked assignments are present and marked is_locked=True
    off3_lecs = [
        (e.slot_id, e.room_id, e.is_locked)
        for e in result.schedule
        if e.offering_id == 3 and e.session_type == "Lecture"
    ]
    assert (27, 2, True) in off3_lecs

    off1_labs = [
        (e.slot_id, e.room_id, e.is_locked)
        for e in result.schedule
        if e.offering_id == 1 and e.session_type == "Lab"
    ]
    assert (8, 5, True) in off1_labs
    assert (9, 5, True) in off1_labs


def test_validator_rejection_gate_discards_invalid_solution(
    seed_dataset: TimetableDataset,
) -> None:
    """FR-6.7: If the independent validator reports a violation, the solution is rejected."""

    class FailingValidator(TimetableValidator):
        def validate(self, dataset, entries=None, config_id=None):
            return [
                Violation(
                    rule_code="H01",
                    conflict_type="Instructor",
                    severity="Hard",
                    description="Simulated independent validator conflict",
                    entity_ref="instructor_id=1",
                )
            ]

    solver = TimetableSolver(validator=FailingValidator())
    result = solver.solve(seed_dataset, time_limit=15, random_seed=1)

    assert result.solver_status == "infeasible"
    assert result.schedule == []
    assert len(result.violations) == 1
    assert any("FR-6.7 Independent Validator Rejection" in r for r in result.reasons)


def test_input_completeness_check_reports_defects(seed_dataset: TimetableDataset) -> None:
    """FR-6.1: Missing or inactive course/batch/instructor is caught before solving."""
    seed_dataset.courses[0].is_active = False

    result = solve_timetable(seed_dataset, time_limit=10, random_seed=1)
    assert result.solver_status == "infeasible"
    assert result.schedule == []
    assert any("FR-6.1 Input Defect" in r for r in result.reasons)


# ==============================================================================
# Milestone 4: Timetable Soft Constraints (S01–S06), Objective & Breakdown Tests
# ==============================================================================


def _set_soft_rule(
    dataset: TimetableDataset,
    rule_code: str,
    *,
    enabled: bool = True,
    weight: int = 5,
    param_value: int | None = None,
) -> None:
    from engine.models import ConstraintRule

    for rule in dataset.constraint_rules:
        if rule.rule_code == rule_code:
            rule.is_enabled = enabled
            rule.weight = weight
            rule.param_value = param_value
            return

    next_id = max((r.rule_id for r in dataset.constraint_rules), default=0) + 1
    config_id = dataset.scheduling_configs[0].config_id if dataset.scheduling_configs else 1
    dataset.constraint_rules.append(
        ConstraintRule(
            rule_id=next_id,
            config_id=config_id,
            rule_code=rule_code,
            rule_type="Soft",
            is_enabled=enabled,
            weight=weight,
            param_value=param_value,
        )
    )


def test_soft_constraints_objective_breakdown_and_score_summary(
    seed_dataset: TimetableDataset,
) -> None:
    """Verify objective_score, max_score, per-constraint breakdown, and UI score_summary."""
    result = solve_timetable(seed_dataset, time_limit=30, random_seed=1)

    assert result.solver_status == "optimal"
    assert result.objective_score is not None
    assert result.max_score > 0
    assert result.max_possible_score == result.max_score
    assert 0 <= result.objective_score <= result.max_score
    assert result.schedule_record is not None
    assert result.schedule_record.objective_score == float(result.objective_score)

    # Check UI summary string format: "score X (Y% of maximum)"
    assert result.score_summary.startswith(f"score {int(result.objective_score)} (")
    assert result.score_summary.endswith("% of maximum)")

    # Check breakdown contains S01–S06
    for code in ("S01", "S02", "S03", "S04", "S05", "S06"):
        assert code in result.soft_breakdown
        bd = result.soft_breakdown[code]
        assert bd.rule_code == code
        assert bd.description != ""
        assert bd.satisfied_count + bd.violated_count == bd.total_count
        assert bd.weighted_contribution == bd.weighted_score
        assert bd["satisfied_count"] == bd.satisfied_count
        assert bd["violated_count"] == bd.violated_count
        assert bd["weighted_contribution"] == bd.weighted_contribution

    # Sum of active weighted contributions equals objective_score
    total_weighted = sum(
        bd.weighted_contribution for bd in result.soft_breakdown.values()
    )
    assert total_weighted == int(result.objective_score)
    total_max = sum(
        bd.max_weighted_score for bd in result.soft_breakdown.values()
    )
    assert total_max == result.max_score

    # Every solution still passes the independent hard validator
    assert validate_timetable(seed_dataset, result.schedule) == []


def test_s01_minimises_batch_idle_gaps_on_a_day(
    seed_dataset: TimetableDataset,
) -> None:
    """S01: Minimise idle gaps between the sessions of a batch on a day."""
    # Enable only S01 with weight 10
    for code in ("S01", "S02", "S03", "S04", "S05", "S06"):
        _set_soft_rule(seed_dataset, code, enabled=(code == "S01"), weight=10 if code == "S01" else 0)

    result = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert result.solver_status == "optimal"
    s01_bd = result.soft_breakdown["S01"]
    assert s01_bd.weight == 10
    assert s01_bd.violated_count == 0
    assert s01_bd.satisfied_count == s01_bd.total_count
    assert s01_bd.weighted_score == s01_bd.max_weighted_score

    # Verify that introducing an artificial gap in an entry list reduces S01 score
    from engine.constraints import S01BatchIdleGaps

    gap_entries = [
        TimetableEntry(
            entry_id=1,
            schedule_id=1,
            offering_id=1,
            instructor_id=1,
            batch_id=1,
            room_id=2,
            slot_id=1,  # Mon slot_index 1
            session_type="Lecture",
        ),
        TimetableEntry(
            entry_id=2,
            schedule_id=1,
            offering_id=2,
            instructor_id=2,
            batch_id=1,
            room_id=2,
            slot_id=3,  # Mon slot_index 3 (slot_index 2 is an idle gap!)
            session_type="Lecture",
        ),
    ]
    bd_with_gap = S01BatchIdleGaps().evaluate_score(
        seed_dataset, gap_entries, weight=8, is_enabled=True
    )
    assert bd_with_gap.violated_count == 1
    assert bd_with_gap.weighted_penalty == 8


def test_s02_spreads_offering_sessions_across_different_days(
    seed_dataset: TimetableDataset,
) -> None:
    """S02: Spread the sessions of one offering over different days."""
    result = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert result.solver_status == "optimal"

    s02_bd = result.soft_breakdown["S02"]
    assert s02_bd.violated_count == 0
    assert s02_bd.satisfied_count == s02_bd.total_count

    slots_by_id = seed_dataset.time_slots_by_id
    # Each offering has 3 lectures; verify all 3 lectures of each offering are on distinct days
    for off in seed_dataset.course_offerings:
        lec_days = [
            slots_by_id[e.slot_id].day_of_week
            for e in result.schedule
            if e.offering_id == off.offering_id and e.session_type == "Lecture"
        ]
        assert len(lec_days) == 3
        assert len(set(lec_days)) == 3


def test_s03_keeps_batch_daily_sessions_at_or_below_parameter(
    seed_dataset: TimetableDataset,
) -> None:
    """S03: Keep the sessions of a batch per day at or below a parameter (default 5, custom 3)."""
    # Default parameter is 5
    res_default = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert res_default.soft_breakdown["S03"].param_value == 5
    assert res_default.soft_breakdown["S03"].violated_count == 0

    # Set S03 parameter to 3 (Batch 1 has 13 weekly slots across 5 days -> 3, 3, 3, 2, 2)
    _set_soft_rule(seed_dataset, "S03", enabled=True, weight=10, param_value=3)
    res_tight = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert res_tight.solver_status == "optimal"
    assert res_tight.soft_breakdown["S03"].param_value == 3
    assert res_tight.soft_breakdown["S03"].violated_count == 0

    slots_by_id = seed_dataset.time_slots_by_id
    for batch in seed_dataset.batches:
        for day in range(1, 6):
            day_count = sum(
                1
                for e in res_tight.schedule
                if e.batch_id == batch.batch_id and slots_by_id[e.slot_id].day_of_week == day
            )
            assert day_count <= 3


def test_s04_keeps_instructor_consecutive_teaching_slots_within_limit(
    seed_dataset: TimetableDataset,
) -> None:
    """S04: Keep consecutive teaching slots of an instructor at or below a parameter (default 3, custom 2)."""
    _set_soft_rule(seed_dataset, "S04", enabled=True, weight=10, param_value=2)
    result = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert result.solver_status == "optimal"

    s04_bd = result.soft_breakdown["S04"]
    assert s04_bd.param_value == 2
    assert s04_bd.violated_count == 0
    assert s04_bd.satisfied_count == s04_bd.total_count

    # Also test S04 evaluation when an instructor teaches 4 consecutive slots (limit=3)
    from engine.constraints import S04InstructorConsecutiveSlots

    consec_entries = [
        TimetableEntry(
            entry_id=idx,
            schedule_id=1,
            offering_id=1,
            instructor_id=1,
            batch_id=1,
            room_id=2,
            slot_id=idx,  # Mon slots 1, 2, 3, 4 (all consecutive!)
            session_type="Lecture",
        )
        for idx in (1, 2, 3, 4)
    ]
    bd_consec = S04InstructorConsecutiveSlots().evaluate_score(
        seed_dataset, consec_entries, weight=6, param_value=3, is_enabled=True
    )
    assert bd_consec.violated_count == 1
    assert bd_consec.weighted_penalty == 6


def test_s05_prefers_previous_schedule_slot_and_room_and_skips_when_none(
    seed_dataset: TimetableDataset,
) -> None:
    """S05: Prefer same slot and room as previous schedule version; skip when none is given."""
    # 1. When no previous schedule is passed, S05 is skipped (total_count == 0, score == 0)
    res_no_prev = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    s05_none = res_no_prev.soft_breakdown["S05"]
    assert s05_none.total_count == 0
    assert s05_none.satisfied_count == 0
    assert s05_none.violated_count == 0
    assert s05_none.weighted_score == 0
    assert s05_none.max_weighted_score == 0

    # 2. Pass the generated schedule as previous_schedule with S05 weight=10
    _set_soft_rule(seed_dataset, "S05", enabled=True, weight=10)
    res_with_prev = solve_timetable(
        seed_dataset,
        time_limit=30,
        random_seed=99,
        previous_schedule=res_no_prev.schedule,
    )
    assert res_with_prev.solver_status == "optimal"
    s05_active = res_with_prev.soft_breakdown["S05"]
    assert s05_active.total_count == 18
    assert s05_active.satisfied_count == 18
    assert s05_active.violated_count == 0
    assert s05_active.weighted_score == 180
    assert s05_active.max_weighted_score == 180

    # All (offering_id, session_type, slot_id, room_id) match the previous schedule
    prev_set = {
        (e.offering_id, e.session_type, e.slot_id, e.room_id)
        for e in res_no_prev.schedule
    }
    curr_set = {
        (e.offering_id, e.session_type, e.slot_id, e.room_id)
        for e in res_with_prev.schedule
    }
    assert curr_set == prev_set


def test_s06_prefers_smallest_fitting_room(
    seed_dataset: TimetableDataset,
) -> None:
    """S06: Prefer the smallest room that fits the offering."""
    # Set Offering 4 enrolled_count to 28 so its smallest fitting Lecture room is Rm 105 (room_id=3, cap=30),
    # while Offerings 1, 2, 3 have 45 students -> smallest fitting Lecture room is Rm 204 (room_id=2, cap=45).
    seed_dataset.course_offerings[3].enrolled_count = 28

    # Enable only S06 with weight 10
    for code in ("S01", "S02", "S03", "S04", "S05", "S06"):
        _set_soft_rule(seed_dataset, code, enabled=(code == "S06"), weight=10 if code == "S06" else 0)

    result = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert result.solver_status == "optimal"
    s06_bd = result.soft_breakdown["S06"]
    assert s06_bd.weight == 10
    assert s06_bd.violated_count == 0
    assert s06_bd.satisfied_count == 18

    for entry in result.schedule:
        if entry.session_type == "Lecture":
            if entry.offering_id in (1, 2, 3):
                assert entry.room_id == 2
            elif entry.offering_id == 4:
                assert entry.room_id == 3


def test_zero_weight_or_disabled_soft_constraints_are_ignored(
    seed_dataset: TimetableDataset,
) -> None:
    """Weights of 0 or is_enabled=False ignore the soft rule (0 contribution to objective)."""
    for code in ("S01", "S02", "S03", "S04", "S05", "S06"):
        _set_soft_rule(seed_dataset, code, enabled=False, weight=0)

    result = solve_timetable(seed_dataset, time_limit=30, random_seed=1)
    assert result.solver_status == "optimal"
    assert result.objective_score == 0.0
    assert result.max_score == 0
    assert result.score_summary == "score 0 (100% of maximum)"
    assert validate_timetable(seed_dataset, result.schedule) == []


def test_soft_constraints_never_violate_hard_constraints_even_with_conflicting_previous_schedule(
    seed_dataset: TimetableDataset,
) -> None:
    """Soft constraints must never cause a hard-constraint violation (validated via TimetableValidator)."""
    # Construct a previous schedule that violates hard constraints (puts all lectures in slot_id=1, room_id=3)
    bad_previous = [
        TimetableEntry(
            entry_id=idx,
            schedule_id=1,
            offering_id=off.offering_id,
            instructor_id=off.instructor_id,
            batch_id=off.batch_id,
            room_id=3,  # capacity 40 < 42 for offerings 1, 2, 3!
            slot_id=1,  # all in the same slot!
            session_type="Lecture",
        )
        for idx, off in enumerate(seed_dataset.course_offerings, start=1)
    ]
    for code in ("S01", "S02", "S03", "S04", "S05", "S06"):
        _set_soft_rule(seed_dataset, code, enabled=True, weight=10)

    result = solve_timetable(
        seed_dataset,
        time_limit=30,
        random_seed=1,
        previous_schedule=bad_previous,
    )
    assert result.solver_status == "optimal"
    assert result.violations == []
    assert validate_timetable(seed_dataset, result.schedule) == []


def test_extensible_soft_constraint_interface_srs_4_3_5(
    seed_dataset: TimetableDataset,
) -> None:
    """SRS 4.3.5: A new soft rule implementing BaseConstraint can be added without modifying solver code."""
    from engine.constraints import BaseConstraint, SOFT_TIMETABLE_CONSTRAINTS
    from engine.models import ConstraintRule, SoftConstraintBreakdown

    class S07PreferMorningSlots(BaseConstraint):
        rule_code = "S07"
        rule_type = "Soft"
        conflict_type = "MorningSlotPreference"
        mandatory = False
        default_weight = 5
        description_text = "Prefer scheduling sessions in morning slots (slot_index <= 3)."

        def add_to_model(self, model, context, param_value=None, weight=None):
            w = self.default_weight if weight is None else int(weight)
            if w <= 0:
                return
            for u in context.sessions:
                morning_vars = [
                    context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for slot in context.slots
                    for room in context.rooms
                    if slot.slot_index <= 3
                    and (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                context.soft_max_score += w
                if morning_vars:
                    context.soft_reward_terms.append(w * sum(morning_vars))

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
            active_entries = dataset.timetable_entries if entries is None else entries
            w = (self.default_weight if weight is None else int(weight)) if is_enabled else 0
            slots_by_id = dataset.slots_by_id
            satisfied = sum(
                1 for e in active_entries if slots_by_id[e.slot_id].slot_index <= 3
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

    seed_dataset.constraint_rules.append(
        ConstraintRule(
            rule_id=99,
            config_id=1,
            rule_code="S07",
            rule_type="Soft",
            is_enabled=True,
            weight=8,
            param_value=None,
        )
    )

    custom_soft = dict(SOFT_TIMETABLE_CONSTRAINTS)
    custom_soft["S07"] = S07PreferMorningSlots()

    result = solve_timetable(
        seed_dataset,
        time_limit=30,
        random_seed=1,
        soft_constraints=custom_soft,
    )
    assert result.solver_status == "optimal"
    assert "S07" in result.soft_breakdown
    assert result.soft_breakdown["S07"].weight == 8
    assert result.soft_breakdown["S07"].satisfied_count == 18
    assert result.soft_breakdown["S07"].violated_count == 0

