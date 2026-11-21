"""Pytest test suite for the standalone ATES timetable validator (H01–H10).

Verifies:
1. One valid baseline schedule loaded from `data/seed_timetable.json` passes with zero violations.
2. Ten deliberately violating schedules (one per hard constraint H01–H10) each trigger
   the exact expected violation type and report the affected entities (SRS Section 4.3.1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.models import TimetableDataset, load_dataset_from_json
from engine.validator import (
    ExamValidator,
    TimetableValidator,
    validate_exam_schedule,
    validate_timetable,
)

SEED_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_timetable.json"
SEED_EXAM_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_exam.json"


@pytest.fixture()
def dataset() -> TimetableDataset:
    """Load a fresh copy of the seed timetable dataset before each test."""
    return load_dataset_from_json(SEED_JSON_PATH)


@pytest.fixture()
def exam_dataset() -> TimetableDataset:
    """Load a fresh copy of the seed exam dataset before each test."""
    return load_dataset_from_json(SEED_EXAM_JSON_PATH)



def _get_entry(dataset: TimetableDataset, entry_id: int):
    for entry in dataset.timetable_entries:
        if entry.entry_id == entry_id:
            return entry
    raise KeyError(f"entry_id={entry_id} not found in seed dataset")


def test_valid_seed_schedule_has_no_violations(dataset: TimetableDataset) -> None:
    """Baseline valid schedule from `data/seed_timetable.json` satisfies all H01–H10."""
    violations = validate_timetable(dataset)
    assert violations == []


def test_h01_instructor_clash(dataset: TimetableDataset) -> None:
    """H01: An instructor teaches at most one session in a slot."""
    # Move entry_id=14 (Instructor 1, Batch 2, Room 2) from slot_id=2 to slot_id=1,
    # clashing with entry_id=1 (Instructor 1, Batch 1, Room 1) in slot_id=1.
    entry_14 = _get_entry(dataset, 14)
    entry_14.slot_id = 1

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H01"
    assert v.conflict_type == "Instructor"
    assert v.severity == "Hard"
    assert v.affected_entities["instructor_id"] == 1
    assert v.affected_entities["slot_id"] == 1
    assert set(v.affected_entities["entry_ids"]) == {1, 14}
    assert "instructor_id=1" in v.entity_ref


def test_h02_room_clash(dataset: TimetableDataset) -> None:
    """H02: A room hosts at most one session in a slot."""
    # Move entry_id=11 (Offering 3, Batch 1, Instructor 3, Room 2) from slot_id=7 to slot_id=2,
    # clashing only on Room 2 with entry_id=14 (Offering 4, Batch 2, Instructor 1, Room 2).
    entry_11 = _get_entry(dataset, 11)
    entry_11.slot_id = 2

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H02"
    assert v.conflict_type == "Room"
    assert v.severity == "Hard"
    assert v.affected_entities["room_id"] == 2
    assert v.affected_entities["room_code"] == "Rm 204"
    assert v.affected_entities["slot_id"] == 2
    assert set(v.affected_entities["entry_ids"]) == {11, 14}
    assert "room_id=2" in v.entity_ref


def test_h03_batch_clash(dataset: TimetableDataset) -> None:
    """H03: A batch attends at most one session in a slot."""
    # Move entry_id=11 (Batch 1, Instructor 3, Room 2) from slot_id=7 to slot_id=1,
    # clashing only on Batch 1 with entry_id=1 (Batch 1, Instructor 1, Room 1).
    entry_11 = _get_entry(dataset, 11)
    entry_11.slot_id = 1

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H03"
    assert v.conflict_type == "Batch"
    assert v.severity == "Hard"
    assert v.affected_entities["batch_id"] == 1
    assert v.affected_entities["slot_id"] == 1
    assert set(v.affected_entities["entry_ids"]) == {1, 11}
    assert "batch_id=1" in v.entity_ref


def test_h04_room_capacity(dataset: TimetableDataset) -> None:
    """H04: Room capacity is at least the enrolled count of the offering."""
    # Move entry_id=1 (Offering 1, enrolled_count=45) into Room 3 (Rm 105, capacity=30).
    entry_1 = _get_entry(dataset, 1)
    entry_1.room_id = 3

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H04"
    assert v.conflict_type == "Capacity"
    assert v.severity == "Hard"
    assert v.affected_entities["entry_id"] == 1
    assert v.affected_entities["offering_id"] == 1
    assert v.affected_entities["room_id"] == 3
    assert v.affected_entities["room_capacity"] == 30
    assert v.affected_entities["enrolled_count"] == 45
    assert "room_id=3" in v.entity_ref


def test_h05_room_type_mismatch(dataset: TimetableDataset) -> None:
    """H05: Lab sessions are held in Lab rooms and lectures in Lecture rooms."""
    # Assign Lecture entry_id=1 to Lab 1 (room_id=4, room_type='Lab', capacity=50).
    entry_1 = _get_entry(dataset, 1)
    entry_1.room_id = 4

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H05"
    assert v.conflict_type == "RoomType"
    assert v.severity == "Hard"
    assert v.affected_entities["entry_id"] == 1
    assert v.affected_entities["room_id"] == 4
    assert v.affected_entities["session_type"] == "Lecture"
    assert v.affected_entities["room_type"] == "Lab"
    assert "entry_id=1" in v.entity_ref


def test_h06_instructor_unavailable(dataset: TimetableDataset) -> None:
    """H06: No session in a slot in which the instructor is unavailable."""
    # Instructor 1 is marked unavailable in slot_id=6 (Monday 13:00-14:00).
    entry_1 = _get_entry(dataset, 1)
    entry_1.slot_id = 6

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H06"
    assert v.conflict_type == "Availability"
    assert v.severity == "Hard"
    assert v.affected_entities["entry_id"] == 1
    assert v.affected_entities["instructor_id"] == 1
    assert v.affected_entities["slot_id"] == 6
    assert "instructor_id=1" in v.entity_ref


def test_h07_blocked_slot(dataset: TimetableDataset) -> None:
    """H07: No session in a blocked slot (break or prayer time)."""
    # slot_id=5 is Monday 12:00-13:00 with is_blocked=True ('Break / Prayer').
    entry_1 = _get_entry(dataset, 1)
    entry_1.slot_id = 5

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H07"
    assert v.conflict_type == "BlockedSlot"
    assert v.severity == "Hard"
    assert v.affected_entities["entry_id"] == 1
    assert v.affected_entities["slot_id"] == 5
    assert v.affected_entities["block_reason"] == "Break / Prayer"
    assert "slot_id=5" in v.entity_ref


def test_h08_session_count_mismatch(dataset: TimetableDataset) -> None:
    """H08: Every offering receives exactly the number of lecture sessions and lab blocks required per week."""
    # Remove one lecture entry (entry_id=13) from Offering 3 (MT-212, requires 3 lectures).
    dataset.timetable_entries = [
        e for e in dataset.timetable_entries if e.entry_id != 13
    ]

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H08"
    assert v.conflict_type == "SessionCount"
    assert v.severity == "Hard"
    assert v.affected_entities["offering_id"] == 3
    assert v.affected_entities["course_code"] == "MT-212"
    assert v.affected_entities["expected_lecture_slots"] == 3
    assert v.affected_entities["actual_lecture_slots"] == 2
    assert "offering_id=3" in v.entity_ref


def test_h09_lab_block_contiguity(dataset: TimetableDataset) -> None:
    """H09: A lab block occupies consecutive slots of one day in one room."""
    # Offering 1 has Lab entries 4 (slot_id=8, index=2) and 5 (slot_id=9, index=3) on Tuesday in Lab 2.
    # Move entry_id=5 to slot_id=10 (Tuesday, index=4) so the lab block has a gap [2, 4].
    entry_5 = _get_entry(dataset, 5)
    entry_5.slot_id = 10

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H09"
    assert v.conflict_type == "LabBlock"
    assert v.severity == "Hard"
    assert v.affected_entities["offering_id"] == 1
    assert set(v.affected_entities["entry_ids"]) == {4, 5}
    assert v.affected_entities["slot_indices"] == [2, 4]
    assert "offering_id=1" in v.entity_ref


def test_h10_instructor_workload_exceeded(dataset: TimetableDataset) -> None:
    """H10: An instructor does not exceed the daily and weekly teaching hours."""
    # Instructor 1 teaches 3 hours on Wednesday (slot_ids 13, 14, 16) with max_daily_hours=4.
    # Move entry_id=14 (Mon slot 2) -> Wed slot 15 and entry_id=16 (Fri slot 1) -> Wed slot 18,
    # giving Instructor 1 five teaching hours on Wednesday (day_of_week=3) while keeping weekly=10.
    entry_14 = _get_entry(dataset, 14)
    entry_16 = _get_entry(dataset, 16)
    entry_14.slot_id = 15
    entry_16.slot_id = 18

    violations = validate_timetable(dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "H10"
    assert v.conflict_type == "Workload"
    assert v.severity == "Hard"
    assert v.affected_entities["instructor_id"] == 1
    assert v.affected_entities["scope"] == "daily"
    assert v.affected_entities["day_of_week"] == 3
    assert v.affected_entities["actual_hours"] == 5.0
    assert v.affected_entities["max_allowed_hours"] == 4
    assert "instructor_id=1" in v.entity_ref


def test_mandatory_constraints_cannot_be_disabled_in_validator(dataset: TimetableDataset) -> None:
    """FR-5.2: Mandatory constraints (H01, H02, H03, H08) remain enforced even if marked disabled."""
    for rule in dataset.constraint_rules:
        if rule.rule_code == "H01":
            rule.is_enabled = False

    entry_14 = _get_entry(dataset, 14)
    entry_14.slot_id = 1

    validator = TimetableValidator()
    violations = validator.validate(dataset)
    assert len(violations) == 1
    assert violations[0].rule_code == "H01"


# ==============================================================================
# Examination Validator Tests (E01–E05)
# ==============================================================================


def _get_exam_entry(dataset: TimetableDataset, exam_entry_id: int):
    for entry in dataset.exam_entries:
        if entry.exam_entry_id == exam_entry_id:
            return entry
    raise KeyError(f"exam_entry_id={exam_entry_id} not found in exam dataset")


def _get_exam_allocation(dataset: TimetableDataset, allocation_id: int):
    for alloc in dataset.exam_room_allocations:
        if alloc.allocation_id == allocation_id:
            return alloc
    raise KeyError(f"allocation_id={allocation_id} not found in exam dataset")


def test_valid_seed_exam_schedule_has_no_violations(exam_dataset: TimetableDataset) -> None:
    """Baseline valid exam schedule from `data/seed_exam.json` satisfies all E01–E05."""
    violations = validate_exam_schedule(exam_dataset)
    assert violations == []


def test_e01_student_exam_clash(exam_dataset: TimetableDataset) -> None:
    """E01: Two courses that share a student are not in the same exam session."""
    # Move exam_entry_id=2 (course_id=2, CS-310, room_id=6) and exam_entry_id=4
    # (course_id=4, CS-318, room_id=1) both into exam_slot_id=4 (2026-12-15 Afternoon).
    # They share repeater student 9001 and occupy different rooms, so only E01 is violated.
    entry_2 = _get_exam_entry(exam_dataset, 2)
    entry_4 = _get_exam_entry(exam_dataset, 4)
    entry_2.exam_slot_id = 4
    entry_4.exam_slot_id = 4

    violations = validate_exam_schedule(exam_dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "E01"
    assert v.conflict_type == "StudentExamClash"
    assert v.severity == "Hard"
    assert v.affected_entities["exam_slot_id"] == 4
    assert set(v.affected_entities["course_ids"]) == {2, 4}
    assert "student:9001" in v.affected_entities["shared_students"]



def test_e02_daily_exam_limit_exceeded(exam_dataset: TimetableDataset) -> None:
    """E02: No student has more exams per day than the configured maximum."""
    # Put exam_entry_id=2 (CS-310, Batch 1) into exam_slot_id=2 (2026-12-14 Afternoon),
    # and move exam_slot_id=5 to date 2026-12-14 Evening so Batch 1 has 3 exams on 2026-12-14.
    entry_2 = _get_exam_entry(exam_dataset, 2)
    entry_2.exam_slot_id = 2
    for slot in exam_dataset.exam_slots:
        if slot.exam_slot_id == 5:
            slot.exam_date = "2026-12-14"
            slot.session_label = "Evening"
            slot.start_time = "18:00"
            slot.end_time = "21:00"

    violations = validate_exam_schedule(exam_dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "E02"
    assert v.conflict_type == "DailyExamLimit"
    assert v.severity == "Hard"
    assert v.affected_entities["student_ref"] == "batch:1"
    assert v.affected_entities["exam_date"] == "2026-12-14"
    assert v.affected_entities["exam_count"] == 3
    assert v.affected_entities["max_allowed"] == 2


def test_e03_exam_seat_allocation_exceeds_room_capacity(exam_dataset: TimetableDataset) -> None:
    """E03: Allocated seats equal the student count and never exceed room capacity."""
    # Move allocation_id=4 (exam_entry_id=5, CS-332, 40 seats) into room_id=3 (Rm 105, capacity=30).
    alloc_4 = _get_exam_allocation(exam_dataset, 4)
    alloc_4.room_id = 3

    violations = validate_exam_schedule(exam_dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "E03"
    assert v.conflict_type == "Capacity"
    assert v.severity == "Hard"
    assert v.affected_entities["exam_entry_id"] == 5
    assert v.affected_entities["room_id"] == 3
    assert v.affected_entities["seats_allocated"] == 40
    assert v.affected_entities["room_capacity"] == 30


def test_e04_exam_room_clash_in_session(exam_dataset: TimetableDataset) -> None:
    """E04: A room is used by at most one exam in a session."""
    # In exam_slot_id=3, exam_entry_id=2 uses room_id=6 (Hall A, capacity=60).
    # Assign allocation_id=4 (exam_entry_id=5, also in exam_slot_id=3, 40 seats) to room_id=6 as well.
    alloc_4 = _get_exam_allocation(exam_dataset, 4)
    alloc_4.room_id = 6

    violations = validate_exam_schedule(exam_dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "E04"
    assert v.conflict_type == "Room"
    assert v.severity == "Hard"
    assert v.affected_entities["room_id"] == 6
    assert v.affected_entities["exam_slot_id"] == 3
    assert set(v.affected_entities["exam_entry_ids"]) == {2, 5}


def test_e05_single_session_per_course_missing(exam_dataset: TimetableDataset) -> None:
    """E05: Every course with an exam is assigned to exactly one session."""
    # Remove exam_entry_id=5 (course_id=5, CS-332) and its room allocation (allocation_id=4).
    exam_dataset.exam_entries = [
        e for e in exam_dataset.exam_entries if e.exam_entry_id != 5
    ]
    exam_dataset.exam_room_allocations = [
        a for a in exam_dataset.exam_room_allocations if a.exam_entry_id != 5
    ]

    violations = validate_exam_schedule(exam_dataset)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_code == "E05"
    assert v.conflict_type == "SessionCount"
    assert v.severity == "Hard"
    assert v.affected_entities["course_id"] == 5
    assert v.affected_entities["expected_sessions"] == 1
    assert v.affected_entities["actual_sessions"] == 0


def test_mandatory_exam_constraints_cannot_be_disabled(exam_dataset: TimetableDataset) -> None:
    """FR-5.2: Mandatory exam rules (E01, E04, E05) cannot be disabled."""
    for rule in exam_dataset.constraint_rules:
        if rule.rule_code == "E04":
            rule.is_enabled = False

    alloc_4 = _get_exam_allocation(exam_dataset, 4)
    alloc_4.room_id = 6

    validator = ExamValidator()
    violations = validator.validate(exam_dataset)
    assert len(violations) == 1
    assert violations[0].rule_code == "E04"

