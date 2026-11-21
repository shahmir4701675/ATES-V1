"""Domain data models for the ATES standalone scheduling and validation engine.

Conforms strictly to `docs/SRS.pdf` (Section 5.1, Appendix A) and `docs/data-contract.md`.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SLOT_MIN: int = 60
MAX_EXAMS_PER_DAY_DEFAULT: int = 2
MAX_SESSIONS_PER_DAY_DEFAULT: int = 5
MAX_CONSEC_HOURS_DEFAULT: int = 3
SOFT_WEIGHT_MIN: int = 0
SOFT_WEIGHT_MAX: int = 10
MANDATORY_TIMETABLE_RULES: frozenset[str] = frozenset({"H01", "H02", "H03", "H08"})
MANDATORY_EXAM_RULES: frozenset[str] = frozenset({"E01", "E04", "E05"})

DEFAULT_SOFT_TIMETABLE_WEIGHTS: dict[str, int] = {
    "S01": 8,
    "S02": 7,
    "S03": 6,
    "S04": 6,
    "S05": 5,
    "S06": 4,
}

DEFAULT_SOFT_EXAM_WEIGHTS: dict[str, int] = {
    "ES01": 8,
    "ES02": 5,
    "ES03": 4,
}


def format_score_summary(objective_score: float | None, max_score: float | None) -> str:
    """Format the objective score and percentage of maximum (e.g. 'score 128 (87% of maximum)')."""
    if objective_score is None:
        return "score 0 (0% of maximum)"
    score_int = int(round(objective_score))
    if max_score is None or max_score <= 0:
        pct = 100 if score_int >= 0 else 0
    else:
        pct = int(round(100.0 * float(objective_score) / float(max_score)))
        pct = max(0, min(100, pct))
    return f"score {score_int} ({pct}% of maximum)"


def _parse_time_to_minutes(time_str: str) -> int:
    """Convert a 24-hour time string ('HH:MM' or 'HH:MM:SS') to minutes since midnight."""
    parts = time_str.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time format: {time_str!r}. Expected HH:MM or HH:MM:SS.")
    hours = int(parts[0])
    minutes = int(parts[1])
    return hours * 60 + minutes


@dataclass
class Department:
    """Academic department (SRS 5.1.3.1 `departments`)."""

    department_id: int
    code: str
    name: str


@dataclass
class AcademicTerm:
    """Semester for which schedules are produced (SRS 5.1.3.2 `academic_terms`)."""

    term_id: int
    name: str
    start_date: str
    end_date: str
    status: str = "Active"


@dataclass
class TimeSlot:
    """Weekly slot grid period of a term (SRS 5.1.3.3 `time_slots`)."""

    slot_id: int
    term_id: int
    day_of_week: int
    slot_index: int
    start_time: str
    end_time: str
    is_blocked: bool = False
    block_reason: str | None = None

    @property
    def duration_minutes(self) -> int:
        """Duration of the slot in minutes."""
        diff = _parse_time_to_minutes(self.end_time) - _parse_time_to_minutes(self.start_time)
        return diff if diff > 0 else DEFAULT_SLOT_MIN

    @property
    def duration_hours(self) -> float:
        """Duration of the slot in hours."""
        return self.duration_minutes / 60.0


@dataclass
class Batch:
    """Student cohort/section (SRS 5.1.3.4 `batches`)."""

    batch_id: int
    department_id: int
    program_code: str
    batch_year: int
    section: str
    strength: int
    is_active: bool = True

    @property
    def label(self) -> str:
        """Human-readable batch label (e.g. 'BSCS-24 A')."""
        short_year = self.batch_year % 100
        return f"{self.program_code}-{short_year:02d} {self.section}"


@dataclass
class Course:
    """Course catalogue entry (SRS 5.1.3.5 `courses`)."""

    course_id: int
    course_code: str
    title: str
    department_id: int
    credit_hours: int
    lecture_hours: int = 0
    lab_hours: int = 0
    is_active: bool = True

    def required_lecture_sessions(self, slot_length_min: int = DEFAULT_SLOT_MIN) -> int:
        """Derive weekly lecture sessions required per FR-2.9 / H08."""
        if self.lecture_hours <= 0:
            return 0
        return math.ceil((self.lecture_hours * 60) / slot_length_min)

    def required_lab_slots(self, slot_length_min: int = DEFAULT_SLOT_MIN) -> int:
        """Derive weekly consecutive lab slots (1 lab block of k slots) per FR-2.9 / H08 / H09."""
        if self.lab_hours <= 0:
            return 0
        return math.ceil((self.lab_hours * 60) / slot_length_min)


@dataclass
class Instructor:
    """Teaching staff member (SRS 5.1.3.6 `instructors`)."""

    instructor_id: int
    department_id: int
    full_name: str
    email: str
    max_daily_hours: int = 4
    max_weekly_hours: int = 18
    is_active: bool = True


@dataclass
class InstructorAvailability:
    """Weekly slot availability record for an instructor (SRS 5.1.3.7 `instructor_availability`)."""

    availability_id: int
    instructor_id: int
    slot_id: int
    is_available: bool = True


@dataclass
class Room:
    """Lecture room, laboratory, or exam hall (SRS 5.1.3.8 `rooms`)."""

    room_id: int
    room_code: str
    building: str
    capacity: int
    room_type: str
    is_active: bool = True


@dataclass
class CourseOffering:
    """A course taught to one batch by one instructor in one term (SRS 5.1.3.10 `course_offerings`)."""

    offering_id: int
    term_id: int
    course_id: int
    batch_id: int
    instructor_id: int
    enrolled_count: int


@dataclass
class SchedulingConfig:
    """Named configuration profile for a term and schedule type (SRS 5.1.3.12 `scheduling_configs`)."""

    config_id: int
    term_id: int
    schedule_type: str
    name: str
    solver_time_limit_s: int = 120
    random_seed: int = 1
    created_by: int = 1
    created_at: str = "2026-10-20T09:00:00Z"


@dataclass
class ConstraintRule:
    """Constraint toggle, weight, and parameter belonging to a config (SRS 5.1.3.13 `constraint_rules`)."""

    rule_id: int
    config_id: int
    rule_code: str
    rule_type: str
    is_enabled: bool = True
    weight: int = 0
    param_value: int | None = None


@dataclass
class Schedule:
    """Header record for a generated schedule version (SRS 5.1.3.14 `schedules`)."""

    schedule_id: int
    term_id: int
    config_id: int
    schedule_type: str = "Timetable"
    version_no: int = 1
    status: str = "Generated"
    solver_status: str | None = "optimal"
    objective_score: float | None = None
    run_seconds: float | None = None
    generated_by: int = 1
    generated_at: str = "2026-10-20T09:15:00Z"
    approved_by: int | None = None
    published_at: str | None = None


@dataclass
class TimetableEntry:
    """One scheduled slot of a class session (SRS 5.1.3.15 `timetable_entries`)."""

    entry_id: int
    schedule_id: int
    offering_id: int
    instructor_id: int
    batch_id: int
    room_id: int
    slot_id: int
    session_type: str
    is_locked: bool = False
    is_manual_override: bool = False


@dataclass
class Enrollment:
    """Optional individual student-to-offering link (SRS 5.1.3.11 `enrollments`, A-4)."""

    enrollment_id: int
    offering_id: int
    student_id: int


@dataclass
class ExamSlot:
    """Exam session date and time window (SRS 5.1.3.16 `exam_slots`, FR-5.7)."""

    exam_slot_id: int
    term_id: int
    exam_date: str
    start_time: str
    end_time: str
    label: str | None = None
    session_label: str | None = None

    def __post_init__(self) -> None:
        if self.label is None and self.session_label is not None:
            self.label = self.session_label
        elif self.session_label is None and self.label is not None:
            self.session_label = self.label


@dataclass
class ExamRoomAllocation:
    """Room and seat count allocated to an exam entry (SRS 5.1.3.18 `exam_room_allocations`, FR-7.4)."""

    allocation_id: int
    exam_entry_id: int
    room_id: int
    seats_allocated: int


@dataclass
class ExamEntry:
    """Assignment of a course exam to an exam session (SRS 5.1.3.17 `exam_entries`, FR-7.2)."""

    exam_entry_id: int
    schedule_id: int
    course_id: int
    exam_slot_id: int
    student_count: int
    is_locked: bool = False
    is_manual_override: bool = False
    room_allocations: list[ExamRoomAllocation] | tuple[ExamRoomAllocation, ...] = field(
        default_factory=list
    )



@dataclass
class Violation:
    """Represents a constraint violation detected by the independent validator (FR-8.1, SRS 5.1.3.19)."""

    rule_code: str
    conflict_type: str
    severity: str
    description: str
    entity_ref: str
    affected_entities: dict[str, Any] = field(default_factory=dict)
    schedule_id: int | None = None

    def to_conflict_log_dict(self) -> dict[str, Any]:
        """Serialize to the canonical `conflict_log` record structure (`docs/data-contract.md` 9.5)."""
        return {
            "schedule_id": self.schedule_id,
            "rule_code": self.rule_code,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "description": self.description,
            "entity_ref": self.entity_ref,
            "affected_entities": self.affected_entities,
            "is_resolved": False,
        }


@dataclass
class SoftConstraintBreakdown:
    """Per-constraint soft evaluation breakdown (FR-5.4, FR-6.4, FR-7.6, SRS 4.3.5)."""

    rule_code: str
    description: str
    is_enabled: bool = True
    weight: int = 0
    param_value: int | None = None
    satisfied_count: int = 0
    violated_count: int = 0
    total_count: int = 0
    weighted_score: float = 0.0
    max_weighted_score: float = 0.0
    weighted_penalty: float = 0.0

    @property
    def satisfied(self) -> int:
        """Alias for `satisfied_count`."""
        return self.satisfied_count

    @property
    def violated(self) -> int:
        """Alias for `violated_count`."""
        return self.violated_count

    @property
    def weighted_contribution(self) -> float:
        """Alias for `weighted_score` (weighted contribution to objective)."""
        return self.weighted_score

    @property
    def max_possible_score(self) -> float:
        """Alias for `max_weighted_score`."""
        return self.max_weighted_score

    @property
    def max_score(self) -> float:
        """Alias for `max_weighted_score`."""
        return self.max_weighted_score

    @property
    def satisfaction_ratio(self) -> float:
        """Return fraction of units satisfied in [0.0, 1.0]."""
        if self.total_count <= 0:
            return 1.0
        return float(self.satisfied_count) / float(self.total_count)

    @property
    def satisfaction_percentage(self) -> float:
        """Return percentage of units satisfied in [0.0, 100.0]."""
        return round(100.0 * self.satisfaction_ratio, 2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize breakdown to a dictionary supporting both canonical and alias keys."""
        return {
            "rule_code": self.rule_code,
            "description": self.description,
            "is_enabled": self.is_enabled,
            "weight": self.weight,
            "param_value": self.param_value,
            "satisfied_count": self.satisfied_count,
            "violated_count": self.violated_count,
            "total_count": self.total_count,
            "satisfied": self.satisfied_count,
            "violated": self.violated_count,
            "weighted_score": self.weighted_score,
            "weighted_contribution": self.weighted_score,
            "max_weighted_score": self.max_weighted_score,
            "max_possible_score": self.max_weighted_score,
            "weighted_penalty": self.weighted_penalty,
            "satisfaction_ratio": self.satisfaction_ratio,
            "satisfaction_percentage": self.satisfaction_percentage,
        }

    def __getitem__(self, key: str) -> Any:
        data = self.to_dict()
        if key in data:
            return data[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.to_dict()

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()


@dataclass
class TimetableDataset:
    """Complete in-memory dataset for validating or solving a term timetable or exam schedule."""

    departments: list[Department] = field(default_factory=list)
    academic_terms: list[AcademicTerm] = field(default_factory=list)
    time_slots: list[TimeSlot] = field(default_factory=list)
    batches: list[Batch] = field(default_factory=list)
    courses: list[Course] = field(default_factory=list)
    instructors: list[Instructor] = field(default_factory=list)
    instructor_availability: list[InstructorAvailability] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    course_offerings: list[CourseOffering] = field(default_factory=list)
    scheduling_configs: list[SchedulingConfig] = field(default_factory=list)
    constraint_rules: list[ConstraintRule] = field(default_factory=list)
    schedules: list[Schedule] = field(default_factory=list)
    timetable_entries: list[TimetableEntry] = field(default_factory=list)
    enrollments: list[Enrollment] = field(default_factory=list)
    exam_slots: list[ExamSlot] = field(default_factory=list)
    exam_entries: list[ExamEntry] = field(default_factory=list)
    exam_room_allocations: list[ExamRoomAllocation] = field(default_factory=list)

    @property
    def slots_by_id(self) -> dict[int, TimeSlot]:
        """Lookup map of `slot_id -> TimeSlot`."""
        return {s.slot_id: s for s in self.time_slots}

    @property
    def time_slots_by_id(self) -> dict[int, TimeSlot]:
        """Alias for `slots_by_id` (`slot_id -> TimeSlot`)."""
        return self.slots_by_id

    @property
    def exam_slots_by_id(self) -> dict[int, ExamSlot]:
        """Lookup map of `exam_slot_id -> ExamSlot`."""
        return {s.exam_slot_id: s for s in self.exam_slots}

    @property
    def exam_entries_by_id(self) -> dict[int, ExamEntry]:
        """Lookup map of `exam_entry_id -> ExamEntry`."""
        return {e.exam_entry_id: e for e in self.exam_entries}

    @property
    def batches_by_id(self) -> dict[int, Batch]:
        """Lookup map of `batch_id -> Batch`."""
        return {b.batch_id: b for b in self.batches}

    @property
    def courses_by_id(self) -> dict[int, Course]:
        """Lookup map of `course_id -> Course`."""
        return {c.course_id: c for c in self.courses}

    @property
    def instructors_by_id(self) -> dict[int, Instructor]:
        """Lookup map of `instructor_id -> Instructor`."""
        return {i.instructor_id: i for i in self.instructors}

    @property
    def rooms_by_id(self) -> dict[int, Room]:
        """Lookup map of `room_id -> Room`."""
        return {r.room_id: r for r in self.rooms}

    @property
    def offerings_by_id(self) -> dict[int, CourseOffering]:
        """Lookup map of `offering_id -> CourseOffering`."""
        return {o.offering_id: o for o in self.course_offerings}

    def resolve_exam_allocations(
        self,
        entries: list[ExamEntry] | None = None,
        allocations: list[ExamRoomAllocation] | None = None,
    ) -> list[ExamRoomAllocation]:
        """Return all `ExamRoomAllocation` records from explicit list, dataset, or nested `ExamEntry.room_allocations`."""
        if allocations is not None:
            return list(allocations)
        if self.exam_room_allocations:
            return list(self.exam_room_allocations)
        active_entries = self.exam_entries if entries is None else entries
        nested: list[ExamRoomAllocation] = []
        for entry in active_entries:
            if entry.room_allocations:
                nested.extend(entry.room_allocations)
        return nested

    def course_students(self, term_id: int | None = None) -> dict[int, set[str]]:
        """Derive enrolled student/cohort identifiers per course (FR-7.1, Assumption A-4).

        - Every explicit `Enrollment(offering_id, student_id)` adds `f"student:{student_id}"`.
        - Under Assumption A-4, when an offering has no explicit enrollment records (or when
          explicit enrollments represent only partial repeater/elective links with
          `len(enrollments_for_offering) < offering.enrolled_count`), the batch cohort
          `f"batch:{offering.batch_id}"` is also included.
        """
        courses_map = self.courses_by_id
        enrollments_by_offering: dict[int, list[Enrollment]] = {}
        for enr in self.enrollments:
            enrollments_by_offering.setdefault(enr.offering_id, []).append(enr)

        result: dict[int, set[str]] = {}
        for off in self.course_offerings:
            if term_id is not None and off.term_id != term_id:
                continue
            course = courses_map.get(off.course_id)
            if course is None or not course.is_active:
                continue
            student_set = result.setdefault(off.course_id, set())
            off_enrs = enrollments_by_offering.get(off.offering_id, [])
            for enr in off_enrs:
                student_set.add(f"student:{enr.student_id}")
            if not off_enrs or len(off_enrs) < off.enrolled_count:
                student_set.add(f"batch:{off.batch_id}")
        return result

    def course_batches(self, term_id: int | None = None) -> dict[int, set[int]]:
        """Return `course_id -> set of batch_ids` for active courses offered in the term."""
        courses_map = self.courses_by_id
        result: dict[int, set[int]] = {}
        for off in self.course_offerings:
            if term_id is not None and off.term_id != term_id:
                continue
            course = courses_map.get(off.course_id)
            if course is None or not course.is_active:
                continue
            result.setdefault(off.course_id, set()).add(off.batch_id)
        return result

    def course_student_counts(self, term_id: int | None = None) -> dict[int, int]:
        """Return total `student_count` sitting each course exam in the term (FR-7.4, E03)."""
        courses_map = self.courses_by_id
        counts: dict[int, int] = {}
        for off in self.course_offerings:
            if term_id is not None and off.term_id != term_id:
                continue
            course = courses_map.get(off.course_id)
            if course is None or not course.is_active:
                continue
            counts[off.course_id] = counts.get(off.course_id, 0) + off.enrolled_count
        return counts

    def term_slot_length_minutes(self, term_id: int | None = None) -> int:
        """Return the slot length in minutes for the given term (default 60 min per C-6)."""
        for slot in self.time_slots:
            if term_id is None or slot.term_id == term_id:
                return slot.duration_minutes
        return DEFAULT_SLOT_MIN

    def is_instructor_available(self, instructor_id: int, slot_id: int) -> bool:
        """Return True unless the slot is explicitly marked unavailable (FR-3.3)."""
        for rec in self.instructor_availability:
            if rec.instructor_id == instructor_id and rec.slot_id == slot_id:
                return rec.is_available
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert dataset to a JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimetableDataset:
        """Construct a `TimetableDataset` from a parsed JSON dictionary."""
        top_allocs = [
            ExamRoomAllocation(**a) for a in data.get("exam_room_allocations", [])
        ]
        allocs_by_entry: dict[int, list[ExamRoomAllocation]] = {}
        for alloc in top_allocs:
            allocs_by_entry.setdefault(alloc.exam_entry_id, []).append(alloc)

        parsed_exam_entries: list[ExamEntry] = []
        for raw_entry in data.get("exam_entries", []):
            entry_copy = dict(raw_entry)
            nested_raw = entry_copy.pop("room_allocations", None)
            if nested_raw is not None:
                nested_allocs = [
                    ExamRoomAllocation(**na) if isinstance(na, dict) else na
                    for na in nested_raw
                ]
                for na in nested_allocs:
                    if all(a.allocation_id != na.allocation_id for a in top_allocs):
                        top_allocs.append(na)
            else:
                nested_allocs = list(allocs_by_entry.get(entry_copy["exam_entry_id"], []))
            parsed_exam_entries.append(
                ExamEntry(**entry_copy, room_allocations=nested_allocs)
            )

        return cls(
            departments=[Department(**d) for d in data.get("departments", [])],
            academic_terms=[AcademicTerm(**t) for t in data.get("academic_terms", [])],
            time_slots=[TimeSlot(**s) for s in data.get("time_slots", [])],
            batches=[Batch(**b) for b in data.get("batches", [])],
            courses=[Course(**c) for c in data.get("courses", [])],
            instructors=[Instructor(**i) for i in data.get("instructors", [])],
            instructor_availability=[
                InstructorAvailability(**a) for a in data.get("instructor_availability", [])
            ],
            rooms=[Room(**r) for r in data.get("rooms", [])],
            course_offerings=[CourseOffering(**o) for o in data.get("course_offerings", [])],
            scheduling_configs=[
                SchedulingConfig(**cfg) for cfg in data.get("scheduling_configs", [])
            ],
            constraint_rules=[ConstraintRule(**cr) for cr in data.get("constraint_rules", [])],
            schedules=[Schedule(**sch) for sch in data.get("schedules", [])],
            timetable_entries=[
                TimetableEntry(**e) for e in data.get("timetable_entries", [])
            ],
            enrollments=[Enrollment(**enr) for enr in data.get("enrollments", [])],
            exam_slots=[ExamSlot(**es) for es in data.get("exam_slots", [])],
            exam_entries=parsed_exam_entries,
            exam_room_allocations=top_allocs,
        )


ExamDataset = TimetableDataset


def load_dataset_from_json(path: str | Path) -> TimetableDataset:
    """Load a `TimetableDataset` from a UTF-8 JSON seed file."""
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)
    return TimetableDataset.from_dict(raw_data)
