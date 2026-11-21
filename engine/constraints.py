"""Pluggable hard and soft constraint modules (H01–H10, S01–S06, E01–E05, ES01–ES03) for ATES.

Design follows SRS Section 4.3.5 (Maintainability and Design for Change) and Appendix A.5:
Each constraint is a separate class with a shared interface (`add_to_model`, `evaluate_score`,
`validate`, `describe`), allowing a new rule to be added without modifying other code.
Validation logic is written completely independently of any CP-SAT solver model (FR-6.7, FR-8.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from engine.models import (
    ExamEntry,
    MAX_CONSEC_HOURS_DEFAULT,
    MAX_EXAMS_PER_DAY_DEFAULT,
    MAX_SESSIONS_PER_DAY_DEFAULT,
    SoftConstraintBreakdown,
    TimetableDataset,
    TimetableEntry,
    Violation,
)


class BaseConstraint(ABC):
    """Abstract base class for all scheduling constraints (SRS 4.3.5)."""

    rule_code: str
    rule_type: str = "Hard"
    conflict_type: str
    mandatory: bool = False
    default_weight: int = 0
    default_param: int | None = None
    description_text: str

    def describe(self) -> str:
        """Return the human-readable rule description from SRS Appendix A.5."""
        return self.description_text

    @abstractmethod
    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        """Add this constraint to an OR-Tools CP-SAT model (SRS 4.3.5, FR-6.3, FR-6.4)."""

    @abstractmethod
    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        """Validate schedule entries against this constraint independently of the solver."""

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        """Evaluate constraint satisfaction and weighted contribution on a schedule (SRS 4.3.5)."""
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))
        violations = self.validate(dataset, entries=entries, param_value=param_value)
        violated = len(violations)
        satisfied = 1 if violated == 0 else 0
        total = max(1, violated)
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def evaluate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        **kwargs: Any,
    ) -> SoftConstraintBreakdown:
        """Alias for `evaluate_score`."""
        return self.evaluate_score(dataset, entries=entries, **kwargs)


def _resolve_entries(
    dataset: TimetableDataset, entries: list[TimetableEntry] | None
) -> list[TimetableEntry]:
    return dataset.timetable_entries if entries is None else entries


def _resolve_schedule_id(entries: list[TimetableEntry], dataset: TimetableDataset) -> int | None:
    if entries:
        return entries[0].schedule_id
    if dataset.schedules:
        return dataset.schedules[0].schedule_id
    return None


class H01InstructorClash(BaseConstraint):
    """H01: An instructor teaches at most one session in a slot (Hard, mandatory)."""

    rule_code = "H01"
    rule_type = "Hard"
    conflict_type = "Instructor"
    mandatory = True
    description_text = "An instructor teaches at most one session in a slot."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for _instructor_id, inst_sessions in sorted(context.sessions_by_instructor.items()):
            for slot in context.slots:
                slot_vars = [
                    context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for u in inst_sessions
                    for room in context.rooms
                    if (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                if len(slot_vars) > 1:
                    model.AddAtMostOne(slot_vars)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        instructors_by_id = dataset.instructors_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        grouped: dict[tuple[int, int], list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            grouped[(entry.instructor_id, entry.slot_id)].append(entry)

        violations: list[Violation] = []
        for (instructor_id, slot_id), slot_entries in sorted(grouped.items()):
            if len(slot_entries) > 1:
                inst = instructors_by_id.get(instructor_id)
                inst_name = inst.full_name if inst else f"Instructor #{instructor_id}"
                entry_ids = [e.entry_id for e in slot_entries]
                offering_ids = [e.offering_id for e in slot_entries]
                course_codes = [
                    courses_by_id[offerings_by_id[e.offering_id].course_id].course_code
                    for e in slot_entries
                    if e.offering_id in offerings_by_id
                    and offerings_by_id[e.offering_id].course_id in courses_by_id
                ]
                entity_ref = (
                    f"instructor_id={instructor_id} ({inst_name}), "
                    f"slot_id={slot_id}, entry_ids={entry_ids}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H01 Violation: Instructor {inst_name} (instructor_id={instructor_id}) "
                            f"is scheduled for {len(slot_entries)} sessions in slot_id={slot_id} "
                            f"(entries {entry_ids})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "instructor_id": instructor_id,
                            "instructor_name": inst_name,
                            "slot_id": slot_id,
                            "entry_ids": entry_ids,
                            "offering_ids": offering_ids,
                            "course_codes": course_codes,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H02RoomClash(BaseConstraint):
    """H02: A room hosts at most one session in a slot (Hard, mandatory)."""

    rule_code = "H02"
    rule_type = "Hard"
    conflict_type = "Room"
    mandatory = True
    description_text = "A room hosts at most one session in a slot."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for room in context.rooms:
            for slot in context.slots:
                room_slot_vars = [
                    context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for u in context.sessions
                    if (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                if len(room_slot_vars) > 1:
                    model.AddAtMostOne(room_slot_vars)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        rooms_by_id = dataset.rooms_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        grouped: dict[tuple[int, int], list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            grouped[(entry.room_id, entry.slot_id)].append(entry)

        violations: list[Violation] = []
        for (room_id, slot_id), slot_entries in sorted(grouped.items()):
            if len(slot_entries) > 1:
                room = rooms_by_id.get(room_id)
                room_code = room.room_code if room else f"Room #{room_id}"
                entry_ids = [e.entry_id for e in slot_entries]
                offering_ids = [e.offering_id for e in slot_entries]
                course_codes = [
                    courses_by_id[offerings_by_id[e.offering_id].course_id].course_code
                    for e in slot_entries
                    if e.offering_id in offerings_by_id
                    and offerings_by_id[e.offering_id].course_id in courses_by_id
                ]
                entity_ref = (
                    f"room_id={room_id} ({room_code}), "
                    f"slot_id={slot_id}, entry_ids={entry_ids}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H02 Violation: Room {room_code} (room_id={room_id}) "
                            f"hosts {len(slot_entries)} sessions in slot_id={slot_id} "
                            f"(entries {entry_ids})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "room_id": room_id,
                            "room_code": room_code,
                            "slot_id": slot_id,
                            "entry_ids": entry_ids,
                            "offering_ids": offering_ids,
                            "course_codes": course_codes,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H03BatchClash(BaseConstraint):
    """H03: A batch attends at most one session in a slot (Hard, mandatory)."""

    rule_code = "H03"
    rule_type = "Hard"
    conflict_type = "Batch"
    mandatory = True
    description_text = "A batch attends at most one session in a slot."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for _batch_id, batch_sessions in sorted(context.sessions_by_batch.items()):
            for slot in context.slots:
                slot_vars = [
                    context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for u in batch_sessions
                    for room in context.rooms
                    if (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                if len(slot_vars) > 1:
                    model.AddAtMostOne(slot_vars)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        batches_by_id = dataset.batches_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        grouped: dict[tuple[int, int], list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            grouped[(entry.batch_id, entry.slot_id)].append(entry)

        violations: list[Violation] = []
        for (batch_id, slot_id), slot_entries in sorted(grouped.items()):
            if len(slot_entries) > 1:
                batch = batches_by_id.get(batch_id)
                batch_label = batch.label if batch else f"Batch #{batch_id}"
                entry_ids = [e.entry_id for e in slot_entries]
                offering_ids = [e.offering_id for e in slot_entries]
                course_codes = [
                    courses_by_id[offerings_by_id[e.offering_id].course_id].course_code
                    for e in slot_entries
                    if e.offering_id in offerings_by_id
                    and offerings_by_id[e.offering_id].course_id in courses_by_id
                ]
                entity_ref = (
                    f"batch_id={batch_id} ({batch_label}), "
                    f"slot_id={slot_id}, entry_ids={entry_ids}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H03 Violation: Batch {batch_label} (batch_id={batch_id}) "
                            f"attends {len(slot_entries)} sessions in slot_id={slot_id} "
                            f"(entries {entry_ids})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "batch_id": batch_id,
                            "batch_label": batch_label,
                            "slot_id": slot_id,
                            "entry_ids": entry_ids,
                            "offering_ids": offering_ids,
                            "course_codes": course_codes,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H04RoomCapacity(BaseConstraint):
    """H04: Room capacity is at least the enrolled count of the offering (Hard)."""

    rule_code = "H04"
    rule_type = "Hard"
    conflict_type = "Capacity"
    mandatory = False
    description_text = "Room capacity is at least the enrolled count of the offering."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for u in context.sessions:
            for room in context.rooms:
                if room.capacity < u.enrolled_count:
                    for slot in context.slots:
                        key = (u.session_idx, slot.slot_id, room.room_id)
                        if key in context.x:
                            model.Add(context.x[key] == 0)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        rooms_by_id = dataset.rooms_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        violations: list[Violation] = []
        for entry in active_entries:
            room = rooms_by_id.get(entry.room_id)
            offering = offerings_by_id.get(entry.offering_id)
            if room is None or offering is None:
                continue
            if room.capacity < offering.enrolled_count:
                course = courses_by_id.get(offering.course_id)
                course_code = course.course_code if course else f"course_id={offering.course_id}"
                entity_ref = (
                    f"entry_id={entry.entry_id}, offering_id={offering.offering_id} ({course_code}), "
                    f"room_id={room.room_id} ({room.room_code})"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H04 Violation: Room {room.room_code} capacity ({room.capacity}) "
                            f"is less than enrolled_count ({offering.enrolled_count}) for "
                            f"offering_id={offering.offering_id} ({course_code}) in entry_id={entry.entry_id}."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "entry_id": entry.entry_id,
                            "offering_id": offering.offering_id,
                            "course_code": course_code,
                            "room_id": room.room_id,
                            "room_code": room.room_code,
                            "room_capacity": room.capacity,
                            "enrolled_count": offering.enrolled_count,
                            "slot_id": entry.slot_id,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H05RoomType(BaseConstraint):
    """H05: Lab sessions are held in Lab rooms and lectures in Lecture rooms (Hard)."""

    rule_code = "H05"
    rule_type = "Hard"
    conflict_type = "RoomType"
    mandatory = False
    description_text = "Lab sessions are held in Lab rooms and lectures in Lecture rooms."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for u in context.sessions:
            expected_type = "Lab" if u.session_type == "Lab" else "Lecture"
            for room in context.rooms:
                if room.room_type != expected_type:
                    for slot in context.slots:
                        key = (u.session_idx, slot.slot_id, room.room_id)
                        if key in context.x:
                            model.Add(context.x[key] == 0)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        rooms_by_id = dataset.rooms_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        violations: list[Violation] = []
        for entry in active_entries:
            room = rooms_by_id.get(entry.room_id)
            if room is None:
                continue
            expected_room_type = "Lab" if entry.session_type == "Lab" else "Lecture"
            if room.room_type != expected_room_type:
                offering = offerings_by_id.get(entry.offering_id)
                course = courses_by_id.get(offering.course_id) if offering else None
                course_code = course.course_code if course else f"offering_id={entry.offering_id}"
                entity_ref = (
                    f"entry_id={entry.entry_id}, offering_id={entry.offering_id} ({course_code}), "
                    f"room_id={room.room_id} ({room.room_code})"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H05 Violation: {entry.session_type} session (entry_id={entry.entry_id}, "
                            f"{course_code}) is assigned to {room.room_type} room "
                            f"{room.room_code} (room_id={room.room_id}); expected {expected_room_type} room."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "entry_id": entry.entry_id,
                            "offering_id": entry.offering_id,
                            "course_code": course_code,
                            "room_id": room.room_id,
                            "room_code": room.room_code,
                            "session_type": entry.session_type,
                            "room_type": room.room_type,
                            "slot_id": entry.slot_id,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H06InstructorAvailability(BaseConstraint):
    """H06: No session in a slot in which the instructor is unavailable (Hard)."""

    rule_code = "H06"
    rule_type = "Hard"
    conflict_type = "Availability"
    mandatory = False
    description_text = "No session in a slot in which the instructor is unavailable."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for u in context.sessions:
            for slot in context.slots:
                if not context.dataset.is_instructor_available(u.instructor_id, slot.slot_id):
                    for room in context.rooms:
                        key = (u.session_idx, slot.slot_id, room.room_id)
                        if key in context.x:
                            model.Add(context.x[key] == 0)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        instructors_by_id = dataset.instructors_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        violations: list[Violation] = []
        for entry in active_entries:
            if not dataset.is_instructor_available(entry.instructor_id, entry.slot_id):
                inst = instructors_by_id.get(entry.instructor_id)
                inst_name = inst.full_name if inst else f"Instructor #{entry.instructor_id}"
                offering = offerings_by_id.get(entry.offering_id)
                course = courses_by_id.get(offering.course_id) if offering else None
                course_code = course.course_code if course else f"offering_id={entry.offering_id}"
                entity_ref = (
                    f"entry_id={entry.entry_id}, instructor_id={entry.instructor_id} ({inst_name}), "
                    f"slot_id={entry.slot_id}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H06 Violation: Instructor {inst_name} (instructor_id={entry.instructor_id}) "
                            f"is unavailable in slot_id={entry.slot_id} (entry_id={entry.entry_id}, {course_code})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "entry_id": entry.entry_id,
                            "offering_id": entry.offering_id,
                            "course_code": course_code,
                            "instructor_id": entry.instructor_id,
                            "instructor_name": inst_name,
                            "slot_id": entry.slot_id,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H07BlockedSlot(BaseConstraint):
    """H07: No session in a blocked slot (break or prayer time) (Hard)."""

    rule_code = "H07"
    rule_type = "Hard"
    conflict_type = "BlockedSlot"
    mandatory = False
    description_text = "No session in a blocked slot (break or prayer time)."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for slot in context.slots:
            if slot.is_blocked:
                for u in context.sessions:
                    for room in context.rooms:
                        key = (u.session_idx, slot.slot_id, room.room_id)
                        if key in context.x:
                            model.Add(context.x[key] == 0)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        slots_by_id = dataset.slots_by_id
        offerings_by_id = dataset.offerings_by_id
        courses_by_id = dataset.courses_by_id

        violations: list[Violation] = []
        for entry in active_entries:
            slot = slots_by_id.get(entry.slot_id)
            if slot is not None and slot.is_blocked:
                offering = offerings_by_id.get(entry.offering_id)
                course = courses_by_id.get(offering.course_id) if offering else None
                course_code = course.course_code if course else f"offering_id={entry.offering_id}"
                reason = slot.block_reason or "Blocked slot"
                entity_ref = (
                    f"entry_id={entry.entry_id}, offering_id={entry.offering_id} ({course_code}), "
                    f"slot_id={slot.slot_id} ({reason})"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H07 Violation: Session entry_id={entry.entry_id} ({course_code}) "
                            f"is scheduled in blocked slot_id={slot.slot_id} ({reason})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "entry_id": entry.entry_id,
                            "offering_id": entry.offering_id,
                            "course_code": course_code,
                            "slot_id": slot.slot_id,
                            "block_reason": slot.block_reason,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H08SessionCount(BaseConstraint):
    """H08: Every offering receives exactly the number of lecture sessions and lab blocks required per week (Hard, mandatory)."""

    rule_code = "H08"
    rule_type = "Hard"
    conflict_type = "SessionCount"
    mandatory = True
    description_text = (
        "Every offering receives exactly the number of lecture sessions and lab blocks required per week."
    )

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for u in context.sessions:
            session_vars = [
                context.x[(u.session_idx, slot.slot_id, room.room_id)]
                for slot in context.slots
                for room in context.rooms
                if (u.session_idx, slot.slot_id, room.room_id) in context.x
            ]
            if session_vars:
                model.AddExactlyOne(session_vars)
            else:
                model.AddBoolOr([])

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        courses_by_id = dataset.courses_by_id

        entries_by_offering: dict[int, list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            entries_by_offering[entry.offering_id].append(entry)

        violations: list[Violation] = []
        for offering in dataset.course_offerings:
            course = courses_by_id.get(offering.course_id)
            if course is None or not course.is_active:
                continue

            slot_len = dataset.term_slot_length_minutes(offering.term_id)
            expected_lecture = course.required_lecture_sessions(slot_len)
            expected_lab = course.required_lab_slots(slot_len)

            off_entries = entries_by_offering.get(offering.offering_id, [])
            actual_lecture = sum(1 for e in off_entries if e.session_type == "Lecture")
            actual_lab = sum(1 for e in off_entries if e.session_type == "Lab")

            if actual_lecture != expected_lecture or actual_lab != expected_lab:
                entry_ids = [e.entry_id for e in off_entries]
                entity_ref = (
                    f"offering_id={offering.offering_id} ({course.course_code}), "
                    f"lecture={actual_lecture}/{expected_lecture}, lab={actual_lab}/{expected_lab}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H08 Violation: Offering offering_id={offering.offering_id} "
                            f"({course.course_code}) requires {expected_lecture} Lecture slot(s) and "
                            f"{expected_lab} Lab slot(s) per week, but has {actual_lecture} Lecture "
                            f"and {actual_lab} Lab slot(s)."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "offering_id": offering.offering_id,
                            "course_id": course.course_id,
                            "course_code": course.course_code,
                            "batch_id": offering.batch_id,
                            "instructor_id": offering.instructor_id,
                            "expected_lecture_slots": expected_lecture,
                            "actual_lecture_slots": actual_lecture,
                            "expected_lab_slots": expected_lab,
                            "actual_lab_slots": actual_lab,
                            "entry_ids": entry_ids,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H09LabBlockContiguity(BaseConstraint):
    """H09: A lab block occupies consecutive slots of one day in one room (Hard)."""

    rule_code = "H09"
    rule_type = "Hard"
    conflict_type = "LabBlock"
    mandatory = False
    description_text = "A lab block occupies consecutive slots of one day in one room."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        slot_by_day_idx = context.slot_by_day_and_index
        for _offering_id, off_sessions in sorted(context.sessions_by_offering.items()):
            lab_sessions = sorted(
                [u for u in off_sessions if u.session_type == "Lab"],
                key=lambda s: s.occurrence_index,
            )
            k = len(lab_sessions)
            if k <= 1:
                continue

            valid_chains: list[tuple[Any, ...]] = []
            for slot in context.slots:
                chain = []
                for offset in range(k):
                    candidate = slot_by_day_idx.get((slot.day_of_week, slot.slot_index + offset))
                    if candidate is None:
                        break
                    chain.append(candidate)
                if len(chain) == k:
                    valid_chains.append(tuple(chain))

            for offset in range(k):
                allowed_slot_ids = {chain[offset].slot_id for chain in valid_chains}
                u_offset = lab_sessions[offset]
                for slot in context.slots:
                    if slot.slot_id not in allowed_slot_ids:
                        for room in context.rooms:
                            key = (u_offset.session_idx, slot.slot_id, room.room_id)
                            if key in context.x:
                                model.Add(context.x[key] == 0)

            for chain in valid_chains:
                for room in context.rooms:
                    first_key = (lab_sessions[0].session_idx, chain[0].slot_id, room.room_id)
                    if first_key not in context.x:
                        continue
                    first_var = context.x[first_key]
                    for offset in range(1, k):
                        offset_key = (
                            lab_sessions[offset].session_idx,
                            chain[offset].slot_id,
                            room.room_id,
                        )
                        if offset_key in context.x:
                            model.Add(context.x[offset_key] == first_var)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        slots_by_id = dataset.slots_by_id
        courses_by_id = dataset.courses_by_id
        offerings_by_id = dataset.offerings_by_id

        lab_entries_by_offering: dict[int, list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            if entry.session_type == "Lab":
                lab_entries_by_offering[entry.offering_id].append(entry)

        violations: list[Violation] = []
        for offering_id, lab_entries in sorted(lab_entries_by_offering.items()):
            if not lab_entries:
                continue

            offering = offerings_by_id.get(offering_id)
            course = courses_by_id.get(offering.course_id) if offering else None
            course_code = course.course_code if course else f"offering_id={offering_id}"

            room_ids = sorted({e.room_id for e in lab_entries})
            days = sorted(
                {slots_by_id[e.slot_id].day_of_week for e in lab_entries if e.slot_id in slots_by_id}
            )
            slot_indices = sorted(
                [slots_by_id[e.slot_id].slot_index for e in lab_entries if e.slot_id in slots_by_id]
            )

            same_room = len(room_ids) == 1
            same_day = len(days) == 1
            expected_consecutive = (
                list(range(slot_indices[0], slot_indices[0] + len(slot_indices)))
                if slot_indices
                else []
            )
            is_consecutive = slot_indices == expected_consecutive

            if not (same_room and same_day and is_consecutive):
                entry_ids = [e.entry_id for e in lab_entries]
                slot_ids = [e.slot_id for e in lab_entries]
                reasons: list[str] = []
                if not same_room:
                    reasons.append(f"split across multiple rooms {room_ids}")
                if not same_day:
                    reasons.append(f"split across multiple days {days}")
                if not is_consecutive:
                    reasons.append(f"non-consecutive slot_index values {slot_indices}")

                entity_ref = (
                    f"offering_id={offering_id} ({course_code}), "
                    f"entry_ids={entry_ids}, slot_ids={slot_ids}, room_ids={room_ids}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H09 Violation: Lab block for offering_id={offering_id} ({course_code}) "
                            f"must occupy consecutive slots on one day in one room, but is "
                            f"{'; '.join(reasons)} (entries {entry_ids})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "offering_id": offering_id,
                            "course_id": course.course_id if course else None,
                            "course_code": course_code,
                            "entry_ids": entry_ids,
                            "room_ids": room_ids,
                            "slot_ids": slot_ids,
                            "days_of_week": days,
                            "slot_indices": slot_indices,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class H10InstructorWorkload(BaseConstraint):
    """H10: An instructor does not exceed the daily and weekly teaching hours (Hard)."""

    rule_code = "H10"
    rule_type = "Hard"
    conflict_type = "Workload"
    mandatory = False
    description_text = "An instructor does not exceed the daily and weekly teaching hours."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for instructor in context.dataset.instructors:
            inst_sessions = context.sessions_by_instructor.get(instructor.instructor_id, [])
            if not inst_sessions:
                continue

            max_daily_min = int(round(instructor.max_daily_hours * 60))
            for _day, day_slots in sorted(context.slots_by_day.items()):
                daily_terms = [
                    slot.duration_minutes * context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for u in inst_sessions
                    for slot in day_slots
                    for room in context.rooms
                    if (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                if daily_terms:
                    model.Add(sum(daily_terms) <= max_daily_min)

            max_weekly_min = int(round(instructor.max_weekly_hours * 60))
            weekly_terms = [
                slot.duration_minutes * context.x[(u.session_idx, slot.slot_id, room.room_id)]
                for u in inst_sessions
                for slot in context.slots
                for room in context.rooms
                if (u.session_idx, slot.slot_id, room.room_id) in context.x
            ]
            if weekly_terms:
                model.Add(sum(weekly_terms) <= max_weekly_min)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_entries(dataset, entries)
        schedule_id = _resolve_schedule_id(active_entries, dataset)
        slots_by_id = dataset.slots_by_id

        entries_by_instructor: dict[int, list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            entries_by_instructor[entry.instructor_id].append(entry)

        violations: list[Violation] = []
        for instructor in dataset.instructors:
            inst_entries = entries_by_instructor.get(instructor.instructor_id, [])
            if not inst_entries:
                continue

            daily_hours: dict[int, float] = defaultdict(float)
            daily_entry_ids: dict[int, list[int]] = defaultdict(list)
            weekly_hours: float = 0.0
            all_entry_ids: list[int] = []

            for entry in inst_entries:
                slot = slots_by_id.get(entry.slot_id)
                hours = slot.duration_hours if slot else 1.0
                day = slot.day_of_week if slot else 0
                daily_hours[day] += hours
                daily_entry_ids[day].append(entry.entry_id)
                weekly_hours += hours
                all_entry_ids.append(entry.entry_id)

            for day, hours in sorted(daily_hours.items()):
                if hours > instructor.max_daily_hours:
                    entity_ref = (
                        f"instructor_id={instructor.instructor_id} ({instructor.full_name}), "
                        f"day_of_week={day}, hours={hours:g}/{instructor.max_daily_hours}"
                    )
                    violations.append(
                        Violation(
                            rule_code=self.rule_code,
                            conflict_type=self.conflict_type,
                            severity="Hard",
                            description=(
                                f"H10 Violation: Instructor {instructor.full_name} "
                                f"(instructor_id={instructor.instructor_id}) teaches {hours:g} hours "
                                f"on day_of_week={day}, exceeding max_daily_hours={instructor.max_daily_hours}."
                            ),
                            entity_ref=entity_ref,
                            affected_entities={
                                "instructor_id": instructor.instructor_id,
                                "instructor_name": instructor.full_name,
                                "scope": "daily",
                                "day_of_week": day,
                                "actual_hours": hours,
                                "max_allowed_hours": instructor.max_daily_hours,
                                "entry_ids": daily_entry_ids[day],
                            },
                            schedule_id=schedule_id,
                        )
                    )

            if weekly_hours > instructor.max_weekly_hours:
                entity_ref = (
                    f"instructor_id={instructor.instructor_id} ({instructor.full_name}), "
                    f"weekly_hours={weekly_hours:g}/{instructor.max_weekly_hours}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"H10 Violation: Instructor {instructor.full_name} "
                            f"(instructor_id={instructor.instructor_id}) teaches {weekly_hours:g} hours "
                            f"weekly, exceeding max_weekly_hours={instructor.max_weekly_hours}."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "instructor_id": instructor.instructor_id,
                            "instructor_name": instructor.full_name,
                            "scope": "weekly",
                            "day_of_week": None,
                            "actual_hours": weekly_hours,
                            "max_allowed_hours": instructor.max_weekly_hours,
                            "entry_ids": all_entry_ids,
                        },
                        schedule_id=schedule_id,
                    )
                )

        return violations


HARD_TIMETABLE_CONSTRAINTS: dict[str, BaseConstraint] = {
    "H01": H01InstructorClash(),
    "H02": H02RoomClash(),
    "H03": H03BatchClash(),
    "H04": H04RoomCapacity(),
    "H05": H05RoomType(),
    "H06": H06InstructorAvailability(),
    "H07": H07BlockedSlot(),
    "H08": H08SessionCount(),
    "H09": H09LabBlockContiguity(),
    "H10": H10InstructorWorkload(),
}


def _resolve_active_term_id(dataset: TimetableDataset, term_id: int | None = None) -> int:
    if term_id is not None:
        return term_id
    for term in dataset.academic_terms:
        if term.status == "Active":
            return term.term_id
    if dataset.academic_terms:
        return dataset.academic_terms[0].term_id
    if dataset.course_offerings:
        return dataset.course_offerings[0].term_id
    if dataset.time_slots:
        return dataset.time_slots[0].term_id
    return 1


class S01BatchIdleGaps(BaseConstraint):
    """S01: Minimise idle gaps between the sessions of a batch on a day (Soft, default weight=8)."""

    rule_code = "S01"
    rule_type = "Soft"
    conflict_type = "BatchIdleGap"
    mandatory = False
    default_weight = 8
    description_text = "Minimise idle gaps between the sessions of a batch on a day."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = self.default_weight if weight is None else int(weight)
        if w <= 0:
            return

        for batch_id, batch_sessions in sorted(context.sessions_by_batch.items()):
            if not batch_sessions:
                continue
            for day, day_slots in sorted(context.slots_by_day.items()):
                unblocked = sorted(
                    [s for s in day_slots if not s.is_blocked],
                    key=lambda s: (s.slot_index, s.slot_id),
                )
                if len(unblocked) < 3:
                    continue

                occ_exprs: list[Any] = []
                for slot in unblocked:
                    slot_terms = [
                        context.x[(u.session_idx, slot.slot_id, room.room_id)]
                        for u in batch_sessions
                        for room in context.rooms
                        if (u.session_idx, slot.slot_id, room.room_id) in context.x
                    ]
                    occ_exprs.append(sum(slot_terms) if slot_terms else 0)

                for i in range(1, len(unblocked) - 1):
                    slot_i = unblocked[i]
                    no_gap = model.NewBoolVar(f"s01_nogap_b{batch_id}_d{day}_s{slot_i.slot_id}")
                    for j in range(0, i):
                        for k in range(i + 1, len(unblocked)):
                            model.Add(
                                no_gap + occ_exprs[j] + occ_exprs[k] - occ_exprs[i] <= 2
                            )
                    context.soft_reward_terms.append(w * no_gap)
                    context.soft_max_score += w

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_entries(dataset, entries)
        resolved_term_id = _resolve_active_term_id(dataset, term_id)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))

        courses_by_id = dataset.courses_by_id
        active_batch_ids = sorted(
            {
                off.batch_id
                for off in dataset.course_offerings
                if off.term_id == resolved_term_id
                and off.course_id in courses_by_id
                and courses_by_id[off.course_id].is_active
            }
        )
        slots_by_day: dict[int, list[Any]] = defaultdict(list)
        for s in dataset.time_slots:
            if s.term_id == resolved_term_id:
                slots_by_day[s.day_of_week].append(s)

        occupied_batch_slots: set[tuple[int, int]] = {
            (e.batch_id, e.slot_id) for e in active_entries
        }

        satisfied = 0
        violated = 0
        for batch_id in active_batch_ids:
            for _day, day_slots in sorted(slots_by_day.items()):
                unblocked = sorted(
                    [s for s in day_slots if not s.is_blocked],
                    key=lambda s: (s.slot_index, s.slot_id),
                )
                if len(unblocked) < 3:
                    continue
                occ = [(batch_id, s.slot_id) in occupied_batch_slots for s in unblocked]
                for i in range(1, len(unblocked) - 1):
                    is_gap = (not occ[i]) and any(occ[:i]) and any(occ[i + 1 :])
                    if is_gap:
                        violated += 1
                    else:
                        satisfied += 1

        total = satisfied + violated
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class S02OfferingDaySpread(BaseConstraint):
    """S02: Spread the sessions of one offering over different days (Soft, default weight=7)."""

    rule_code = "S02"
    rule_type = "Soft"
    conflict_type = "OfferingDaySpread"
    mandatory = False
    default_weight = 7
    description_text = "Spread the sessions of one offering over different days."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = self.default_weight if weight is None else int(weight)
        if w <= 0:
            return

        num_days = len(context.slots_by_day)
        if num_days <= 1:
            return

        for offering_id, off_sessions in sorted(context.sessions_by_offering.items()):
            meeting_sessions = [
                u
                for u in off_sessions
                if u.session_type == "Lecture"
                or (u.session_type == "Lab" and u.occurrence_index == 0)
            ]
            num_meetings = len(meeting_sessions)
            if num_meetings <= 1:
                continue

            target_days = min(num_meetings, num_days)
            day_used_vars: list[Any] = []
            for day, day_slots in sorted(context.slots_by_day.items()):
                day_terms = [
                    context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for u in meeting_sessions
                    for slot in day_slots
                    for room in context.rooms
                    if (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                if day_terms:
                    used_d = model.NewBoolVar(f"s02_used_o{offering_id}_d{day}")
                    model.Add(used_d <= sum(day_terms))
                    day_used_vars.append(used_d)

            if day_used_vars:
                if num_meetings <= num_days:
                    for dv in day_used_vars:
                        context.soft_reward_terms.append(w * dv)
                    context.soft_max_score += w * target_days
                else:
                    spread_var = model.NewIntVar(0, target_days, f"s02_spread_o{offering_id}")
                    model.Add(spread_var <= sum(day_used_vars))
                    context.soft_reward_terms.append(w * spread_var)
                    context.soft_max_score += w * target_days

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_entries(dataset, entries)
        resolved_term_id = _resolve_active_term_id(dataset, term_id)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))

        slots_by_id = dataset.slots_by_id
        courses_by_id = dataset.courses_by_id
        slot_len = dataset.term_slot_length_minutes(resolved_term_id)
        days_in_term = {
            s.day_of_week for s in dataset.time_slots if s.term_id == resolved_term_id
        }
        num_days = len(days_in_term)

        entries_by_off: dict[int, list[TimetableEntry]] = defaultdict(list)
        for entry in active_entries:
            entries_by_off[entry.offering_id].append(entry)

        satisfied = 0
        violated = 0
        for offering in sorted(dataset.course_offerings, key=lambda o: o.offering_id):
            if offering.term_id != resolved_term_id:
                continue
            course = courses_by_id.get(offering.course_id)
            if course is None or not course.is_active:
                continue

            num_lec = course.required_lecture_sessions(slot_len)
            num_lab = course.required_lab_slots(slot_len)
            num_meetings = num_lec + (1 if num_lab > 0 else 0)
            if num_meetings <= 1 or num_days <= 1:
                continue

            target_days = min(num_meetings, num_days)
            off_entries = entries_by_off.get(offering.offering_id, [])

            meeting_days: set[int] = set()
            for e in off_entries:
                if e.session_type == "Lecture" and e.slot_id in slots_by_id:
                    meeting_days.add(slots_by_id[e.slot_id].day_of_week)

            lab_days = sorted(
                {
                    slots_by_id[e.slot_id].day_of_week
                    for e in off_entries
                    if e.session_type == "Lab" and e.slot_id in slots_by_id
                }
            )
            if lab_days:
                meeting_days.add(lab_days[0])

            distinct_days = min(target_days, len(meeting_days))
            satisfied += distinct_days
            violated += target_days - distinct_days

        total = satisfied + violated
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class S03BatchDailySessionLimit(BaseConstraint):
    """S03: Keep the sessions of a batch per day at or below a parameter (default 5) (Soft, default weight=6)."""

    rule_code = "S03"
    rule_type = "Soft"
    conflict_type = "BatchDailyLoad"
    mandatory = False
    default_weight = 6
    default_param = MAX_SESSIONS_PER_DAY_DEFAULT
    description_text = "Keep the sessions of a batch per day at or below a parameter (default 5)."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = self.default_weight if weight is None else int(weight)
        if w <= 0:
            return

        limit = self.default_param if param_value is None else int(param_value)
        for batch_id, batch_sessions in sorted(context.sessions_by_batch.items()):
            if not batch_sessions:
                continue
            for day, day_slots in sorted(context.slots_by_day.items()):
                day_terms = [
                    context.x[(u.session_idx, slot.slot_id, room.room_id)]
                    for u in batch_sessions
                    for slot in day_slots
                    for room in context.rooms
                    if (u.session_idx, slot.slot_id, room.room_id) in context.x
                ]
                ok_bd = model.NewBoolVar(f"s03_ok_b{batch_id}_d{day}")
                excess_bound = max(1, len(day_slots) - limit)
                if day_terms:
                    model.Add(sum(day_terms) - limit <= excess_bound * (1 - ok_bd))
                context.soft_reward_terms.append(w * ok_bd)
                context.soft_max_score += w

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_entries(dataset, entries)
        resolved_term_id = _resolve_active_term_id(dataset, term_id)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))
        limit = self.default_param if param_value is None else int(param_value)

        courses_by_id = dataset.courses_by_id
        slots_by_id = dataset.slots_by_id
        active_batch_ids = sorted(
            {
                off.batch_id
                for off in dataset.course_offerings
                if off.term_id == resolved_term_id
                and off.course_id in courses_by_id
                and courses_by_id[off.course_id].is_active
            }
        )
        days = sorted(
            {s.day_of_week for s in dataset.time_slots if s.term_id == resolved_term_id}
        )

        counts_by_batch_day: dict[tuple[int, int], int] = defaultdict(int)
        for e in active_entries:
            slot = slots_by_id.get(e.slot_id)
            if slot is not None and slot.term_id == resolved_term_id:
                counts_by_batch_day[(e.batch_id, slot.day_of_week)] += 1

        satisfied = 0
        violated = 0
        for batch_id in active_batch_ids:
            for day in days:
                if counts_by_batch_day[(batch_id, day)] <= limit:
                    satisfied += 1
                else:
                    violated += 1

        total = satisfied + violated
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=limit,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class S04InstructorConsecutiveSlots(BaseConstraint):
    """S04: Keep consecutive teaching slots of an instructor at or below a parameter (default 3) (Soft, default weight=6)."""

    rule_code = "S04"
    rule_type = "Soft"
    conflict_type = "InstructorConsecutive"
    mandatory = False
    default_weight = 6
    default_param = MAX_CONSEC_HOURS_DEFAULT
    description_text = (
        "Keep consecutive teaching slots of an instructor at or below a parameter (default 3)."
    )

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = self.default_weight if weight is None else int(weight)
        if w <= 0:
            return

        max_consec = self.default_param if param_value is None else int(param_value)
        if max_consec < 1:
            max_consec = 1

        slot_by_day_idx = context.slot_by_day_and_index
        for instructor_id, inst_sessions in sorted(context.sessions_by_instructor.items()):
            if not inst_sessions:
                continue
            for day, day_slots in sorted(context.slots_by_day.items()):
                sorted_day_slots = sorted(day_slots, key=lambda s: (s.slot_index, s.slot_id))
                for start_slot in sorted_day_slots:
                    chain = []
                    for offset in range(max_consec + 1):
                        cand = slot_by_day_idx.get((day, start_slot.slot_index + offset))
                        if cand is None or cand.is_blocked:
                            break
                        chain.append(cand)
                    if len(chain) != max_consec + 1:
                        continue

                    window_terms = [
                        context.x[(u.session_idx, s.slot_id, room.room_id)]
                        for s in chain
                        for u in inst_sessions
                        for room in context.rooms
                        if (u.session_idx, s.slot_id, room.room_id) in context.x
                    ]
                    ok_w = model.NewBoolVar(
                        f"s04_ok_i{instructor_id}_d{day}_s{start_slot.slot_index}"
                    )
                    if window_terms:
                        model.Add(sum(window_terms) <= max_consec + (1 - ok_w))
                    context.soft_reward_terms.append(w * ok_w)
                    context.soft_max_score += w

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_entries(dataset, entries)
        resolved_term_id = _resolve_active_term_id(dataset, term_id)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))
        max_consec = self.default_param if param_value is None else int(param_value)
        if max_consec < 1:
            max_consec = 1

        courses_by_id = dataset.courses_by_id
        active_instructor_ids = sorted(
            {
                off.instructor_id
                for off in dataset.course_offerings
                if off.term_id == resolved_term_id
                and off.course_id in courses_by_id
                and courses_by_id[off.course_id].is_active
            }
        )

        slots_by_day: dict[int, list[Any]] = defaultdict(list)
        slot_by_day_idx: dict[tuple[int, int], Any] = {}
        for s in dataset.time_slots:
            if s.term_id == resolved_term_id:
                slots_by_day[s.day_of_week].append(s)
                slot_by_day_idx[(s.day_of_week, s.slot_index)] = s

        inst_taught_slots: set[tuple[int, int]] = {
            (e.instructor_id, e.slot_id) for e in active_entries
        }

        satisfied = 0
        violated = 0
        for instructor_id in active_instructor_ids:
            for day, day_slots in sorted(slots_by_day.items()):
                sorted_day_slots = sorted(day_slots, key=lambda s: (s.slot_index, s.slot_id))
                for start_slot in sorted_day_slots:
                    chain = []
                    for offset in range(max_consec + 1):
                        cand = slot_by_day_idx.get((day, start_slot.slot_index + offset))
                        if cand is None or cand.is_blocked:
                            break
                        chain.append(cand)
                    if len(chain) != max_consec + 1:
                        continue

                    taught_count = sum(
                        1 for s in chain if (instructor_id, s.slot_id) in inst_taught_slots
                    )
                    if taught_count <= max_consec:
                        satisfied += 1
                    else:
                        violated += 1

        total = satisfied + violated
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=max_consec,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class S05ScheduleStability(BaseConstraint):
    """S05: Prefer the same slot and room as in a previous schedule version (Soft, default weight=5)."""

    rule_code = "S05"
    rule_type = "Soft"
    conflict_type = "ScheduleStability"
    mandatory = False
    default_weight = 5
    description_text = "Prefer the same slot and room as in a previous schedule version."

    @staticmethod
    def _extract_targets(
        previous_entries: list[TimetableEntry] | None,
        valid_offering_ids: set[int],
    ) -> list[tuple[int, str, int, int]]:
        if not previous_entries:
            return []
        targets = {
            (e.offering_id, e.session_type, e.slot_id, e.room_id)
            for e in previous_entries
            if e.offering_id in valid_offering_ids
        }
        return sorted(targets)

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = self.default_weight if weight is None else int(weight)
        if w <= 0:
            return

        previous_entries = getattr(context, "previous_entries", None)
        valid_offering_ids = set(context.sessions_by_offering.keys())
        targets = self._extract_targets(previous_entries, valid_offering_ids)
        if not targets:
            return

        for idx, (off_id, sess_type, slot_id, room_id) in enumerate(targets):
            match_vars = [
                context.x[(u.session_idx, slot_id, room_id)]
                for u in context.sessions_by_offering.get(off_id, [])
                if u.session_type == sess_type
                and (u.session_idx, slot_id, room_id) in context.x
            ]
            if match_vars:
                m_var = model.NewBoolVar(
                    f"s05_match_{idx}_o{off_id}_s{slot_id}_r{room_id}"
                )
                model.Add(m_var <= sum(match_vars))
                context.soft_reward_terms.append(w * m_var)
            context.soft_max_score += w

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_entries(dataset, entries)
        resolved_term_id = _resolve_active_term_id(dataset, term_id)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))

        courses_by_id = dataset.courses_by_id
        valid_offering_ids = {
            off.offering_id
            for off in dataset.course_offerings
            if off.term_id == resolved_term_id
            and off.course_id in courses_by_id
            and courses_by_id[off.course_id].is_active
        }
        targets = self._extract_targets(previous_entries, valid_offering_ids)
        if not targets:
            return SoftConstraintBreakdown(
                rule_code=self.rule_code,
                description=self.describe(),
                is_enabled=False,
                weight=eff_weight,
                param_value=param_value,
                satisfied_count=0,
                violated_count=0,
                total_count=0,
                weighted_score=0.0,
                max_weighted_score=0.0,
                weighted_penalty=0.0,
            )

        current_set = {
            (e.offering_id, e.session_type, e.slot_id, e.room_id) for e in active_entries
        }
        satisfied = sum(1 for t in targets if t in current_set)
        violated = len(targets) - satisfied
        total = len(targets)
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class S06SmallestFittingRoom(BaseConstraint):
    """S06: Prefer the smallest room that fits the offering (Soft, default weight=4)."""

    rule_code = "S06"
    rule_type = "Soft"
    conflict_type = "RoomFit"
    mandatory = False
    default_weight = 4
    description_text = "Prefer the smallest room that fits the offering."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = self.default_weight if weight is None else int(weight)
        if w <= 0:
            return

        for u in context.sessions:
            expected_type = "Lab" if u.session_type == "Lab" else "Lecture"
            fitting_rooms = [
                r
                for r in context.rooms
                if r.room_type == expected_type and r.capacity >= u.enrolled_count
            ]
            if not fitting_rooms:
                continue
            min_cap = min(r.capacity for r in fitting_rooms)
            smallest_room_ids = sorted(
                r.room_id for r in fitting_rooms if r.capacity == min_cap
            )
            small_vars = [
                context.x[(u.session_idx, slot.slot_id, r_id)]
                for slot in context.slots
                for r_id in smallest_room_ids
                if (u.session_idx, slot.slot_id, r_id) in context.x
            ]
            if small_vars:
                fit_var = model.NewBoolVar(f"s06_fit_s{u.session_idx}")
                model.Add(fit_var <= sum(small_vars))
                context.soft_reward_terms.append(w * fit_var)
            context.soft_max_score += w

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_entries(dataset, entries)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))

        offerings_by_id = dataset.offerings_by_id
        rooms_by_id = dataset.rooms_by_id
        active_rooms = [r for r in dataset.rooms if r.is_active]

        satisfied = 0
        violated = 0
        for entry in active_entries:
            offering = offerings_by_id.get(entry.offering_id)
            room = rooms_by_id.get(entry.room_id)
            if offering is None:
                continue
            expected_type = "Lab" if entry.session_type == "Lab" else "Lecture"
            fitting_rooms = [
                r
                for r in active_rooms
                if r.room_type == expected_type and r.capacity >= offering.enrolled_count
            ]
            if not fitting_rooms:
                continue
            min_cap = min(r.capacity for r in fitting_rooms)
            if (
                room is not None
                and room.room_type == expected_type
                and room.capacity == min_cap
            ):
                satisfied += 1
            else:
                violated += 1

        total = satisfied + violated
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


SOFT_TIMETABLE_CONSTRAINTS: dict[str, BaseConstraint] = {
    "S01": S01BatchIdleGaps(),
    "S02": S02OfferingDaySpread(),
    "S03": S03BatchDailySessionLimit(),
    "S04": S04InstructorConsecutiveSlots(),
    "S05": S05ScheduleStability(),
    "S06": S06SmallestFittingRoom(),
}


def _resolve_exam_entries(
    dataset: TimetableDataset, entries: list[ExamEntry] | None
) -> list[ExamEntry]:
    return dataset.exam_entries if entries is None else entries


def _resolve_exam_schedule_id(entries: list[ExamEntry], dataset: TimetableDataset) -> int | None:
    if entries:
        return entries[0].schedule_id
    for sch in dataset.schedules:
        if sch.schedule_type == "Exam":
            return sch.schedule_id
    if dataset.schedules:
        return dataset.schedules[0].schedule_id
    return None


class E01StudentExamClash(BaseConstraint):
    """E01: Two courses that share a student are not in the same exam session (Hard, mandatory)."""

    rule_code = "E01"
    rule_type = "Hard"
    conflict_type = "StudentExamClash"
    mandatory = True
    description_text = "Two courses that share a student are not in the same exam session."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for u, v in sorted(context.conflict_graph.edges()):
            for slot in context.exam_slots:
                key_u = (u, slot.exam_slot_id)
                key_v = (v, slot.exam_slot_id)
                if key_u in context.y and key_v in context.y:
                    model.Add(context.y[key_u] + context.y[key_v] <= 1)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_exam_entries(dataset, entries)
        schedule_id = _resolve_exam_schedule_id(active_entries, dataset)
        courses_by_id = dataset.courses_by_id
        course_students = dataset.course_students()

        by_slot: dict[int, list[ExamEntry]] = defaultdict(list)
        for entry in active_entries:
            by_slot[entry.exam_slot_id].append(entry)

        violations: list[Violation] = []
        for exam_slot_id, slot_entries in sorted(by_slot.items()):
            n = len(slot_entries)
            for i in range(n):
                for j in range(i + 1, n):
                    e1 = slot_entries[i]
                    e2 = slot_entries[j]
                    s1 = course_students.get(e1.course_id, set())
                    s2 = course_students.get(e2.course_id, set())
                    shared = sorted(s1 & s2)
                    if e1.course_id == e2.course_id or shared:
                        c1 = courses_by_id.get(e1.course_id)
                        c2 = courses_by_id.get(e2.course_id)
                        code1 = c1.course_code if c1 else f"course_id={e1.course_id}"
                        code2 = c2.course_code if c2 else f"course_id={e2.course_id}"
                        entity_ref = (
                            f"exam_slot_id={exam_slot_id}, "
                            f"course_ids=[{e1.course_id}, {e2.course_id}] ({code1}, {code2}), "
                            f"shared_students={shared}"
                        )
                        violations.append(
                            Violation(
                                rule_code=self.rule_code,
                                conflict_type=self.conflict_type,
                                severity="Hard",
                                description=(
                                    f"E01 Violation: Courses {code1} (course_id={e1.course_id}) "
                                    f"and {code2} (course_id={e2.course_id}) share enrolled students "
                                    f"{shared} and are both scheduled in exam_slot_id={exam_slot_id}."
                                ),
                                entity_ref=entity_ref,
                                affected_entities={
                                    "exam_slot_id": exam_slot_id,
                                    "course_ids": [e1.course_id, e2.course_id],
                                    "course_codes": [code1, code2],
                                    "exam_entry_ids": [e1.exam_entry_id, e2.exam_entry_id],
                                    "shared_students": shared,
                                },
                                schedule_id=schedule_id,
                            )
                        )
        return violations


class E02DailyExamLimit(BaseConstraint):
    """E02: No student has more exams per day than the configured maximum (Hard)."""

    rule_code = "E02"
    rule_type = "Hard"
    conflict_type = "DailyExamLimit"
    mandatory = False
    description_text = "No student has more exams per day than the configured maximum."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        max_per_day = param_value if param_value is not None else MAX_EXAMS_PER_DAY_DEFAULT
        for _student_ref, student_courses in sorted(context.courses_by_student.items()):
            for _exam_date, day_slots in sorted(context.slots_by_date.items()):
                terms = [
                    context.y[(cid, slot.exam_slot_id)]
                    for cid in student_courses
                    for slot in day_slots
                    if (cid, slot.exam_slot_id) in context.y
                ]
                if len(terms) > max_per_day:
                    model.Add(sum(terms) <= max_per_day)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_exam_entries(dataset, entries)
        schedule_id = _resolve_exam_schedule_id(active_entries, dataset)
        exam_slots_by_id = dataset.exam_slots_by_id
        courses_by_id = dataset.courses_by_id
        course_students = dataset.course_students()

        max_per_day = param_value
        if max_per_day is None:
            for rule in dataset.constraint_rules:
                if rule.rule_code == "E02" and rule.param_value is not None:
                    max_per_day = rule.param_value
                    break
        if max_per_day is None:
            max_per_day = MAX_EXAMS_PER_DAY_DEFAULT

        student_day_entries: dict[tuple[str, str], list[ExamEntry]] = defaultdict(list)
        for entry in active_entries:
            exam_slot = exam_slots_by_id.get(entry.exam_slot_id)
            if exam_slot is None:
                continue
            for student_ref in sorted(course_students.get(entry.course_id, set())):
                student_day_entries[(student_ref, exam_slot.exam_date)].append(entry)

        violations: list[Violation] = []
        for (student_ref, exam_date), day_entries in sorted(student_day_entries.items()):
            if len(day_entries) > max_per_day:
                course_ids = [e.course_id for e in day_entries]
                course_codes = [
                    courses_by_id[e.course_id].course_code
                    if e.course_id in courses_by_id
                    else f"course_id={e.course_id}"
                    for e in day_entries
                ]
                entry_ids = [e.exam_entry_id for e in day_entries]
                entity_ref = (
                    f"student={student_ref}, exam_date={exam_date}, "
                    f"exams={len(day_entries)}/{max_per_day}, courses={course_codes}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"E02 Violation: Student/cohort {student_ref} has {len(day_entries)} "
                            f"exams ({course_codes}) on {exam_date}, exceeding the daily maximum "
                            f"of {max_per_day}."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "student_ref": student_ref,
                            "exam_date": exam_date,
                            "exam_count": len(day_entries),
                            "max_allowed": max_per_day,
                            "course_ids": course_ids,
                            "course_codes": course_codes,
                            "exam_entry_ids": entry_ids,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class E03ExamSeatAllocation(BaseConstraint):
    """E03: Allocated seats equal the student count and never exceed room capacity (Hard)."""

    rule_code = "E03"
    rule_type = "Hard"
    conflict_type = "Capacity"
    mandatory = False
    description_text = "Allocated seats equal the student count and never exceed room capacity."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        total_cap = context.total_exam_room_capacity
        for cid in context.course_ids:
            needed = context.student_counts.get(cid, 0)
            if needed > total_cap:
                for slot in context.exam_slots:
                    key = (cid, slot.exam_slot_id)
                    if key in context.y:
                        model.Add(context.y[key] == 0)

        for slot in context.exam_slots:
            cap_terms = [
                context.student_counts.get(cid, 0) * context.y[(cid, slot.exam_slot_id)]
                for cid in context.course_ids
                if (cid, slot.exam_slot_id) in context.y
            ]
            if cap_terms:
                model.Add(sum(cap_terms) <= total_cap)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_exam_entries(dataset, entries)
        schedule_id = _resolve_exam_schedule_id(active_entries, dataset)
        rooms_by_id = dataset.rooms_by_id
        courses_by_id = dataset.courses_by_id
        expected_counts = dataset.course_student_counts()
        all_allocs = dataset.resolve_exam_allocations(entries=active_entries)

        allocs_by_entry: dict[int, list[Any]] = defaultdict(list)
        for alloc in all_allocs:
            allocs_by_entry[alloc.exam_entry_id].append(alloc)

        violations: list[Violation] = []
        for entry in active_entries:
            course = courses_by_id.get(entry.course_id)
            course_code = course.course_code if course else f"course_id={entry.course_id}"
            entry_allocs = allocs_by_entry.get(entry.exam_entry_id, [])

            for alloc in entry_allocs:
                room = rooms_by_id.get(alloc.room_id)
                room_code = room.room_code if room else f"room_id={alloc.room_id}"
                if alloc.seats_allocated <= 0:
                    violations.append(
                        Violation(
                            rule_code=self.rule_code,
                            conflict_type=self.conflict_type,
                            severity="Hard",
                            description=(
                                f"E03 Violation: Exam entry_id={entry.exam_entry_id} ({course_code}) "
                                f"has non-positive seats_allocated={alloc.seats_allocated} in {room_code}."
                            ),
                            entity_ref=(
                                f"exam_entry_id={entry.exam_entry_id} ({course_code}), "
                                f"room_id={alloc.room_id} ({room_code})"
                            ),
                            affected_entities={
                                "exam_entry_id": entry.exam_entry_id,
                                "course_id": entry.course_id,
                                "course_code": course_code,
                                "room_id": alloc.room_id,
                                "room_code": room_code,
                                "seats_allocated": alloc.seats_allocated,
                                "room_capacity": room.capacity if room else None,
                            },
                            schedule_id=schedule_id,
                        )
                    )
                elif room is not None and alloc.seats_allocated > room.capacity:
                    violations.append(
                        Violation(
                            rule_code=self.rule_code,
                            conflict_type=self.conflict_type,
                            severity="Hard",
                            description=(
                                f"E03 Violation: Room {room_code} (room_id={room.room_id}, "
                                f"capacity={room.capacity}) is allocated {alloc.seats_allocated} "
                                f"seats for exam_entry_id={entry.exam_entry_id} ({course_code}), "
                                f"exceeding room capacity."
                            ),
                            entity_ref=(
                                f"exam_entry_id={entry.exam_entry_id} ({course_code}), "
                                f"room_id={room.room_id} ({room_code}), "
                                f"seats={alloc.seats_allocated}/{room.capacity}"
                            ),
                            affected_entities={
                                "exam_entry_id": entry.exam_entry_id,
                                "course_id": entry.course_id,
                                "course_code": course_code,
                                "room_id": room.room_id,
                                "room_code": room_code,
                                "seats_allocated": alloc.seats_allocated,
                                "room_capacity": room.capacity,
                            },
                            schedule_id=schedule_id,
                        )
                    )

            total_seats = sum(a.seats_allocated for a in entry_allocs)
            required_students = expected_counts.get(entry.course_id, entry.student_count)
            if total_seats != entry.student_count or entry.student_count != required_students:
                entity_ref = (
                    f"exam_entry_id={entry.exam_entry_id} ({course_code}), "
                    f"allocated_seats={total_seats}, student_count={entry.student_count}, "
                    f"expected_students={required_students}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"E03 Violation: Exam entry_id={entry.exam_entry_id} ({course_code}) "
                            f"has total allocated seats={total_seats}, which does not equal "
                            f"student_count={entry.student_count} (expected={required_students})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "exam_entry_id": entry.exam_entry_id,
                            "course_id": entry.course_id,
                            "course_code": course_code,
                            "allocated_seats": total_seats,
                            "student_count": entry.student_count,
                            "expected_student_count": required_students,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class E04ExamRoomClash(BaseConstraint):
    """E04: A room is used by at most one exam in a session (Hard, mandatory)."""

    rule_code = "E04"
    rule_type = "Hard"
    conflict_type = "Room"
    mandatory = True
    description_text = "A room is used by at most one exam in a session."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        max_rooms = len(context.eligible_rooms)
        for slot in context.exam_slots:
            slot_vars = [
                context.y[(cid, slot.exam_slot_id)]
                for cid in context.course_ids
                if (cid, slot.exam_slot_id) in context.y
            ]
            if slot_vars:
                model.Add(sum(slot_vars) <= max_rooms)

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_exam_entries(dataset, entries)
        schedule_id = _resolve_exam_schedule_id(active_entries, dataset)
        rooms_by_id = dataset.rooms_by_id
        courses_by_id = dataset.courses_by_id
        entries_by_id = {e.exam_entry_id: e for e in active_entries}
        all_allocs = dataset.resolve_exam_allocations(entries=active_entries)

        room_session_usage: dict[tuple[int, int], list[ExamEntry]] = defaultdict(list)
        for alloc in all_allocs:
            entry = entries_by_id.get(alloc.exam_entry_id)
            if entry is not None:
                room_session_usage[(entry.exam_slot_id, alloc.room_id)].append(entry)

        violations: list[Violation] = []
        for (exam_slot_id, room_id), used_entries in sorted(room_session_usage.items()):
            if len(used_entries) > 1:
                room = rooms_by_id.get(room_id)
                room_code = room.room_code if room else f"Room #{room_id}"
                entry_ids = [e.exam_entry_id for e in used_entries]
                course_ids = [e.course_id for e in used_entries]
                course_codes = [
                    courses_by_id[e.course_id].course_code
                    if e.course_id in courses_by_id
                    else f"course_id={e.course_id}"
                    for e in used_entries
                ]
                entity_ref = (
                    f"room_id={room_id} ({room_code}), exam_slot_id={exam_slot_id}, "
                    f"exam_entry_ids={entry_ids}"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"E04 Violation: Room {room_code} (room_id={room_id}) is allocated "
                            f"to {len(used_entries)} exams ({course_codes}) in "
                            f"exam_slot_id={exam_slot_id} (exam_entry_ids={entry_ids})."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "room_id": room_id,
                            "room_code": room_code,
                            "exam_slot_id": exam_slot_id,
                            "exam_entry_ids": entry_ids,
                            "course_ids": course_ids,
                            "course_codes": course_codes,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class E05SingleSessionPerCourse(BaseConstraint):
    """E05: Every course with an exam is assigned to exactly one session (Hard, mandatory)."""

    rule_code = "E05"
    rule_type = "Hard"
    conflict_type = "SessionCount"
    mandatory = True
    description_text = "Every course with an exam is assigned to exactly one session."

    def add_to_model(self, model: Any, context: Any, param_value: int | None = None) -> None:
        for cid in context.course_ids:
            course_vars = [
                context.y[(cid, slot.exam_slot_id)]
                for slot in context.exam_slots
                if (cid, slot.exam_slot_id) in context.y
            ]
            if course_vars:
                model.AddExactlyOne(course_vars)
            else:
                model.AddBoolOr([])

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        active_entries = _resolve_exam_entries(dataset, entries)
        schedule_id = _resolve_exam_schedule_id(active_entries, dataset)
        courses_by_id = dataset.courses_by_id
        exam_slots_by_id = dataset.exam_slots_by_id

        required_course_ids = sorted(dataset.course_student_counts().keys())
        entries_by_course: dict[int, list[ExamEntry]] = defaultdict(list)
        for entry in active_entries:
            entries_by_course[entry.course_id].append(entry)

        all_course_ids = sorted(set(required_course_ids) | set(entries_by_course.keys()))
        violations: list[Violation] = []

        for cid in all_course_ids:
            course = courses_by_id.get(cid)
            course_code = course.course_code if course else f"course_id={cid}"
            c_entries = entries_by_course.get(cid, [])
            valid_slot_entries = [
                e for e in c_entries if e.exam_slot_id in exam_slots_by_id
            ]

            if cid in required_course_ids and (
                len(c_entries) != 1 or len(valid_slot_entries) != 1
            ):
                entry_ids = [e.exam_entry_id for e in c_entries]
                entity_ref = (
                    f"course_id={cid} ({course_code}), "
                    f"assigned_sessions={len(valid_slot_entries)}/1"
                )
                violations.append(
                    Violation(
                        rule_code=self.rule_code,
                        conflict_type=self.conflict_type,
                        severity="Hard",
                        description=(
                            f"E05 Violation: Course {course_code} (course_id={cid}) must be "
                            f"assigned to exactly 1 valid exam session, but is assigned to "
                            f"{len(c_entries)} session(s) ({len(valid_slot_entries)} valid)."
                        ),
                        entity_ref=entity_ref,
                        affected_entities={
                            "course_id": cid,
                            "course_code": course_code,
                            "expected_sessions": 1,
                            "actual_sessions": len(c_entries),
                            "valid_sessions": len(valid_slot_entries),
                            "exam_entry_ids": entry_ids,
                        },
                        schedule_id=schedule_id,
                    )
                )
        return violations


class ES01ExamDaySpread(BaseConstraint):
    """ES01: Spread the exams of one batch over different days (Soft, default weight=8)."""

    rule_code = "ES01"
    rule_type = "Soft"
    conflict_type = "ExamDaySpread"
    mandatory = False
    default_weight = 8
    description_text = "Spread the exams of one batch over different days."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = weight if weight is not None else (param_value if param_value is not None else self.default_weight)
        if w <= 0:
            return
        courses_by_batch: dict[int, list[int]] = defaultdict(list)
        for cid in context.course_ids:
            for bid in sorted(context.course_batches.get(cid, set())):
                courses_by_batch[bid].append(cid)

        for bid, b_courses in sorted(courses_by_batch.items()):
            for exam_date, day_slots in sorted(context.slots_by_date.items()):
                day_vars = [
                    context.y[(cid, slot.exam_slot_id)]
                    for cid in b_courses
                    for slot in day_slots
                    if (cid, slot.exam_slot_id) in context.y
                ]
                if len(day_vars) > 1:
                    excess = model.NewIntVar(
                        0, len(day_vars), f"es01_excess_b{bid}_{exam_date}"
                    )
                    model.Add(excess >= sum(day_vars) - 1)
                    context.soft_penalty_terms.append(w * excess)

    def penalty(
        self,
        dataset: TimetableDataset,
        entries: list[ExamEntry] | None = None,
        allocations: list[Any] | None = None,
        weight: int | None = None,
    ) -> int:
        """Compute weighted ES01 penalty for batches having multiple exams on the same day."""
        w = self.default_weight if weight is None else weight
        if w <= 0:
            return 0
        active_entries = _resolve_exam_entries(dataset, entries)
        exam_slots_by_id = dataset.exam_slots_by_id
        course_batches = dataset.course_batches()

        batch_date_counts: dict[tuple[int, str], int] = defaultdict(int)
        for entry in active_entries:
            slot = exam_slots_by_id.get(entry.exam_slot_id)
            if slot is None:
                continue
            for bid in course_batches.get(entry.course_id, set()):
                batch_date_counts[(bid, slot.exam_date)] += 1

        extra_same_day = sum(
            max(0, count - 1) for count in batch_date_counts.values()
        )
        return w * extra_same_day

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_exam_entries(dataset, entries)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))
        exam_slots_by_id = dataset.exam_slots_by_id
        course_batches = dataset.course_batches(term_id=term_id)

        batch_date_counts: dict[tuple[int, str], int] = defaultdict(int)
        total_batch_exams = 0
        for entry in active_entries:
            slot = exam_slots_by_id.get(entry.exam_slot_id)
            if slot is None:
                continue
            for bid in course_batches.get(entry.course_id, set()):
                batch_date_counts[(bid, slot.exam_date)] += 1
                total_batch_exams += 1

        violated = sum(max(0, count - 1) for count in batch_date_counts.values())
        total = max(total_batch_exams, violated)
        satisfied = max(0, total - violated)
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class ES02MinimalRoomsPerExam(BaseConstraint):
    """ES02: Use as few rooms as possible per exam (Soft, default weight=5)."""

    rule_code = "ES02"
    rule_type = "Soft"
    conflict_type = "RoomCount"
    mandatory = False
    default_weight = 5
    description_text = "Use as few rooms as possible per exam."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = weight if weight is not None else (param_value if param_value is not None else self.default_weight)
        if w <= 0:
            return
        max_rooms = max(1, len(context.eligible_rooms))
        for cid in context.course_ids:
            z_vars = [
                context.z[(cid, slot.exam_slot_id, room.room_id)]
                for slot in context.exam_slots
                for room in context.eligible_rooms
                if (cid, slot.exam_slot_id, room.room_id) in context.z
            ]
            if len(z_vars) > 1:
                extra_rooms = model.NewIntVar(0, max_rooms, f"es02_extra_rooms_c{cid}")
                model.Add(extra_rooms >= sum(z_vars) - 1)
                context.soft_penalty_terms.append(w * extra_rooms)

    def penalty(
        self,
        dataset: TimetableDataset,
        entries: list[ExamEntry] | None = None,
        allocations: list[Any] | None = None,
        weight: int | None = None,
    ) -> int:
        """Compute weighted ES02 penalty for exams split across multiple rooms."""
        w = self.default_weight if weight is None else weight
        if w <= 0:
            return 0
        active_entries = _resolve_exam_entries(dataset, entries)
        all_allocs = (
            allocations
            if allocations is not None
            else dataset.resolve_exam_allocations(entries=active_entries)
        )
        rooms_per_entry: dict[int, set[int]] = defaultdict(set)
        for alloc in all_allocs:
            if alloc.seats_allocated > 0:
                rooms_per_entry[alloc.exam_entry_id].add(alloc.room_id)

        extra_rooms = sum(
            max(0, len(rooms_per_entry.get(e.exam_entry_id, set())) - 1)
            for e in active_entries
        )
        return w * extra_rooms

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_exam_entries(dataset, entries)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))
        all_allocs = (
            allocations
            if allocations is not None
            else dataset.resolve_exam_allocations(entries=active_entries)
        )
        rooms_per_entry: dict[int, set[int]] = defaultdict(set)
        for alloc in all_allocs:
            if alloc.seats_allocated > 0:
                rooms_per_entry[alloc.exam_entry_id].add(alloc.room_id)

        violated = sum(
            max(0, len(rooms_per_entry.get(e.exam_entry_id, set())) - 1)
            for e in active_entries
        )
        total = max(len(active_entries), violated)
        satisfied = max(0, total - violated)
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []


class ES03SameBuildingPerExam(BaseConstraint):
    """ES03: Keep the rooms of one exam in the same building (Soft, default weight=4)."""

    rule_code = "ES03"
    rule_type = "Soft"
    conflict_type = "BuildingSpread"
    mandatory = False
    default_weight = 4
    description_text = "Keep the rooms of one exam in the same building."

    def add_to_model(
        self,
        model: Any,
        context: Any,
        param_value: int | None = None,
        weight: int | None = None,
    ) -> None:
        w = weight if weight is not None else (param_value if param_value is not None else self.default_weight)
        if w <= 0:
            return
        rooms_by_bldg: dict[str, list[Any]] = defaultdict(list)
        for room in context.eligible_rooms:
            rooms_by_bldg[room.building].append(room)

        if len(rooms_by_bldg) <= 1:
            return

        for cid in context.course_ids:
            bldg_vars: list[Any] = []
            for b_idx, (_bldg_name, b_rooms) in enumerate(sorted(rooms_by_bldg.items())):
                b_var = model.NewBoolVar(f"es03_bldg_c{cid}_b{b_idx}")
                for slot in context.exam_slots:
                    for room in b_rooms:
                        key = (cid, slot.exam_slot_id, room.room_id)
                        if key in context.z:
                            model.AddImplication(context.z[key], b_var)
                bldg_vars.append(b_var)
            extra_bldgs = model.NewIntVar(
                0, len(bldg_vars), f"es03_extra_bldgs_c{cid}"
            )
            model.Add(extra_bldgs >= sum(bldg_vars) - 1)
            context.soft_penalty_terms.append(w * extra_bldgs)

    def penalty(
        self,
        dataset: TimetableDataset,
        entries: list[ExamEntry] | None = None,
        allocations: list[Any] | None = None,
        weight: int | None = None,
    ) -> int:
        """Compute weighted ES03 penalty for exams whose rooms span multiple buildings."""
        w = self.default_weight if weight is None else weight
        if w <= 0:
            return 0
        active_entries = _resolve_exam_entries(dataset, entries)
        rooms_by_id = dataset.rooms_by_id
        all_allocs = (
            allocations
            if allocations is not None
            else dataset.resolve_exam_allocations(entries=active_entries)
        )
        bldgs_per_entry: dict[int, set[str]] = defaultdict(set)
        for alloc in all_allocs:
            if alloc.seats_allocated > 0 and alloc.room_id in rooms_by_id:
                bldgs_per_entry[alloc.exam_entry_id].add(
                    rooms_by_id[alloc.room_id].building
                )

        extra_bldgs = sum(
            max(0, len(bldgs_per_entry.get(e.exam_entry_id, set())) - 1)
            for e in active_entries
        )
        return w * extra_bldgs

    def evaluate_score(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        *,
        weight: int | None = None,
        param_value: int | None = None,
        is_enabled: bool = True,
        previous_entries: list[TimetableEntry] | None = None,
        allocations: list[Any] | None = None,
        term_id: int | None = None,
    ) -> SoftConstraintBreakdown:
        active_entries = _resolve_exam_entries(dataset, entries)
        eff_weight = 0 if not is_enabled else (self.default_weight if weight is None else max(0, int(weight)))
        rooms_by_id = dataset.rooms_by_id
        all_allocs = (
            allocations
            if allocations is not None
            else dataset.resolve_exam_allocations(entries=active_entries)
        )
        bldgs_per_entry: dict[int, set[str]] = defaultdict(set)
        for alloc in all_allocs:
            if alloc.seats_allocated > 0 and alloc.room_id in rooms_by_id:
                bldgs_per_entry[alloc.exam_entry_id].add(
                    rooms_by_id[alloc.room_id].building
                )

        violated = sum(
            max(0, len(bldgs_per_entry.get(e.exam_entry_id, set())) - 1)
            for e in active_entries
        )
        total = max(len(active_entries), violated)
        satisfied = max(0, total - violated)
        return SoftConstraintBreakdown(
            rule_code=self.rule_code,
            description=self.describe(),
            is_enabled=is_enabled and eff_weight > 0,
            weight=eff_weight,
            param_value=param_value,
            satisfied_count=satisfied,
            violated_count=violated,
            total_count=total,
            weighted_score=float(eff_weight * satisfied),
            max_weighted_score=float(eff_weight * total),
            weighted_penalty=float(eff_weight * violated),
        )

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[Any] | None = None,
        param_value: int | None = None,
    ) -> list[Violation]:
        return []



HARD_EXAM_CONSTRAINTS: dict[str, BaseConstraint] = {
    "E01": E01StudentExamClash(),
    "E02": E02DailyExamLimit(),
    "E03": E03ExamSeatAllocation(),
    "E04": E04ExamRoomClash(),
    "E05": E05SingleSessionPerCourse(),
}

SOFT_EXAM_CONSTRAINTS: dict[str, BaseConstraint] = {
    "ES01": ES01ExamDaySpread(),
    "ES02": ES02MinimalRoomsPerExam(),
    "ES03": ES03SameBuildingPerExam(),
}
