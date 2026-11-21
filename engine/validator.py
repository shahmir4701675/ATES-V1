"""Independent timetable and examination validator for ATES (FR-6.7, FR-7.7, FR-8.1, SRS Section 4.3.1).

Evaluates any weekly timetable schedule against hard constraints H01–H10 and any examination
schedule against hard constraints E01–E05 without relying on any solver model or web layer.
"""

from __future__ import annotations

from dataclasses import replace

from engine.constraints import (
    BaseConstraint,
    HARD_EXAM_CONSTRAINTS,
    HARD_TIMETABLE_CONSTRAINTS,
)
from engine.models import (
    ExamEntry,
    ExamRoomAllocation,
    MANDATORY_EXAM_RULES,
    MANDATORY_TIMETABLE_RULES,
    TimetableDataset,
    TimetableEntry,
    Violation,
)


class TimetableValidator:
    """Independent validator checking weekly timetable schedules against H01–H10."""

    def __init__(
        self,
        constraints: dict[str, BaseConstraint] | None = None,
    ) -> None:
        self._constraints: dict[str, BaseConstraint] = (
            dict(HARD_TIMETABLE_CONSTRAINTS) if constraints is None else dict(constraints)
        )

    def _enabled_rule_map(
        self, dataset: TimetableDataset, config_id: int | None = None
    ) -> dict[str, tuple[bool, int | None]]:
        """Determine enabled state and param_value for H01–H10 (FR-5.1, FR-5.2)."""
        state: dict[str, tuple[bool, int | None]] = {
            code: (True, None) for code in self._constraints
        }
        for rule in dataset.constraint_rules:
            if config_id is not None and rule.config_id != config_id:
                continue
            if rule.rule_code in self._constraints:
                # Mandatory rules cannot be disabled per FR-5.2
                is_enabled = True if rule.rule_code in MANDATORY_TIMETABLE_RULES else rule.is_enabled
                state[rule.rule_code] = (is_enabled, rule.param_value)
        return state

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry] | None = None,
        config_id: int | None = None,
    ) -> list[Violation]:
        """Validate `dataset` (or explicit `entries`) against all enabled hard constraints H01–H10.

        Returns a list of `Violation` objects with `rule_code`, `conflict_type`, `severity`,
        `description`, `entity_ref`, and `affected_entities`. An empty list means the
        schedule is valid.
        """
        active_entries = dataset.timetable_entries if entries is None else entries
        if config_id is None and dataset.schedules:
            config_id = dataset.schedules[0].config_id

        rule_states = self._enabled_rule_map(dataset, config_id=config_id)
        violations: list[Violation] = []

        for code in sorted(self._constraints.keys()):
            constraint = self._constraints[code]
            is_enabled, param_value = rule_states.get(code, (True, None))
            if constraint.mandatory or is_enabled:
                violations.extend(
                    constraint.validate(
                        dataset=dataset,
                        entries=active_entries,
                        param_value=param_value,
                    )
                )

        return violations

    def validate_exam(
        self,
        dataset: TimetableDataset,
        entries: list[ExamEntry] | None = None,
        allocations: list[ExamRoomAllocation] | None = None,
        config_id: int | None = None,
    ) -> list[Violation]:
        """Validate `dataset` against all enabled hard examination constraints E01–E05."""
        return ExamValidator().validate(
            dataset=dataset,
            entries=entries,
            allocations=allocations,
            config_id=config_id,
        )


class ExamValidator:
    """Independent validator checking examination schedules against E01–E05 (FR-7.7, FR-8.1)."""

    def __init__(
        self,
        constraints: dict[str, BaseConstraint] | None = None,
    ) -> None:
        self._constraints: dict[str, BaseConstraint] = (
            dict(HARD_EXAM_CONSTRAINTS) if constraints is None else dict(constraints)
        )

    def _enabled_rule_map(
        self, dataset: TimetableDataset, config_id: int | None = None
    ) -> dict[str, tuple[bool, int | None]]:
        """Determine enabled state and param_value for E01–E05 (FR-5.1, FR-5.2)."""
        state: dict[str, tuple[bool, int | None]] = {
            code: (True, None) for code in self._constraints
        }
        for rule in dataset.constraint_rules:
            if config_id is not None and rule.config_id != config_id:
                continue
            if rule.rule_code in self._constraints:
                is_enabled = True if rule.rule_code in MANDATORY_EXAM_RULES else rule.is_enabled
                state[rule.rule_code] = (is_enabled, rule.param_value)
        return state

    def validate(
        self,
        dataset: TimetableDataset,
        entries: list[ExamEntry] | None = None,
        allocations: list[ExamRoomAllocation] | None = None,
        config_id: int | None = None,
    ) -> list[Violation]:
        """Validate `dataset` (or explicit `entries`/`allocations`) against enabled E01–E05.

        Returns a list of `Violation` objects. An empty list means the examination
        schedule satisfies all hard constraints.
        """
        active_entries = dataset.exam_entries if entries is None else entries
        active_dataset = dataset
        if entries is not None or allocations is not None:
            active_dataset = replace(
                dataset,
                exam_entries=active_entries,
                exam_room_allocations=(
                    dataset.exam_room_allocations if allocations is None else allocations
                ),
            )

        if config_id is None and active_dataset.schedules:
            for sch in active_dataset.schedules:
                if sch.schedule_type == "Exam":
                    config_id = sch.config_id
                    break
            if config_id is None:
                config_id = active_dataset.schedules[0].config_id

        rule_states = self._enabled_rule_map(active_dataset, config_id=config_id)
        violations: list[Violation] = []

        for code in sorted(self._constraints.keys()):
            constraint = self._constraints[code]
            is_enabled, param_value = rule_states.get(code, (True, None))
            if constraint.mandatory or is_enabled:
                violations.extend(
                    constraint.validate(
                        dataset=active_dataset,
                        entries=active_entries,
                        param_value=param_value,
                    )
                )

        return violations


def validate_timetable(
    dataset: TimetableDataset,
    entries: list[TimetableEntry] | None = None,
    config_id: int | None = None,
) -> list[Violation]:
    """Convenience function to validate a timetable dataset against H01–H10."""
    validator = TimetableValidator()
    return validator.validate(dataset=dataset, entries=entries, config_id=config_id)


def validate_exam_schedule(
    dataset: TimetableDataset,
    entries: list[ExamEntry] | None = None,
    allocations: list[ExamRoomAllocation] | None = None,
    config_id: int | None = None,
) -> list[Violation]:
    """Convenience function to validate an examination schedule against E01–E05."""
    validator = ExamValidator()
    return validator.validate(
        dataset=dataset,
        entries=entries,
        allocations=allocations,
        config_id=config_id,
    )

