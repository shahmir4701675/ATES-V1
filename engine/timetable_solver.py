"""OR-Tools CP-SAT weekly timetable solver for ATES (Milestones 2 & 4: FA-6, C-4, Appendix A.5).

Models each required session (lecture slot or lab block slot) as a variable over
`(slot, room)` pairs, enforces hard constraints H01–H10 (always enforcing mandatory
rules H01, H02, H03, H08 per FR-5.2), maximises the weighted sum of satisfied soft
constraints S01–S06 (with integer weights 0–10 read from configuration, where 0 or
disabled is ignored per FR-5.1, FR-5.4, FR-6.4), supports configurable solver time limit
(default 120 s per C-4) and deterministic random seed (FR-6.9), validates every
candidate solution with the independent `TimetableValidator` before returning it
(FR-6.7), and produces human-readable infeasibility reasons when no schedule exists
(UR-17, FR-6.1, FR-6.5).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

from ortools.sat.python import cp_model

from engine.constraints import (
    BaseConstraint,
    HARD_TIMETABLE_CONSTRAINTS,
    SOFT_TIMETABLE_CONSTRAINTS,
)
from engine.models import (
    MANDATORY_TIMETABLE_RULES,
    Room,
    SOFT_WEIGHT_MAX,
    SOFT_WEIGHT_MIN,
    Schedule,
    SoftConstraintBreakdown,
    TimeSlot,
    TimetableDataset,
    TimetableEntry,
    Violation,
    format_score_summary,
)
from engine.validator import TimetableValidator

SOLVER_LIMIT_DEFAULT: float = 120.0
DEFAULT_RANDOM_SEED: int = 1


def _normalize_previous_entries(previous_schedule: Any) -> list[TimetableEntry]:
    """Extract a list of `TimetableEntry` objects from optional `previous_schedule` input."""
    if previous_schedule is None:
        return []
    if isinstance(previous_schedule, TimetableDataset):
        return list(previous_schedule.timetable_entries)
    if hasattr(previous_schedule, "schedule") and isinstance(
        getattr(previous_schedule, "schedule"), list
    ):
        return list(previous_schedule.schedule)
    if isinstance(previous_schedule, (list, tuple)):
        return list(previous_schedule)
    return []


@dataclass
class RequiredSession:
    """One schedulable session unit (1 lecture slot or 1 slot of a lab block) (FR-2.9, FR-6.3)."""

    session_idx: int
    offering_id: int
    course_id: int
    course_code: str
    batch_id: int
    instructor_id: int
    enrolled_count: int
    session_type: str  # 'Lecture' or 'Lab'
    occurrence_index: int
    group_size: int
    locked_slot_id: int | None = None
    locked_room_id: int | None = None


@dataclass
class SolverContext:
    """Shared CP-SAT model context passed to each constraint's `add_to_model` method."""

    dataset: TimetableDataset
    term_id: int
    sessions: list[RequiredSession]
    slots: list[TimeSlot]
    rooms: list[Room]
    slot_room_pairs: list[tuple[int, int]]
    x: dict[tuple[int, int, int], cp_model.IntVar]
    session_vars: dict[int, cp_model.IntVar]
    sessions_by_instructor: dict[int, list[RequiredSession]] = field(default_factory=dict)
    sessions_by_batch: dict[int, list[RequiredSession]] = field(default_factory=dict)
    sessions_by_offering: dict[int, list[RequiredSession]] = field(default_factory=dict)
    slots_by_day: dict[int, list[TimeSlot]] = field(default_factory=dict)
    slot_by_day_and_index: dict[tuple[int, int], TimeSlot] = field(default_factory=dict)
    previous_entries: list[TimetableEntry] = field(default_factory=list)
    soft_reward_terms: list[Any] = field(default_factory=list)
    soft_max_score: int = 0


@dataclass
class TimetableSolveResult:
    """Result returned by the ATES CP-SAT timetable solver (FA-6, C-4, FR-6.4)."""

    schedule: list[TimetableEntry]
    solver_status: str  # 'optimal', 'feasible', 'infeasible', 'unknown'
    run_time: float
    reasons: list[str] = field(default_factory=list)
    schedule_record: Schedule | None = None
    violations: list[Violation] = field(default_factory=list)
    objective_score: float | None = None
    max_score: float | None = None
    soft_breakdown: dict[str, SoftConstraintBreakdown] = field(default_factory=dict)
    soft_penalties: dict[str, int] = field(default_factory=dict)

    @property
    def entries(self) -> list[TimetableEntry]:
        """Alias for `schedule` (`list[TimetableEntry]`)."""
        return self.schedule

    @property
    def timetable_entries(self) -> list[TimetableEntry]:
        """Alias for `schedule` (`list[TimetableEntry]`)."""
        return self.schedule

    @property
    def status(self) -> str:
        """Alias for `solver_status`."""
        return self.solver_status

    @property
    def run_seconds(self) -> float:
        """Alias for `run_time` matching `schedules.run_seconds`."""
        return self.run_time

    @property
    def infeasibility_reasons(self) -> list[str]:
        """Alias for `reasons`."""
        return self.reasons

    @property
    def is_feasible(self) -> bool:
        """Return True when a valid, hard-constraint-free schedule was produced."""
        return self.solver_status in ("optimal", "feasible") and len(self.violations) == 0

    @property
    def max_possible_score(self) -> float | None:
        """Alias for `max_score`."""
        return self.max_score

    @property
    def constraint_breakdown(self) -> dict[str, SoftConstraintBreakdown]:
        """Alias for `soft_breakdown`."""
        return self.soft_breakdown

    @property
    def per_constraint_breakdown(self) -> dict[str, SoftConstraintBreakdown]:
        """Alias for `soft_breakdown`."""
        return self.soft_breakdown

    @property
    def breakdown(self) -> dict[str, SoftConstraintBreakdown]:
        """Alias for `soft_breakdown`."""
        return self.soft_breakdown

    @property
    def score_percentage(self) -> float:
        """Return objective score as a percentage of `max_score` in [0.0, 100.0]."""
        if self.objective_score is None:
            return 0.0
        if self.max_score is None or self.max_score <= 0:
            return 100.0
        pct = 100.0 * float(self.objective_score) / float(self.max_score)
        return round(max(0.0, min(100.0, pct)), 2)

    @property
    def score_summary(self) -> str:
        """Return formatted UI summary string, e.g. `'score 128 (87% of maximum)'`."""
        return format_score_summary(self.objective_score, self.max_score)

    def __iter__(self) -> Iterator[Any]:
        """Allow tuple unpacking: `schedule, solver_status, run_time, reasons = result`."""
        yield self.schedule
        yield self.solver_status
        yield self.run_time
        yield self.reasons

    def to_dict(self) -> dict[str, Any]:
        """Convert solver result to a JSON-serializable dictionary."""
        return {
            "schedule": [asdict(e) for e in self.schedule],
            "solver_status": self.solver_status,
            "run_time": self.run_time,
            "reasons": list(self.reasons),
            "schedule_record": asdict(self.schedule_record) if self.schedule_record else None,
            "violations": [v.to_conflict_log_dict() for v in self.violations],
            "objective_score": self.objective_score,
            "max_score": self.max_score,
            "max_possible_score": self.max_score,
            "score_percentage": self.score_percentage,
            "score_summary": self.score_summary,
            "soft_breakdown": {
                code: bd.to_dict() for code, bd in self.soft_breakdown.items()
            },
            "soft_penalties": dict(self.soft_penalties),
        }


class TimetableSolver:
    """OR-Tools CP-SAT weekly timetable solver enforcing H01–H10 and optimising S01–S06."""

    def __init__(
        self,
        constraints: dict[str, BaseConstraint] | None = None,
        validator: TimetableValidator | None = None,
        soft_constraints: dict[str, BaseConstraint] | None = None,
    ) -> None:
        if constraints is None:
            self._constraints: dict[str, BaseConstraint] = dict(HARD_TIMETABLE_CONSTRAINTS)
            extra_soft: dict[str, BaseConstraint] = {}
        else:
            self._constraints = {
                code: c for code, c in constraints.items() if getattr(c, "rule_type", "Hard") != "Soft"
            }
            extra_soft = {
                code: c for code, c in constraints.items() if getattr(c, "rule_type", "Hard") == "Soft"
            }

        self._soft_constraints: dict[str, BaseConstraint] = (
            dict(SOFT_TIMETABLE_CONSTRAINTS) if soft_constraints is None else dict(soft_constraints)
        )
        self._soft_constraints.update(extra_soft)

        self._validator: TimetableValidator = (
            TimetableValidator(constraints=self._constraints) if validator is None else validator
        )

    def _resolve_rule_states(
        self, dataset: TimetableDataset, config_id: int | None = None
    ) -> dict[str, tuple[bool, int | None]]:
        """Determine enabled state and parameter for H01–H10 (FR-5.1, FR-5.2).

        Mandatory rules (H01, H02, H03, H08) are always enabled even if marked disabled.
        """
        states: dict[str, tuple[bool, int | None]] = {
            code: (True, None) for code in self._constraints
        }
        for rule in dataset.constraint_rules:
            if config_id is not None and rule.config_id != config_id:
                continue
            if rule.rule_code in self._constraints:
                enabled = True if rule.rule_code in MANDATORY_TIMETABLE_RULES else rule.is_enabled
                states[rule.rule_code] = (enabled, rule.param_value)
        for mandatory_code in MANDATORY_TIMETABLE_RULES:
            if mandatory_code in states:
                _, param = states[mandatory_code]
                states[mandatory_code] = (True, param)
        return states

    def _resolve_soft_rule_states(
        self, dataset: TimetableDataset, config_id: int | None = None
    ) -> dict[str, tuple[bool, int, int | None]]:
        """Determine `(is_enabled, weight, param_value)` for soft constraints S01–S06 (FR-5.1, FR-5.4).

        Each weight is an integer 0–10 read from configuration (`0` or `is_enabled=False` means ignored).
        """
        soft_states: dict[str, tuple[bool, int, int | None]] = {}
        for code, constraint in self._soft_constraints.items():
            default_w = int(getattr(constraint, "default_weight", 5))
            clamped_default_w = max(SOFT_WEIGHT_MIN, min(SOFT_WEIGHT_MAX, default_w))
            default_p = getattr(constraint, "default_param", None)
            soft_states[code] = (clamped_default_w > 0, clamped_default_w, default_p)

        for rule in dataset.constraint_rules:
            if config_id is not None and rule.config_id != config_id:
                continue
            if rule.rule_code in self._soft_constraints:
                constraint = self._soft_constraints[rule.rule_code]
                default_p = getattr(constraint, "default_param", None)
                param_val = rule.param_value if rule.param_value is not None else default_p
                raw_w = int(rule.weight) if rule.weight is not None else 0
                clamped_w = max(SOFT_WEIGHT_MIN, min(SOFT_WEIGHT_MAX, raw_w))
                if not rule.is_enabled or clamped_w <= 0:
                    soft_states[rule.rule_code] = (False, 0, param_val)
                else:
                    soft_states[rule.rule_code] = (True, clamped_w, param_val)

        return soft_states

    def _resolve_term_id(self, dataset: TimetableDataset, term_id: int | None) -> int:
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

    def _resolve_config(
        self,
        dataset: TimetableDataset,
        config_id: int | None,
        term_id: int,
    ) -> tuple[int, float, int]:
        """Return `(resolved_config_id, config_time_limit_s, config_random_seed)`."""
        for cfg in dataset.scheduling_configs:
            if config_id is not None and cfg.config_id == config_id:
                return cfg.config_id, float(cfg.solver_time_limit_s), int(cfg.random_seed)
        for cfg in dataset.scheduling_configs:
            if cfg.term_id == term_id and cfg.schedule_type == "Timetable":
                return cfg.config_id, float(cfg.solver_time_limit_s), int(cfg.random_seed)
        if dataset.scheduling_configs:
            cfg = dataset.scheduling_configs[0]
            return cfg.config_id, float(cfg.solver_time_limit_s), int(cfg.random_seed)
        return (config_id or 1), SOLVER_LIMIT_DEFAULT, DEFAULT_RANDOM_SEED

    def check_input_and_diagnose(
        self,
        dataset: TimetableDataset,
        rule_states: dict[str, tuple[bool, int | None]],
        term_id: int,
    ) -> tuple[bool, list[str]]:
        """Check input completeness (FR-6.1) and diagnose infeasibility causes (UR-17, H01–H10).

        Returns `(has_structural_defect, reasons)`.
        """
        reasons: list[str] = []
        structural_defect = False

        def is_on(code: str) -> bool:
            if code in MANDATORY_TIMETABLE_RULES:
                return True
            return rule_states.get(code, (True, None))[0]

        term_slots = [s for s in dataset.time_slots if s.term_id == term_id]
        active_rooms = [r for r in dataset.rooms if r.is_active]
        term_offerings = [o for o in dataset.course_offerings if o.term_id == term_id]

        if not term_offerings:
            reasons.append(f"FR-6.1 Input Defect: No course offerings found for term_id={term_id}.")
            return True, reasons
        if not term_slots:
            reasons.append(f"FR-6.1 Input Defect: No time slots defined for term_id={term_id}.")
            return True, reasons
        if not active_rooms:
            reasons.append("FR-6.1 Input Defect: No active rooms available in dataset.")
            return True, reasons

        courses_by_id = dataset.courses_by_id
        batches_by_id = dataset.batches_by_id
        instructors_by_id = dataset.instructors_by_id
        slots_by_id = {s.slot_id: s for s in term_slots}
        rooms_by_id = {r.room_id: r for r in active_rooms}

        # Check FR-6.1 completeness for every offering (course, batch, instructor)
        valid_offerings = []
        for off in term_offerings:
            course = courses_by_id.get(off.course_id)
            batch = batches_by_id.get(off.batch_id)
            instructor = instructors_by_id.get(off.instructor_id)
            if course is None or not course.is_active:
                structural_defect = True
                reasons.append(
                    f"FR-6.1 Input Defect: Offering offering_id={off.offering_id} references "
                    f"missing or inactive course_id={off.course_id}."
                )
                continue
            if batch is None or not batch.is_active:
                structural_defect = True
                reasons.append(
                    f"FR-6.1 Input Defect: Offering offering_id={off.offering_id} ({course.course_code}) "
                    f"references missing or inactive batch_id={off.batch_id}."
                )
                continue
            if instructor is None or not instructor.is_active:
                structural_defect = True
                reasons.append(
                    f"FR-6.1 Input Defect: Offering offering_id={off.offering_id} ({course.course_code}) "
                    f"references missing or inactive instructor_id={off.instructor_id}."
                )
                continue
            valid_offerings.append(off)

        if structural_defect:
            return True, reasons

        slot_len = dataset.term_slot_length_minutes(term_id)
        usable_slots = [s for s in term_slots if not (is_on("H07") and s.is_blocked)]
        if not usable_slots:
            reasons.append(
                "H07/BlockedSlot: All time slots in the term are marked as blocked; "
                "0 unblocked slots available for scheduling."
            )
            return False, reasons

        slot_by_day_idx: dict[tuple[int, int], TimeSlot] = {
            (s.day_of_week, s.slot_index): s for s in term_slots
        }

        total_lecture_slots_needed = 0
        total_lab_slots_needed = 0
        inst_required_slots: dict[int, int] = defaultdict(int)
        inst_required_minutes: dict[int, int] = defaultdict(int)
        inst_offering_codes: dict[int, list[str]] = defaultdict(list)
        batch_required_slots: dict[int, int] = defaultdict(int)
        batch_offering_codes: dict[int, list[str]] = defaultdict(list)

        for off in valid_offerings:
            course = courses_by_id[off.course_id]
            instructor = instructors_by_id[off.instructor_id]
            lec_slots = course.required_lecture_sessions(slot_len)
            lab_slots = course.required_lab_slots(slot_len)
            total_slots_for_off = lec_slots + lab_slots

            total_lecture_slots_needed += lec_slots
            total_lab_slots_needed += lab_slots
            inst_required_slots[off.instructor_id] += total_slots_for_off
            inst_required_minutes[off.instructor_id] += total_slots_for_off * slot_len
            inst_offering_codes[off.instructor_id].append(
                f"{course.course_code} (offering_id={off.offering_id})"
            )
            batch_required_slots[off.batch_id] += total_slots_for_off
            batch_offering_codes[off.batch_id].append(
                f"{course.course_code} (offering_id={off.offering_id})"
            )

            # Check suitable rooms for Lecture sessions (FR-6.1, H04, H05)
            if lec_slots > 0:
                type_ok_rooms = [
                    r for r in active_rooms if (not is_on("H05") or r.room_type == "Lecture")
                ]
                cap_ok_rooms = [
                    r for r in type_ok_rooms if (not is_on("H04") or r.capacity >= off.enrolled_count)
                ]
                if not type_ok_rooms:
                    reasons.append(
                        f"H05/RoomType: Offering offering_id={off.offering_id} ({course.course_code}) "
                        f"requires {lec_slots} Lecture session(s), but no active Lecture room exists."
                    )
                elif not cap_ok_rooms:
                    max_cap = max((r.capacity for r in type_ok_rooms), default=0)
                    reasons.append(
                        f"H04/Capacity: Offering offering_id={off.offering_id} ({course.course_code}) "
                        f"has enrolled_count={off.enrolled_count}, exceeding the maximum Lecture room "
                        f"capacity of {max_cap}."
                    )

            # Check suitable rooms for Lab sessions (FR-6.1, H04, H05)
            if lab_slots > 0:
                type_ok_rooms = [
                    r for r in active_rooms if (not is_on("H05") or r.room_type == "Lab")
                ]
                cap_ok_rooms = [
                    r for r in type_ok_rooms if (not is_on("H04") or r.capacity >= off.enrolled_count)
                ]
                if not type_ok_rooms:
                    reasons.append(
                        f"H05/RoomType: Offering offering_id={off.offering_id} ({course.course_code}) "
                        f"requires {lab_slots} Lab slot(s), but no active Lab room exists."
                    )
                elif not cap_ok_rooms:
                    max_cap = max((r.capacity for r in type_ok_rooms), default=0)
                    reasons.append(
                        f"H04/Capacity: Offering offering_id={off.offering_id} ({course.course_code}) "
                        f"has enrolled_count={off.enrolled_count}, exceeding the maximum Lab room "
                        f"capacity of {max_cap}."
                    )

            # Check H09 contiguous lab block feasibility (with H06, H07, H10)
            if lab_slots >= 2 and is_on("H09"):
                valid_lab_chains = 0
                for s in term_slots:
                    chain = []
                    for offset in range(lab_slots):
                        cand = slot_by_day_idx.get((s.day_of_week, s.slot_index + offset))
                        if cand is None:
                            break
                        if is_on("H07") and cand.is_blocked:
                            break
                        if is_on("H06") and not dataset.is_instructor_available(
                            off.instructor_id, cand.slot_id
                        ):
                            break
                        chain.append(cand)
                    if len(chain) == lab_slots:
                        valid_lab_chains += 1

                if valid_lab_chains == 0:
                    reasons.append(
                        f"H09/LabBlock: Offering offering_id={off.offering_id} ({course.course_code}) "
                        f"requires {lab_slots} consecutive Lab slots on one day, but no valid "
                        f"{lab_slots}-slot contiguous unblocked/available window exists for "
                        f"instructor {instructor.full_name} (instructor_id={off.instructor_id})."
                    )

                if is_on("H10"):
                    lab_block_hours = (lab_slots * slot_len) / 60.0
                    if lab_block_hours > instructor.max_daily_hours:
                        reasons.append(
                            f"H09/H10/Workload: Offering offering_id={off.offering_id} ({course.course_code}) "
                            f"requires a contiguous {lab_block_hours:g}-hour Lab block on one day, "
                            f"exceeding instructor {instructor.full_name} (instructor_id={off.instructor_id}) "
                            f"max_daily_hours={instructor.max_daily_hours}."
                        )

        # Global room-slot supply checks (H02, H05, H07, H08)
        total_sessions_needed = total_lecture_slots_needed + total_lab_slots_needed
        total_room_slots = len(usable_slots) * len(active_rooms)
        if total_sessions_needed > total_room_slots:
            reasons.append(
                f"H02/H08/SlotSupply: Total required session slots ({total_sessions_needed}) "
                f"exceed total usable room-slot capacity ({total_room_slots} across "
                f"{len(active_rooms)} rooms and {len(usable_slots)} usable slots)."
            )

        if is_on("H05"):
            lecture_rooms = [r for r in active_rooms if r.room_type == "Lecture"]
            lab_rooms = [r for r in active_rooms if r.room_type == "Lab"]
            if lecture_rooms and total_lecture_slots_needed > len(usable_slots) * len(lecture_rooms):
                reasons.append(
                    f"H02/H05/LectureRoomSupply: Total required Lecture slots "
                    f"({total_lecture_slots_needed}) exceed total usable Lecture room-slots "
                    f"({len(usable_slots) * len(lecture_rooms)})."
                )
            if lab_rooms and total_lab_slots_needed > len(usable_slots) * len(lab_rooms):
                reasons.append(
                    f"H02/H05/LabRoomSupply: Total required Lab slots "
                    f"({total_lab_slots_needed}) exceed total usable Lab room-slots "
                    f"({len(usable_slots) * len(lab_rooms)})."
                )

        # Batch slot supply checks (H03, H07, H08)
        for batch_id, needed_slots in sorted(batch_required_slots.items()):
            batch = batches_by_id[batch_id]
            if needed_slots > len(usable_slots):
                reasons.append(
                    f"H03/Batch: Batch {batch.label} (batch_id={batch_id}) requires "
                    f"{needed_slots} weekly slots across offerings "
                    f"[{', '.join(batch_offering_codes[batch_id])}], exceeding the "
                    f"{len(usable_slots)} usable weekly slots."
                )

        # Instructor availability and workload checks (H01, H06, H07, H08, H10)
        for instructor_id, needed_slots in sorted(inst_required_slots.items()):
            instructor = instructors_by_id[instructor_id]
            avail_usable_slots = [
                s
                for s in usable_slots
                if not (is_on("H06") and not dataset.is_instructor_available(instructor_id, s.slot_id))
            ]
            if needed_slots > len(avail_usable_slots):
                reasons.append(
                    f"H01/H06/Availability: Instructor {instructor.full_name} "
                    f"(instructor_id={instructor_id}) requires {needed_slots} weekly slots "
                    f"for [{', '.join(inst_offering_codes[instructor_id])}], but only has "
                    f"{len(avail_usable_slots)} usable available slot(s)."
                )

            if is_on("H10"):
                needed_hours = inst_required_minutes[instructor_id] / 60.0
                if needed_hours > instructor.max_weekly_hours:
                    reasons.append(
                        f"H10/Workload: Instructor {instructor.full_name} "
                        f"(instructor_id={instructor_id}) requires {needed_hours:g} weekly teaching "
                        f"hours for [{', '.join(inst_offering_codes[instructor_id])}], exceeding "
                        f"max_weekly_hours={instructor.max_weekly_hours}."
                    )

                avail_hours_by_day: dict[int, float] = defaultdict(float)
                for s in avail_usable_slots:
                    avail_hours_by_day[s.day_of_week] += s.duration_hours
                max_weekly_by_daily_cap = sum(
                    min(day_hrs, float(instructor.max_daily_hours))
                    for day_hrs in avail_hours_by_day.values()
                )
                if needed_hours > max_weekly_by_daily_cap:
                    reasons.append(
                        f"H10/Workload: Instructor {instructor.full_name} "
                        f"(instructor_id={instructor_id}) requires {needed_hours:g} weekly teaching "
                        f"hours, but daily limit max_daily_hours={instructor.max_daily_hours} "
                        f"across available days allows at most {max_weekly_by_daily_cap:g} hours/week."
                    )

        # Locked entries check (FR-6.10)
        locked_entries = [e for e in dataset.timetable_entries if e.is_locked]
        for entry in locked_entries:
            if entry.slot_id not in slots_by_id:
                reasons.append(
                    f"FR-6.10/LockedEntry: Locked entry_id={entry.entry_id} references "
                    f"invalid slot_id={entry.slot_id}."
                )
            if entry.room_id not in rooms_by_id:
                reasons.append(
                    f"FR-6.10/LockedEntry: Locked entry_id={entry.entry_id} references "
                    f"invalid or inactive room_id={entry.room_id}."
                )

        return False, reasons

    def _build_required_sessions(
        self,
        dataset: TimetableDataset,
        term_id: int,
    ) -> list[RequiredSession]:
        """Expand active course offerings into individual `RequiredSession` variables (FR-2.9, FR-6.3)."""
        courses_by_id = dataset.courses_by_id
        slots_by_id = dataset.slots_by_id
        slot_len = dataset.term_slot_length_minutes(term_id)

        locked_by_group: dict[tuple[int, str], list[TimetableEntry]] = defaultdict(list)
        for entry in dataset.timetable_entries:
            if entry.is_locked:
                locked_by_group[(entry.offering_id, entry.session_type)].append(entry)

        for key in locked_by_group:
            locked_by_group[key].sort(
                key=lambda e: (
                    slots_by_id[e.slot_id].day_of_week if e.slot_id in slots_by_id else 0,
                    slots_by_id[e.slot_id].slot_index if e.slot_id in slots_by_id else 0,
                    e.slot_id,
                )
            )

        sessions: list[RequiredSession] = []
        session_idx = 0

        for offering in sorted(dataset.course_offerings, key=lambda o: o.offering_id):
            if offering.term_id != term_id:
                continue
            course = courses_by_id.get(offering.course_id)
            if course is None or not course.is_active:
                continue

            num_lec = course.required_lecture_sessions(slot_len)
            locked_lecs = locked_by_group.get((offering.offering_id, "Lecture"), [])
            for occ in range(num_lec):
                locked_entry = locked_lecs[occ] if occ < len(locked_lecs) else None
                sessions.append(
                    RequiredSession(
                        session_idx=session_idx,
                        offering_id=offering.offering_id,
                        course_id=offering.course_id,
                        course_code=course.course_code,
                        batch_id=offering.batch_id,
                        instructor_id=offering.instructor_id,
                        enrolled_count=offering.enrolled_count,
                        session_type="Lecture",
                        occurrence_index=occ,
                        group_size=num_lec,
                        locked_slot_id=locked_entry.slot_id if locked_entry else None,
                        locked_room_id=locked_entry.room_id if locked_entry else None,
                    )
                )
                session_idx += 1

            num_lab = course.required_lab_slots(slot_len)
            locked_labs = locked_by_group.get((offering.offering_id, "Lab"), [])
            for occ in range(num_lab):
                locked_entry = locked_labs[occ] if occ < len(locked_labs) else None
                sessions.append(
                    RequiredSession(
                        session_idx=session_idx,
                        offering_id=offering.offering_id,
                        course_id=offering.course_id,
                        course_code=course.course_code,
                        batch_id=offering.batch_id,
                        instructor_id=offering.instructor_id,
                        enrolled_count=offering.enrolled_count,
                        session_type="Lab",
                        occurrence_index=occ,
                        group_size=num_lab,
                        locked_slot_id=locked_entry.slot_id if locked_entry else None,
                        locked_room_id=locked_entry.room_id if locked_entry else None,
                    )
                )
                session_idx += 1

        return sessions

    def _build_cp_model(
        self,
        dataset: TimetableDataset,
        term_id: int,
        sessions: list[RequiredSession],
        rule_states: dict[str, tuple[bool, int | None]],
        soft_rule_states: dict[str, tuple[bool, int, int | None]] | None = None,
        previous_entries: list[TimetableEntry] | None = None,
    ) -> tuple[cp_model.CpModel, SolverContext]:
        """Construct the CP-SAT model with `(slot, room)` variables, H01–H10, and S01–S06."""
        model = cp_model.CpModel()

        slots = sorted(
            [s for s in dataset.time_slots if s.term_id == term_id],
            key=lambda s: (s.day_of_week, s.slot_index, s.slot_id),
        )
        rooms = sorted(
            [r for r in dataset.rooms if r.is_active],
            key=lambda r: r.room_id,
        )

        slot_room_pairs: list[tuple[int, int]] = [
            (slot.slot_id, room.room_id) for slot in slots for room in rooms
        ]
        pair_index_map: dict[tuple[int, int], int] = {
            pair: idx for idx, pair in enumerate(slot_room_pairs)
        }
        x: dict[tuple[int, int, int], cp_model.IntVar] = {}
        session_vars: dict[int, cp_model.IntVar] = {}

        num_pairs = len(slot_room_pairs)

        for u in sessions:
            if num_pairs > 0:
                session_vars[u.session_idx] = model.NewIntVar(
                    0, num_pairs - 1, f"session_{u.session_idx}_slot_room"
                )
            else:
                session_vars[u.session_idx] = model.NewIntVar(0, 0, f"session_{u.session_idx}_empty")

            pair_terms = []
            for slot in slots:
                for room in rooms:
                    key = (u.session_idx, slot.slot_id, room.room_id)
                    var = model.NewBoolVar(
                        f"x_s{u.session_idx}_slot{slot.slot_id}_room{room.room_id}"
                    )
                    x[key] = var
                    p_idx = pair_index_map[(slot.slot_id, room.room_id)]
                    pair_terms.append(p_idx * var)

            if pair_terms:
                model.Add(session_vars[u.session_idx] == sum(pair_terms))

            # FR-6.10: Pin locked session to its (slot, room)
            if u.locked_slot_id is not None and u.locked_room_id is not None:
                locked_key = (u.session_idx, u.locked_slot_id, u.locked_room_id)
                if locked_key in x:
                    model.Add(x[locked_key] == 1)
                else:
                    # Locked to a non-existent or inactive (slot, room) -> infeasible
                    model.AddBoolOr([])

        sessions_by_instructor: dict[int, list[RequiredSession]] = defaultdict(list)
        sessions_by_batch: dict[int, list[RequiredSession]] = defaultdict(list)
        sessions_by_offering: dict[int, list[RequiredSession]] = defaultdict(list)
        for u in sessions:
            sessions_by_instructor[u.instructor_id].append(u)
            sessions_by_batch[u.batch_id].append(u)
            sessions_by_offering[u.offering_id].append(u)

        slots_by_day: dict[int, list[TimeSlot]] = defaultdict(list)
        slot_by_day_and_index: dict[tuple[int, int], TimeSlot] = {}
        for slot in slots:
            slots_by_day[slot.day_of_week].append(slot)
            slot_by_day_and_index[(slot.day_of_week, slot.slot_index)] = slot

        context = SolverContext(
            dataset=dataset,
            term_id=term_id,
            sessions=sessions,
            slots=slots,
            rooms=rooms,
            slot_room_pairs=slot_room_pairs,
            x=x,
            session_vars=session_vars,
            sessions_by_instructor=dict(sessions_by_instructor),
            sessions_by_batch=dict(sessions_by_batch),
            sessions_by_offering=dict(sessions_by_offering),
            slots_by_day=dict(slots_by_day),
            slot_by_day_and_index=slot_by_day_and_index,
            previous_entries=list(previous_entries or []),
        )

        # Symmetry breaking among unlocked identical sessions of the same offering & type
        for _offering_id, off_sessions in sorted(sessions_by_offering.items()):
            unlocked_lectures = [
                u
                for u in off_sessions
                if u.session_type == "Lecture" and u.locked_slot_id is None
            ]
            for i in range(len(unlocked_lectures) - 1):
                u_curr = unlocked_lectures[i]
                u_next = unlocked_lectures[i + 1]
                model.Add(session_vars[u_curr.session_idx] < session_vars[u_next.session_idx])

            unlocked_labs = [
                u
                for u in off_sessions
                if u.session_type == "Lab" and u.locked_slot_id is None
            ]
            if len(unlocked_labs) == sum(1 for u in off_sessions if u.session_type == "Lab"):
                for i in range(len(unlocked_labs) - 1):
                    u_curr = unlocked_labs[i]
                    u_next = unlocked_labs[i + 1]
                    model.Add(session_vars[u_curr.session_idx] < session_vars[u_next.session_idx])

        # Enforce all enabled hard constraints H01–H10 (mandatory ones always enforced per FR-5.2)
        for code in sorted(self._constraints.keys()):
            constraint = self._constraints[code]
            is_enabled, param_value = rule_states.get(code, (True, None))
            if constraint.mandatory or code in MANDATORY_TIMETABLE_RULES or is_enabled:
                constraint.add_to_model(model=model, context=context, param_value=param_value)

        # Add weighted soft constraint objectives S01–S06 (FR-5.4, FR-6.4)
        if soft_rule_states is not None:
            for s_code in sorted(self._soft_constraints.keys()):
                s_constraint = self._soft_constraints[s_code]
                s_enabled, s_weight, s_param = soft_rule_states.get(
                    s_code,
                    (True, int(getattr(s_constraint, "default_weight", 5)), getattr(s_constraint, "default_param", None)),
                )
                if s_enabled and s_weight > 0:
                    try:
                        s_constraint.add_to_model(
                            model=model,
                            context=context,
                            param_value=s_param,
                            weight=s_weight,
                        )
                    except TypeError:
                        s_constraint.add_to_model(
                            model=model,
                            context=context,
                            param_value=s_param,
                        )

            if context.soft_reward_terms:
                max_obj = max(0, int(context.soft_max_score))
                if max_obj > 0:
                    obj_var = model.NewIntVar(0, max_obj, "total_soft_objective")
                    model.Add(obj_var == sum(context.soft_reward_terms))
                    model.Maximize(obj_var)
                else:
                    model.Maximize(sum(context.soft_reward_terms))

        return model, context

    def evaluate_soft_constraints(
        self,
        dataset: TimetableDataset,
        entries: list[TimetableEntry],
        *,
        config_id: int | None = None,
        term_id: int | None = None,
        previous_entries: list[TimetableEntry] | None = None,
    ) -> tuple[float, float, dict[str, SoftConstraintBreakdown], dict[str, int]]:
        """Evaluate all soft constraints S01–S06 and return `(objective_score, max_score, breakdown, penalties)`."""
        resolved_term_id = self._resolve_term_id(dataset, term_id)
        soft_states = self._resolve_soft_rule_states(dataset, config_id=config_id)
        breakdown: dict[str, SoftConstraintBreakdown] = {}
        penalties: dict[str, int] = {}
        total_score = 0.0
        total_max_score = 0.0

        for s_code in sorted(self._soft_constraints.keys()):
            s_constraint = self._soft_constraints[s_code]
            s_enabled, s_weight, s_param = soft_states.get(
                s_code,
                (True, int(getattr(s_constraint, "default_weight", 5)), getattr(s_constraint, "default_param", None)),
            )
            bd = s_constraint.evaluate_score(
                dataset=dataset,
                entries=entries,
                weight=s_weight,
                param_value=s_param,
                is_enabled=s_enabled,
                previous_entries=previous_entries,
                term_id=resolved_term_id,
            )
            breakdown[s_code] = bd
            penalties[s_code] = int(round(bd.weighted_penalty))
            total_score += bd.weighted_score
            total_max_score += bd.max_weighted_score

        return total_score, total_max_score, breakdown, penalties

    def _diagnose_combinatorial_infeasibility(
        self,
        dataset: TimetableDataset,
        term_id: int,
        sessions: list[RequiredSession],
        rule_states: dict[str, tuple[bool, int | None]],
        seed: int,
    ) -> list[str]:
        """Probe which constraint(s) cause CP-SAT infeasibility when pre-checks pass."""
        found_reasons: list[str] = []
        optional_enabled = [
            code
            for code in sorted(self._constraints.keys())
            if code not in MANDATORY_TIMETABLE_RULES
            and not self._constraints[code].mandatory
            and rule_states.get(code, (True, None))[0]
        ]

        for code in optional_enabled:
            relaxed_states = dict(rule_states)
            relaxed_states[code] = (False, relaxed_states[code][1])
            probe_model, _ = self._build_cp_model(
                dataset=dataset,
                term_id=term_id,
                sessions=sessions,
                rule_states=relaxed_states,
            )
            probe_solver = cp_model.CpSolver()
            probe_solver.parameters.max_time_in_seconds = 2.0
            probe_solver.parameters.random_seed = seed
            probe_solver.parameters.num_search_workers = 1
            status = probe_solver.Solve(probe_model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                constraint = self._constraints[code]
                found_reasons.append(
                    f"{code}/{constraint.conflict_type}: Schedule is infeasible due to "
                    f"constraint {code} ({constraint.describe()}); relaxing {code} makes the "
                    f"timetable feasible."
                )

        if not found_reasons:
            enabled_list = [
                code
                for code in sorted(self._constraints.keys())
                if self._constraints[code].mandatory
                or code in MANDATORY_TIMETABLE_RULES
                or rule_states.get(code, (True, None))[0]
            ]
            found_reasons.append(
                f"Combinatorial Conflict: No conflict-free assignment of (slot, room) pairs "
                f"exists satisfying enabled hard constraints {enabled_list} across "
                f"{len(sessions)} required sessions."
            )
        return found_reasons

    def solve(
        self,
        dataset: TimetableDataset,
        time_limit: float | None = None,
        random_seed: int | None = None,
        *,
        time_limit_s: float | None = None,
        seed: int | None = None,
        config_id: int | None = None,
        term_id: int | None = None,
        previous_schedule: Any = None,
        previous_entries: list[TimetableEntry] | None = None,
    ) -> TimetableSolveResult:
        """Solve the weekly timetable CSP using OR-Tools CP-SAT and validate the result.

        Parameters
        ----------
        dataset:
            `TimetableDataset` containing master data, slots, rooms, offerings, and rules.
        time_limit:
            Maximum CP-SAT solver time in seconds (default 120 s per constraint C-4).
        random_seed:
            Random seed for deterministic CP-SAT solving (default 1 per FR-5.5 / FR-6.9).
        time_limit_s:
            Optional keyword alias for `time_limit`.
        seed:
            Optional keyword alias for `random_seed`.
        config_id:
            Optional `scheduling_configs.config_id` to select constraint rules from.
        term_id:
            Optional `academic_terms.term_id` to solve for.
        previous_schedule:
            Optional previous schedule version (`list[TimetableEntry]`, `TimetableSolveResult`,
            or `TimetableDataset`) for S05 stability preference. Skipped if None.
        previous_entries:
            Optional keyword alias for `previous_schedule`.
        """
        start_wall = time.perf_counter()

        resolved_term_id = self._resolve_term_id(dataset, term_id)
        resolved_config_id, cfg_time_limit, cfg_seed = self._resolve_config(
            dataset, config_id, resolved_term_id
        )

        effective_time_limit = (
            float(time_limit_s)
            if time_limit_s is not None
            else (
                float(time_limit)
                if time_limit is not None
                else (cfg_time_limit if cfg_time_limit > 0 else SOLVER_LIMIT_DEFAULT)
            )
        )
        effective_seed = (
            int(seed)
            if seed is not None
            else (int(random_seed) if random_seed is not None else cfg_seed)
        )

        schedule_id = dataset.schedules[0].schedule_id if dataset.schedules else 1
        version_no = dataset.schedules[0].version_no if dataset.schedules else 1

        rule_states = self._resolve_rule_states(dataset, config_id=resolved_config_id)
        soft_rule_states = self._resolve_soft_rule_states(dataset, config_id=resolved_config_id)
        resolved_prev_entries = _normalize_previous_entries(
            previous_entries if previous_entries is not None else previous_schedule
        )

        has_structural_defect, pre_reasons = self.check_input_and_diagnose(
            dataset=dataset,
            rule_states=rule_states,
            term_id=resolved_term_id,
        )

        if has_structural_defect:
            elapsed = round(time.perf_counter() - start_wall, 4)
            sched_rec = Schedule(
                schedule_id=schedule_id,
                term_id=resolved_term_id,
                config_id=resolved_config_id,
                schedule_type="Timetable",
                version_no=version_no,
                status="Infeasible",
                solver_status="infeasible",
                objective_score=None,
                run_seconds=elapsed,
            )
            return TimetableSolveResult(
                schedule=[],
                solver_status="infeasible",
                run_time=elapsed,
                reasons=pre_reasons,
                schedule_record=sched_rec,
                violations=[],
            )

        sessions = self._build_required_sessions(dataset=dataset, term_id=resolved_term_id)
        model, context = self._build_cp_model(
            dataset=dataset,
            term_id=resolved_term_id,
            sessions=sessions,
            rule_states=rule_states,
            soft_rule_states=soft_rule_states,
            previous_entries=resolved_prev_entries,
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = effective_time_limit
        solver.parameters.random_seed = effective_seed
        solver.parameters.num_search_workers = 1

        cp_status = solver.Solve(model)
        elapsed = round(time.perf_counter() - start_wall, 4)

        if cp_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver_status_str = "optimal" if cp_status == cp_model.OPTIMAL else "feasible"
            raw_entries: list[TimetableEntry] = []

            for u in sessions:
                chosen_slot_id: int | None = None
                chosen_room_id: int | None = None
                for slot in context.slots:
                    for room in context.rooms:
                        key = (u.session_idx, slot.slot_id, room.room_id)
                        if key in context.x and solver.BooleanValue(context.x[key]):
                            chosen_slot_id = slot.slot_id
                            chosen_room_id = room.room_id
                            break
                    if chosen_slot_id is not None:
                        break

                if chosen_slot_id is not None and chosen_room_id is not None:
                    raw_entries.append(
                        TimetableEntry(
                            entry_id=0,
                            schedule_id=schedule_id,
                            offering_id=u.offering_id,
                            instructor_id=u.instructor_id,
                            batch_id=u.batch_id,
                            room_id=chosen_room_id,
                            slot_id=chosen_slot_id,
                            session_type=u.session_type,
                            is_locked=(u.locked_slot_id is not None),
                            is_manual_override=False,
                        )
                    )

            # Sort entries deterministically by offering_id, session_type (Lecture then Lab), and slot_id
            raw_entries.sort(
                key=lambda e: (
                    e.offering_id,
                    0 if e.session_type == "Lecture" else 1,
                    e.slot_id,
                    e.room_id,
                )
            )
            for idx, entry in enumerate(raw_entries, start=1):
                entry.entry_id = idx

            # FR-6.7: Run every solution through the independent validator before returning it
            violations = self._validator.validate(
                dataset=dataset,
                entries=raw_entries,
                config_id=resolved_config_id,
            )
            if violations:
                violation_reasons = [
                    f"FR-6.7 Independent Validator Rejection ({v.rule_code}): {v.description}"
                    for v in violations
                ]
                sched_rec = Schedule(
                    schedule_id=schedule_id,
                    term_id=resolved_term_id,
                    config_id=resolved_config_id,
                    schedule_type="Timetable",
                    version_no=version_no,
                    status="Infeasible",
                    solver_status="infeasible",
                    objective_score=None,
                    run_seconds=elapsed,
                )
                return TimetableSolveResult(
                    schedule=[],
                    solver_status="infeasible",
                    run_time=elapsed,
                    reasons=violation_reasons,
                    schedule_record=sched_rec,
                    violations=violations,
                )

            # Evaluate soft constraints S01–S06 on the validated schedule
            obj_score, max_score, soft_breakdown, soft_penalties = self.evaluate_soft_constraints(
                dataset=dataset,
                entries=raw_entries,
                config_id=resolved_config_id,
                term_id=resolved_term_id,
                previous_entries=resolved_prev_entries,
            )

            # Validated solution: update dataset.timetable_entries and return Generated schedule
            dataset.timetable_entries = list(raw_entries)
            sched_rec = Schedule(
                schedule_id=schedule_id,
                term_id=resolved_term_id,
                config_id=resolved_config_id,
                schedule_type="Timetable",
                version_no=version_no,
                status="Generated",
                solver_status=solver_status_str,
                objective_score=obj_score,
                run_seconds=elapsed,
            )
            return TimetableSolveResult(
                schedule=raw_entries,
                solver_status=solver_status_str,
                run_time=elapsed,
                reasons=[],
                schedule_record=sched_rec,
                violations=[],
                objective_score=obj_score,
                max_score=max_score,
                soft_breakdown=soft_breakdown,
                soft_penalties=soft_penalties,
            )

        if cp_status == cp_model.INFEASIBLE:
            infeasibility_reasons = list(pre_reasons)
            if not infeasibility_reasons:
                infeasibility_reasons = self._diagnose_combinatorial_infeasibility(
                    dataset=dataset,
                    term_id=resolved_term_id,
                    sessions=sessions,
                    rule_states=rule_states,
                    seed=effective_seed,
                )
            sched_rec = Schedule(
                schedule_id=schedule_id,
                term_id=resolved_term_id,
                config_id=resolved_config_id,
                schedule_type="Timetable",
                version_no=version_no,
                status="Infeasible",
                solver_status="infeasible",
                objective_score=None,
                run_seconds=elapsed,
            )
            return TimetableSolveResult(
                schedule=[],
                solver_status="infeasible",
                run_time=elapsed,
                reasons=infeasibility_reasons,
                schedule_record=sched_rec,
                violations=[],
            )

        # cp_model.UNKNOWN or cp_model.MODEL_INVALID (e.g., time limit reached without finding a solution)
        unknown_reasons = list(pre_reasons)
        unknown_reasons.append(
            f"Solver reached time limit ({effective_time_limit:g} s) without finding a feasible schedule."
        )
        sched_rec = Schedule(
            schedule_id=schedule_id,
            term_id=resolved_term_id,
            config_id=resolved_config_id,
            schedule_type="Timetable",
            version_no=version_no,
            status="Infeasible",
            solver_status="unknown",
            objective_score=None,
            run_seconds=elapsed,
        )
        return TimetableSolveResult(
            schedule=[],
            solver_status="unknown",
            run_time=elapsed,
            reasons=unknown_reasons,
            schedule_record=sched_rec,
            violations=[],
        )


def solve_timetable(
    dataset: TimetableDataset,
    time_limit: float = SOLVER_LIMIT_DEFAULT,
    random_seed: int | None = None,
    *,
    time_limit_s: float | None = None,
    seed: int | None = None,
    config_id: int | None = None,
    term_id: int | None = None,
    previous_schedule: Any = None,
    previous_entries: list[TimetableEntry] | None = None,
    validator: TimetableValidator | None = None,
    soft_constraints: dict[str, BaseConstraint] | None = None,
) -> TimetableSolveResult:
    """Solve a weekly timetable using OR-Tools CP-SAT and validate the solution (FA-6, FR-6.4)."""
    solver = TimetableSolver(validator=validator, soft_constraints=soft_constraints)
    return solver.solve(
        dataset=dataset,
        time_limit=time_limit,
        random_seed=random_seed,
        time_limit_s=time_limit_s,
        seed=seed,
        config_id=config_id,
        term_id=term_id,
        previous_schedule=previous_schedule,
        previous_entries=previous_entries,
    )


generate_timetable = solve_timetable
