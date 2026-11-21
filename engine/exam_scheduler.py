"""Examination scheduler for ATES (FA-7, Section 3.3.4 Figure 13, Appendix A.5 E01–E05 & ES01–ES03).

Implements the hybrid examination scheduling pipeline:
1. Build a NetworkX conflict graph where courses with an exam are vertices and an edge
   joins two courses that share at least one enrolled student (FR-7.1).
2. Colour the conflict graph with the DSATUR heuristic and map colours to exam sessions,
   respecting E01 (no student exam clash), E02 (max exams per student per day), and soft
   preference ES01 (spread batch exams across different days) (FR-7.2, FR-7.3, FR-7.6).
3. If more sessions are needed than defined (or DSATUR cannot satisfy daily/room limits),
   fall back to an exact OR-Tools CP-SAT step; if still impossible, return an Infeasible
   result listing the session shortfall and the courses that cannot be placed (FR-7.2, FR-7.5).
4. Allocate eligible exam rooms ('Exam Hall', 'Lecture') to each exam so that allocated
   seats equal student_count, never exceed room capacity (E03), no room is used twice in
   one session (E04, FR-7.4), and soft preferences ES02 (minimal rooms per exam) and
   ES03 (same building per exam) are optimised (FR-7.6).
5. Verify every generated examination schedule through the independent validator (FR-7.7).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import time
from typing import Any, Literal

import networkx as nx
from ortools.sat.python import cp_model

from engine.constraints import (
    BaseConstraint,
    HARD_EXAM_CONSTRAINTS,
    SOFT_EXAM_CONSTRAINTS,
)
from engine.models import (
    ExamEntry,
    ExamRoomAllocation,
    ExamSlot,
    MANDATORY_EXAM_RULES,
    MAX_EXAMS_PER_DAY_DEFAULT,
    Room,
    SOFT_WEIGHT_MAX,
    SOFT_WEIGHT_MIN,
    Schedule,
    SoftConstraintBreakdown,
    TimetableDataset,
    Violation,
    format_score_summary,
)
from engine.validator import ExamValidator

SOLVER_LIMIT_DEFAULT: float = 120.0
DEFAULT_RANDOM_SEED: int = 1
ELIGIBLE_EXAM_ROOM_TYPES: frozenset[str] = frozenset({"Exam Hall", "Lecture"})
DEFAULT_SOFT_EXAM_WEIGHTS: dict[str, int] = {
    "ES01": 8,
    "ES02": 5,
    "ES03": 4,
}

ExamSolverStatus = Literal["optimal", "feasible", "infeasible", "unknown"]


@dataclass
class ExamSolverContext:
    """Context object passed to examination constraints' `add_to_model` methods."""

    dataset: TimetableDataset
    term_id: int | None
    course_ids: list[int]
    exam_slots: list[ExamSlot]
    eligible_rooms: list[Room]
    conflict_graph: nx.Graph
    student_counts: dict[int, int]
    course_students: dict[int, set[str]]
    course_batches: dict[int, set[int]]
    courses_by_student: dict[str, list[int]]
    slots_by_date: dict[str, list[ExamSlot]]
    total_exam_room_capacity: int
    y: dict[tuple[int, int], cp_model.IntVar]
    z: dict[tuple[int, int, int], cp_model.IntVar]
    soft_penalty_terms: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class ExamScheduleResult:
    """Result returned by the examination scheduler (FR-7.1–FR-7.7)."""

    status: ExamSolverStatus
    schedule: Schedule | None
    entries: list[ExamEntry]
    room_allocations: list[ExamRoomAllocation]
    run_time_s: float
    reasons: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    shortfall: int = 0
    unplaced_courses: list[int] = field(default_factory=list)
    unplaced_course_codes: list[str] = field(default_factory=list)
    chromatic_number: int = 0
    used_cpsat_fallback: bool = False
    objective_score: float | None = None
    max_score: float | None = None
    soft_penalties: dict[str, int] = field(default_factory=dict)
    soft_breakdown: dict[str, SoftConstraintBreakdown] = field(default_factory=dict)

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
        """Return formatted UI summary string, e.g. `'score 88 (95% of maximum)'`."""
        return format_score_summary(self.objective_score, self.max_score)


def build_conflict_graph(
    dataset: TimetableDataset,
    term_id: int | None = None,
) -> nx.Graph:
    """Build the course examination conflict graph (FR-7.1, Figure 13 Step 1).

    Vertices are `course_id`s of courses offered in `term_id`. An undirected edge
    `(u, v)` joins two courses iff they share at least one enrolled student or cohort.
    """
    graph = nx.Graph()
    courses_by_id = dataset.courses_by_id
    student_counts = dataset.course_student_counts(term_id=term_id)
    course_students = dataset.course_students(term_id=term_id)
    course_batches = dataset.course_batches(term_id=term_id)

    course_ids = sorted(student_counts.keys())
    for cid in course_ids:
        course = courses_by_id.get(cid)
        graph.add_node(
            cid,
            course_code=course.course_code if course else f"course_id={cid}",
            title=course.title if course else "",
            student_count=student_counts.get(cid, 0),
            students=sorted(course_students.get(cid, set())),
            batches=sorted(course_batches.get(cid, set())),
        )

    n = len(course_ids)
    for i in range(n):
        u = course_ids[i]
        students_u = course_students.get(u, set())
        for j in range(i + 1, n):
            v = course_ids[j]
            students_v = course_students.get(v, set())
            shared = sorted(students_u & students_v)
            if shared:
                graph.add_edge(
                    u,
                    v,
                    shared_students=shared,
                    shared_count=len(shared),
                )

    return graph


def colour_conflict_graph_dsatur(graph: nx.Graph) -> dict[int, int]:
    """Colour the conflict graph using the DSATUR heuristic (FR-7.2, Figure 13 Step 2).

    Returns a dictionary mapping `course_id -> colour_index` (0-indexed).
    """
    if graph.number_of_nodes() == 0:
        return {}
    raw_colouring = nx.coloring.greedy_color(graph, strategy="DSATUR")
    return {int(node): int(colour) for node, colour in raw_colouring.items()}


class ExamScheduler:
    """Hybrid DSATUR + OR-Tools CP-SAT examination scheduler for ATES (FA-7)."""

    def __init__(
        self,
        dataset: TimetableDataset,
        time_limit_s: float | None = None,
        random_seed: int | None = None,
        config_id: int | None = None,
        term_id: int | None = None,
        constraints: dict[str, BaseConstraint] | None = None,
        soft_constraints: dict[str, BaseConstraint] | None = None,
    ) -> None:
        self.dataset = dataset
        self.config_id = config_id
        self.term_id = term_id
        if constraints is None:
            self._constraints: dict[str, BaseConstraint] = dict(HARD_EXAM_CONSTRAINTS)
            extra_soft: dict[str, BaseConstraint] = {}
        else:
            self._constraints = {
                code: c for code, c in constraints.items() if getattr(c, "rule_type", "Hard") != "Soft"
            }
            extra_soft = {
                code: c for code, c in constraints.items() if getattr(c, "rule_type", "Hard") == "Soft"
            }
        self._soft_constraints: dict[str, BaseConstraint] = (
            dict(SOFT_EXAM_CONSTRAINTS)
            if soft_constraints is None
            else dict(soft_constraints)
        )
        self._soft_constraints.update(extra_soft)

        resolved_limit, resolved_seed, resolved_config_id, resolved_term_id = (
            self._resolve_config_params(time_limit_s, random_seed, config_id, term_id)
        )
        self.time_limit_s: float = resolved_limit
        self.random_seed: int = resolved_seed
        self.config_id = resolved_config_id
        self.term_id = resolved_term_id

    def _resolve_config_params(
        self,
        time_limit_s: float | None,
        random_seed: int | None,
        config_id: int | None,
        term_id: int | None,
    ) -> tuple[float, int, int | None, int | None]:
        """Resolve solver parameters from arguments or dataset's `scheduling_configs`."""
        chosen_cfg = None
        if config_id is not None:
            for cfg in self.dataset.scheduling_configs:
                if cfg.config_id == config_id:
                    chosen_cfg = cfg
                    break
        elif self.dataset.scheduling_configs:
            for cfg in self.dataset.scheduling_configs:
                if cfg.schedule_type == "Exam":
                    chosen_cfg = cfg
                    break
            if chosen_cfg is None:
                chosen_cfg = self.dataset.scheduling_configs[0]

        if chosen_cfg is not None:
            if config_id is None:
                config_id = chosen_cfg.config_id
            if term_id is None:
                term_id = chosen_cfg.term_id

        if term_id is None and self.dataset.academic_terms:
            term_id = self.dataset.academic_terms[0].term_id

        limit = (
            float(time_limit_s)
            if time_limit_s is not None
            else (
                float(chosen_cfg.solver_time_limit_s)
                if chosen_cfg is not None
                else SOLVER_LIMIT_DEFAULT
            )
        )
        seed = (
            int(random_seed)
            if random_seed is not None
            else (
                int(chosen_cfg.random_seed)
                if chosen_cfg is not None
                else DEFAULT_RANDOM_SEED
            )
        )
        return limit, seed, config_id, term_id

    def _enabled_rule_map(self) -> dict[str, tuple[bool, int | None]]:
        """Return `{rule_code: (is_enabled, param_value)}` respecting mandatory E01, E04, E05."""
        state: dict[str, tuple[bool, int | None]] = {
            code: (True, MAX_EXAMS_PER_DAY_DEFAULT if code == "E02" else None)
            for code in self._constraints
        }
        for rule in self.dataset.constraint_rules:
            if self.config_id is not None and rule.config_id != self.config_id:
                continue
            if rule.rule_code in self._constraints:
                is_enabled = (
                    True if rule.rule_code in MANDATORY_EXAM_RULES else rule.is_enabled
                )
                param_val = rule.param_value
                if rule.rule_code == "E02" and param_val is None:
                    param_val = MAX_EXAMS_PER_DAY_DEFAULT
                state[rule.rule_code] = (is_enabled, param_val)
        return state

    def _soft_rule_weights(self) -> dict[str, int]:
        """Return active integer weights (0–10) for ES01–ES03 (0 if disabled)."""
        weights: dict[str, int] = {}
        for code, constraint in self._soft_constraints.items():
            default_w = int(getattr(constraint, "default_weight", DEFAULT_SOFT_EXAM_WEIGHTS.get(code, 5)))
            weights[code] = max(SOFT_WEIGHT_MIN, min(SOFT_WEIGHT_MAX, default_w))

        for rule in self.dataset.constraint_rules:
            if self.config_id is not None and rule.config_id != self.config_id:
                continue
            if rule.rule_code in self._soft_constraints:
                if not rule.is_enabled or rule.weight is None or rule.weight <= 0:
                    weights[rule.rule_code] = 0
                else:
                    weights[rule.rule_code] = max(
                        SOFT_WEIGHT_MIN, min(SOFT_WEIGHT_MAX, int(rule.weight))
                    )
        return weights

    def _is_enabled(
        self,
        rule_code: str,
        rule_states: dict[str, tuple[bool, int | None]],
    ) -> bool:
        if rule_code in MANDATORY_EXAM_RULES:
            return True
        return rule_states.get(rule_code, (True, None))[0]

    def _eligible_rooms(self) -> list[Room]:
        """Return active rooms eligible for exams ('Exam Hall', 'Lecture')."""
        rooms = [
            r
            for r in self.dataset.rooms
            if r.is_active and r.room_type in ELIGIBLE_EXAM_ROOM_TYPES
        ]
        rooms.sort(
            key=lambda r: (
                0 if r.room_type == "Exam Hall" else 1,
                -r.capacity,
                r.room_id,
            )
        )
        return rooms

    def _exam_slots_for_term(self) -> list[ExamSlot]:
        """Return sorted exam slots for the target term."""
        slots = [
            s
            for s in self.dataset.exam_slots
            if self.term_id is None or s.term_id == self.term_id
        ]
        slots.sort(key=lambda s: (s.exam_date, s.start_time, s.exam_slot_id))
        return slots

    def allocate_session_rooms(
        self,
        course_ids: list[int],
        student_counts: dict[int, int],
        eligible_rooms: list[Room],
        enforce_capacity: bool = True,
        es02_weight: int = 5,
        es03_weight: int = 4,
    ) -> dict[int, list[tuple[int, int]]] | None:
        """Allocate disjoint rooms in a single session to `course_ids` (FR-7.4, E03, E04, ES02, ES03).

        Optimises soft preferences ES02 (use as few rooms as possible per exam) and
        ES03 (keep rooms of one exam in the same building), breaking ties by preferring
        Exam Hall rooms and larger capacities.
        """
        if not course_ids:
            return {}

        ordered_courses = sorted(
            course_ids,
            key=lambda cid: (-student_counts.get(cid, 0), cid),
        )
        if len(ordered_courses) > len(eligible_rooms):
            return None

        if not enforce_capacity:
            result: dict[int, list[tuple[int, int]]] = {}
            for idx, cid in enumerate(ordered_courses):
                room = eligible_rooms[idx]
                needed = student_counts.get(cid, 0)
                seats = min(room.capacity, max(1, needed)) if needed > 0 else 0
                result[cid] = [(room.room_id, seats)] if seats > 0 else []
            return result

        total_needed = sum(student_counts.get(cid, 0) for cid in ordered_courses)
        total_available = sum(r.capacity for r in eligible_rooms)
        if total_needed > total_available:
            return None

        # Solve exact per-session room allocation optimizing ES02, ES03, and Exam Hall preference
        model = cp_model.CpModel()
        assign: dict[tuple[int, int], cp_model.IntVar] = {}
        for cid in ordered_courses:
            for room in eligible_rooms:
                assign[(cid, room.room_id)] = model.NewBoolVar(
                    f"r_{cid}_{room.room_id}"
                )

        # E04: Each room used by at most one exam in this session
        for room in eligible_rooms:
            model.Add(
                sum(assign[(cid, room.room_id)] for cid in ordered_courses) <= 1
            )

        # E03: Total capacity of assigned rooms covers student_count
        for cid in ordered_courses:
            needed = student_counts.get(cid, 0)
            if needed <= 0:
                for room in eligible_rooms:
                    model.Add(assign[(cid, room.room_id)] == 0)
            else:
                model.Add(
                    sum(
                        room.capacity * assign[(cid, room.room_id)]
                        for room in eligible_rooms
                    )
                    >= needed
                )

        rooms_by_bldg: dict[str, list[Room]] = defaultdict(list)
        for room in eligible_rooms:
            rooms_by_bldg[room.building].append(room)

        objective_terms: list[Any] = []

        # ES02: Minimise rooms per exam (primary weight scaled by 10000)
        eff_es02 = max(1, es02_weight)
        for cid in ordered_courses:
            if student_counts.get(cid, 0) > 0:
                room_sum = sum(assign[(cid, room.room_id)] for room in eligible_rooms)
                objective_terms.append(10000 * eff_es02 * room_sum)

        # ES03: Keep rooms of one exam in the same building (primary weight scaled by 10000)
        if es03_weight > 0 and len(rooms_by_bldg) > 1:
            for cid in ordered_courses:
                if student_counts.get(cid, 0) <= 0:
                    continue
                bldg_vars: list[cp_model.IntVar] = []
                for b_idx, (_bldg_name, b_rooms) in enumerate(
                    sorted(rooms_by_bldg.items())
                ):
                    b_var = model.NewBoolVar(f"bldg_{cid}_{b_idx}")
                    for room in b_rooms:
                        model.AddImplication(assign[(cid, room.room_id)], b_var)
                    bldg_vars.append(b_var)
                extra_b = model.NewIntVar(0, len(bldg_vars), f"extra_bldg_{cid}")
                model.Add(extra_b >= sum(bldg_vars) - 1)
                objective_terms.append(10000 * es03_weight * extra_b)

        # Secondary tie-breaker: prefer Exam Hall over Lecture and follow eligible_rooms ordering
        for r_idx, room in enumerate(eligible_rooms):
            type_cost = 10 if room.room_type == "Exam Hall" else 50
            tie_cost = type_cost + r_idx
            for cid in ordered_courses:
                objective_terms.append(tie_cost * assign[(cid, room.room_id)])

        model.Minimize(sum(objective_terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None

        exact_alloc: dict[int, list[tuple[int, int]]] = {}
        for cid in ordered_courses:
            needed = student_counts.get(cid, 0)
            rem = needed
            selected_rooms = [
                room
                for room in eligible_rooms
                if solver.BooleanValue(assign[(cid, room.room_id)])
            ]
            # Order selected rooms by Exam Hall first, largest capacity first
            selected_rooms.sort(
                key=lambda r: (
                    0 if r.room_type == "Exam Hall" else 1,
                    -r.capacity,
                    r.room_id,
                )
            )
            chosen: list[tuple[int, int]] = []
            for room in selected_rooms:
                if rem <= 0:
                    break
                seats = min(room.capacity, rem)
                chosen.append((room.room_id, seats))
                rem -= seats
            if rem > 0:
                return None
            exact_alloc[cid] = chosen

        return exact_alloc

    def _split_colour_classes_for_rooms(
        self,
        colouring: dict[int, int],
        student_counts: dict[int, int],
        eligible_rooms: list[Room],
        enforce_e03: bool,
        es02_weight: int = 5,
        es03_weight: int = 4,
    ) -> list[list[int]] | None:
        """Group courses by DSATUR colour and split any group that exceeds single-session room capacity."""
        by_colour: dict[int, list[int]] = defaultdict(list)
        for cid, col in sorted(colouring.items()):
            by_colour[col].append(cid)

        colour_groups: list[list[int]] = []
        for col in sorted(by_colour.keys()):
            group = sorted(
                by_colour[col],
                key=lambda cid: (-student_counts.get(cid, 0), cid),
            )
            if (
                self.allocate_session_rooms(
                    group,
                    student_counts,
                    eligible_rooms,
                    enforce_capacity=enforce_e03,
                    es02_weight=es02_weight,
                    es03_weight=es03_weight,
                )
                is not None
            ):
                colour_groups.append(group)
                continue

            remaining = list(group)
            while remaining:
                current_sub: list[int] = []
                next_remaining: list[int] = []
                for cid in remaining:
                    candidate = current_sub + [cid]
                    if (
                        self.allocate_session_rooms(
                            candidate,
                            student_counts,
                            eligible_rooms,
                            enforce_capacity=enforce_e03,
                            es02_weight=es02_weight,
                            es03_weight=es03_weight,
                        )
                        is not None
                    ):
                        current_sub = candidate
                    else:
                        next_remaining.append(cid)
                if not current_sub:
                    return None
                colour_groups.append(current_sub)
                remaining = next_remaining

        return colour_groups

    def _map_colour_groups_to_slots(
        self,
        colour_groups: list[list[int]],
        exam_slots: list[ExamSlot],
        course_students: dict[int, set[str]],
        course_batches: dict[int, set[int]],
        enforce_e02: bool,
        max_exams_per_day: int,
        es01_weight: int = 8,
    ) -> dict[int, int] | None:
        """Map DSATUR colour groups injectively to `exam_slots` respecting E02 and optimising ES01."""
        k = len(colour_groups)
        if k > len(exam_slots):
            return None
        if k == 0:
            return {}

        indexed_groups = list(enumerate(colour_groups))
        indexed_groups.sort(
            key=lambda item: (
                -sum(len(course_students.get(cid, set())) for cid in item[1]),
                -len(item[1]),
                item[0],
            )
        )

        group_student_counts: list[dict[str, int]] = []
        group_batch_counts: list[dict[int, int]] = []
        for _, grp in indexed_groups:
            s_counts: dict[str, int] = defaultdict(int)
            b_counts: dict[int, int] = defaultdict(int)
            for cid in grp:
                for st in course_students.get(cid, set()):
                    s_counts[st] += 1
                for bid in course_batches.get(cid, set()):
                    b_counts[bid] += 1
            group_student_counts.append(dict(s_counts))
            group_batch_counts.append(dict(b_counts))

        used_slot_indices: set[int] = set()
        daily_student_load: dict[tuple[str, str], int] = defaultdict(int)
        daily_batch_load: dict[tuple[int, str], int] = defaultdict(int)
        current_slot_for_pos: dict[int, int] = {}
        best_slot_for_pos: dict[int, int] | None = None
        best_cost: tuple[int, int] | None = None

        def backtrack(pos: int, current_es01_clashes: int, slot_idx_sum: int) -> bool:
            nonlocal best_slot_for_pos, best_cost

            if best_cost is not None and (current_es01_clashes, slot_idx_sum) >= best_cost:
                return False

            if pos == k:
                best_cost = (current_es01_clashes, slot_idx_sum)
                best_slot_for_pos = dict(current_slot_for_pos)
                # Stop immediately if ES01 is disabled or we achieved 0 same-day batch clashes
                return es01_weight <= 0 or current_es01_clashes == 0

            s_counts = group_student_counts[pos]
            b_counts = group_batch_counts[pos]

            # Order candidate exam slots by fewest incremental ES01 batch clashes, then slot index
            candidates: list[tuple[int, int]] = []
            for slot_idx, slot in enumerate(exam_slots):
                if slot_idx in used_slot_indices:
                    continue
                if enforce_e02:
                    violates_e02 = False
                    for st, inc in s_counts.items():
                        if (
                            daily_student_load[(st, slot.exam_date)] + inc
                            > max_exams_per_day
                        ):
                            violates_e02 = True
                            break
                    if violates_e02:
                        continue

                inc_es01 = 0
                if es01_weight > 0:
                    for bid, b_inc in b_counts.items():
                        prev = daily_batch_load[(bid, slot.exam_date)]
                        new_val = prev + b_inc
                        inc_es01 += max(0, new_val - 1) - max(0, prev - 1)

                candidates.append((inc_es01, slot_idx))

            candidates.sort()

            for inc_es01, slot_idx in candidates:
                slot = exam_slots[slot_idx]
                used_slot_indices.add(slot_idx)
                current_slot_for_pos[pos] = slot.exam_slot_id
                if enforce_e02:
                    for st, inc in s_counts.items():
                        daily_student_load[(st, slot.exam_date)] += inc
                if es01_weight > 0:
                    for bid, b_inc in b_counts.items():
                        daily_batch_load[(bid, slot.exam_date)] += b_inc

                stop_now = backtrack(
                    pos + 1,
                    current_es01_clashes + inc_es01,
                    slot_idx_sum + slot_idx,
                )

                if es01_weight > 0:
                    for bid, b_inc in b_counts.items():
                        daily_batch_load[(bid, slot.exam_date)] -= b_inc
                if enforce_e02:
                    for st, inc in s_counts.items():
                        daily_student_load[(st, slot.exam_date)] -= inc
                del current_slot_for_pos[pos]
                used_slot_indices.remove(slot_idx)

                if stop_now:
                    return True

            return False

        backtrack(0, 0, 0)
        if best_slot_for_pos is None:
            return None

        course_to_slot: dict[int, int] = {}
        for pos, (_, grp) in enumerate(indexed_groups):
            slot_id = best_slot_for_pos[pos]
            for cid in grp:
                course_to_slot[cid] = slot_id
        return course_to_slot

    def _build_context(
        self,
        course_ids: list[int],
        exam_slots: list[ExamSlot],
        eligible_rooms: list[Room],
        conflict_graph: nx.Graph,
        student_counts: dict[int, int],
        course_students: dict[int, set[str]],
        course_batches: dict[int, set[int]],
        y: dict[tuple[int, int], cp_model.IntVar],
        z: dict[tuple[int, int, int], cp_model.IntVar],
    ) -> ExamSolverContext:
        courses_by_student: dict[str, list[int]] = defaultdict(list)
        for cid in course_ids:
            for st in sorted(course_students.get(cid, set())):
                courses_by_student[st].append(cid)

        slots_by_date: dict[str, list[ExamSlot]] = defaultdict(list)
        for slot in exam_slots:
            slots_by_date[slot.exam_date].append(slot)

        total_cap = sum(r.capacity for r in eligible_rooms)
        return ExamSolverContext(
            dataset=self.dataset,
            term_id=self.term_id,
            course_ids=course_ids,
            exam_slots=exam_slots,
            eligible_rooms=eligible_rooms,
            conflict_graph=conflict_graph,
            student_counts=student_counts,
            course_students=course_students,
            course_batches=course_batches,
            courses_by_student=dict(courses_by_student),
            slots_by_date=dict(slots_by_date),
            total_exam_room_capacity=total_cap,
            y=y,
            z=z,
        )

    def _extract_locked_exams(
        self,
    ) -> tuple[dict[int, int], dict[int, list[tuple[int, int]]]]:
        """Extract locked course-to-slot and course-to-room-allocations from `dataset.exam_entries` (FR-6.10)."""
        locked_slots: dict[int, int] = {}
        locked_rooms: dict[int, list[tuple[int, int]]] = {}
        all_allocs = self.dataset.resolve_exam_allocations()
        allocs_by_entry: dict[int, list[ExamRoomAllocation]] = defaultdict(list)
        for alloc in all_allocs:
            allocs_by_entry[alloc.exam_entry_id].append(alloc)

        for entry in self.dataset.exam_entries:
            if entry.is_locked:
                locked_slots[entry.course_id] = entry.exam_slot_id
                e_allocs = (
                    list(entry.room_allocations)
                    if entry.room_allocations
                    else allocs_by_entry.get(entry.exam_entry_id, [])
                )
                if e_allocs:
                    locked_rooms[entry.course_id] = [
                        (a.room_id, a.seats_allocated)
                        for a in e_allocs
                        if a.seats_allocated > 0
                    ]
        return locked_slots, locked_rooms

    def _solve_with_cpsat(
        self,
        course_ids: list[int],
        exam_slots: list[ExamSlot],
        eligible_rooms: list[Room],
        conflict_graph: nx.Graph,
        student_counts: dict[int, int],
        course_students: dict[int, set[str]],
        course_batches: dict[int, set[int]],
        rule_states: dict[str, tuple[bool, int | None]],
        remaining_time_s: float,
        soft_weights: dict[str, int] | None = None,
        locked_slots: dict[int, int] | None = None,
        locked_rooms: dict[int, list[tuple[int, int]]] | None = None,
    ) -> tuple[
        ExamSolverStatus,
        dict[int, int] | None,
        dict[int, list[tuple[int, int]]] | None,
    ]:
        """Exact CP-SAT fallback step (FR-7.2, FR-7.6, FR-6.10, Figure 13 Step 3)."""
        if not exam_slots or not eligible_rooms:
            return "infeasible", None, None

        active_soft_weights = (
            self._soft_rule_weights() if soft_weights is None else soft_weights
        )
        pinned_slots = locked_slots or {}
        pinned_rooms = locked_rooms or {}

        model = cp_model.CpModel()
        y: dict[tuple[int, int], cp_model.IntVar] = {}
        z: dict[tuple[int, int, int], cp_model.IntVar] = {}

        for cid in course_ids:
            for slot in exam_slots:
                y[(cid, slot.exam_slot_id)] = model.NewBoolVar(
                    f"y_c{cid}_s{slot.exam_slot_id}"
                )
                for room in eligible_rooms:
                    z[(cid, slot.exam_slot_id, room.room_id)] = model.NewBoolVar(
                        f"z_c{cid}_s{slot.exam_slot_id}_r{room.room_id}"
                    )

        # FR-6.10: Pin locked exam sessions and their room allocations
        valid_slot_ids = {s.exam_slot_id for s in exam_slots}
        valid_room_ids = {r.room_id for r in eligible_rooms}
        for cid, locked_slot_id in pinned_slots.items():
            if cid not in course_ids:
                continue
            if locked_slot_id not in valid_slot_ids:
                return "infeasible", None, None
            model.Add(y[(cid, locked_slot_id)] == 1)
            if cid in pinned_rooms and pinned_rooms[cid]:
                req_room_ids = {r_id for r_id, _ in pinned_rooms[cid]}
                if not req_room_ids.issubset(valid_room_ids):
                    return "infeasible", None, None
                for room in eligible_rooms:
                    if room.room_id in req_room_ids:
                        model.Add(z[(cid, locked_slot_id, room.room_id)] == 1)
                    else:
                        model.Add(z[(cid, locked_slot_id, room.room_id)] == 0)

        context = self._build_context(
            course_ids=course_ids,
            exam_slots=exam_slots,
            eligible_rooms=eligible_rooms,
            conflict_graph=conflict_graph,
            student_counts=student_counts,
            course_students=course_students,
            course_batches=course_batches,
            y=y,
            z=z,
        )

        # Add enabled hard constraints E01–E05 from constraint classes
        for code in sorted(self._constraints.keys()):
            constraint = self._constraints[code]
            is_enabled, param_value = rule_states.get(code, (True, None))
            if constraint.mandatory or is_enabled:
                constraint.add_to_model(model, context, param_value=param_value)

        # Link room-allocation variables z to session-assignment variables y (E03 & E04 exactness)
        enforce_e03 = self._is_enabled("E03", rule_states)
        for cid in course_ids:
            needed = student_counts.get(cid, 0)
            for slot in exam_slots:
                y_var = y[(cid, slot.exam_slot_id)]
                z_vars = [
                    z[(cid, slot.exam_slot_id, room.room_id)] for room in eligible_rooms
                ]
                for z_var in z_vars:
                    model.AddImplication(z_var, y_var)
                if enforce_e03:
                    model.Add(
                        sum(
                            room.capacity * z[(cid, slot.exam_slot_id, room.room_id)]
                            for room in eligible_rooms
                        )
                        >= needed * y_var
                    )
                elif needed > 0:
                    model.Add(sum(z_vars) >= 1).OnlyEnforceIf(y_var)

        # E04: No room is used twice in the same exam session
        for slot in exam_slots:
            for room in eligible_rooms:
                model.Add(
                    sum(z[(cid, slot.exam_slot_id, room.room_id)] for cid in course_ids)
                    <= 1
                )

        # Add soft preferences ES01–ES03
        for s_code in sorted(self._soft_constraints.keys()):
            s_weight = active_soft_weights.get(s_code, 0)
            if s_weight > 0:
                try:
                    self._soft_constraints[s_code].add_to_model(
                        model, context, param_value=s_weight, weight=s_weight
                    )
                except TypeError:
                    self._soft_constraints[s_code].add_to_model(
                        model, context, param_value=s_weight
                    )

        if context.soft_penalty_terms:
            model.Minimize(sum(context.soft_penalty_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, float(remaining_time_s))
        solver.parameters.random_seed = int(self.random_seed)
        solver.parameters.num_search_workers = 1

        raw_status = solver.Solve(model)
        if raw_status == cp_model.INFEASIBLE:
            return "infeasible", None, None
        if raw_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return "unknown", None, None

        status_str: ExamSolverStatus = (
            "optimal" if raw_status == cp_model.OPTIMAL else "feasible"
        )
        course_to_slot: dict[int, int] = {}
        course_to_rooms: dict[int, list[tuple[int, int]]] = {}

        for cid in course_ids:
            chosen_slot_id: int | None = None
            for slot in exam_slots:
                if solver.BooleanValue(y[(cid, slot.exam_slot_id)]):
                    chosen_slot_id = slot.exam_slot_id
                    break
            if chosen_slot_id is None:
                return "infeasible", None, None
            course_to_slot[cid] = chosen_slot_id

            if cid in pinned_rooms and pinned_rooms[cid]:
                course_to_rooms[cid] = list(pinned_rooms[cid])
                continue

            needed = student_counts.get(cid, 0)
            rem = needed
            selected_rooms = [
                room
                for room in eligible_rooms
                if solver.BooleanValue(z[(cid, chosen_slot_id, room.room_id)])
            ]
            selected_rooms.sort(
                key=lambda r: (
                    0 if r.room_type == "Exam Hall" else 1,
                    -r.capacity,
                    r.room_id,
                )
            )
            alloc_list: list[tuple[int, int]] = []
            for room in selected_rooms:
                if rem <= 0:
                    break
                seats = (
                    min(room.capacity, rem)
                    if enforce_e03
                    else min(room.capacity, max(1, rem))
                )
                alloc_list.append((room.room_id, seats))
                rem -= seats
            course_to_rooms[cid] = alloc_list

        return status_str, course_to_slot, course_to_rooms

    def compute_soft_penalties(
        self,
        entries: list[ExamEntry],
        allocations: list[ExamRoomAllocation],
        soft_weights: dict[str, int] | None = None,
    ) -> dict[str, int]:
        """Compute weighted soft penalty breakdown for ES01–ES03 (FR-7.6)."""
        active_weights = (
            self._soft_rule_weights() if soft_weights is None else soft_weights
        )
        penalties: dict[str, int] = {}
        for code in sorted(self._soft_constraints.keys()):
            constraint = self._soft_constraints[code]
            w = active_weights.get(code, 0)
            if hasattr(constraint, "penalty"):
                penalties[code] = int(
                    constraint.penalty(
                        dataset=self.dataset,
                        entries=entries,
                        allocations=allocations,
                        weight=w,
                    )
                )
            else:
                bd = constraint.evaluate_score(
                    dataset=self.dataset,
                    entries=entries,
                    allocations=allocations,
                    weight=w,
                    is_enabled=(w > 0),
                    term_id=self.term_id,
                )
                penalties[code] = int(round(bd.weighted_penalty))
        return penalties

    def evaluate_soft_constraints(
        self,
        entries: list[ExamEntry],
        allocations: list[ExamRoomAllocation],
        soft_weights: dict[str, int] | None = None,
    ) -> tuple[float, float, dict[str, SoftConstraintBreakdown], dict[str, int]]:
        """Evaluate soft examination constraints ES01–ES03 and return `(objective_score, max_score, breakdown, penalties)`."""
        active_weights = (
            self._soft_rule_weights() if soft_weights is None else soft_weights
        )
        breakdown: dict[str, SoftConstraintBreakdown] = {}
        penalties: dict[str, int] = {}
        total_score = 0.0
        total_max_score = 0.0

        for code in sorted(self._soft_constraints.keys()):
            constraint = self._soft_constraints[code]
            w = active_weights.get(code, 0)
            bd = constraint.evaluate_score(
                dataset=self.dataset,
                entries=entries,
                allocations=allocations,
                weight=w,
                is_enabled=(w > 0),
                term_id=self.term_id,
            )
            breakdown[code] = bd
            if hasattr(constraint, "penalty"):
                penalties[code] = int(
                    constraint.penalty(
                        dataset=self.dataset,
                        entries=entries,
                        allocations=allocations,
                        weight=w,
                    )
                )
            else:
                penalties[code] = int(round(bd.weighted_penalty))
            total_score += bd.weighted_score
            total_max_score += bd.max_weighted_score

        return total_score, total_max_score, breakdown, penalties

    def _diagnose_infeasibility(
        self,
        course_ids: list[int],
        exam_slots: list[ExamSlot],
        eligible_rooms: list[Room],
        conflict_graph: nx.Graph,
        dsatur_colouring: dict[int, int],
        student_counts: dict[int, int],
        course_students: dict[int, set[str]],
        rule_states: dict[str, tuple[bool, int | None]],
    ) -> tuple[int, list[int], list[str], list[str]]:
        """Determine the session shortfall, unplaced courses, and diagnostic reasons (FR-7.5)."""
        courses_by_id = self.dataset.courses_by_id
        reasons: list[str] = []

        num_defined_slots = len(exam_slots)
        num_dsatur_colours = (
            len(set(dsatur_colouring.values())) if dsatur_colouring else 0
        )

        unplaced_courses: list[int] = []
        if not exam_slots:
            unplaced_courses = list(course_ids)
            reasons.append(
                f"E05 Infeasibility: 0 exam_slots are defined, so none of the "
                f"{len(course_ids)} course(s) can be scheduled."
            )
        elif not eligible_rooms:
            unplaced_courses = list(course_ids)
            reasons.append(
                "E03/E04 Infeasibility: 0 active eligible exam rooms ('Exam Hall' or 'Lecture') "
                "exist in the dataset."
            )
        else:
            model = cp_model.CpModel()
            y: dict[tuple[int, int], cp_model.IntVar] = {}
            z: dict[tuple[int, int, int], cp_model.IntVar] = {}
            placed: dict[int, cp_model.IntVar] = {}

            for cid in course_ids:
                placed[cid] = model.NewBoolVar(f"placed_c{cid}")
                for slot in exam_slots:
                    y[(cid, slot.exam_slot_id)] = model.NewBoolVar(
                        f"y_c{cid}_s{slot.exam_slot_id}"
                    )
                    for room in eligible_rooms:
                        z[(cid, slot.exam_slot_id, room.room_id)] = model.NewBoolVar(
                            f"z_c{cid}_s{slot.exam_slot_id}_r{room.room_id}"
                        )
                model.Add(
                    sum(y[(cid, slot.exam_slot_id)] for slot in exam_slots)
                    == placed[cid]
                )

            # E01: Conflict graph edges
            for u, v in sorted(conflict_graph.edges()):
                for slot in exam_slots:
                    model.Add(
                        y[(u, slot.exam_slot_id)] + y[(v, slot.exam_slot_id)] <= 1
                    )

            # E02: Daily exam limit
            if self._is_enabled("E02", rule_states):
                max_per_day = rule_states.get("E02", (True, MAX_EXAMS_PER_DAY_DEFAULT))[1]
                if max_per_day is None:
                    max_per_day = MAX_EXAMS_PER_DAY_DEFAULT
                courses_by_student: dict[str, list[int]] = defaultdict(list)
                for cid in course_ids:
                    for st in sorted(course_students.get(cid, set())):
                        courses_by_student[st].append(cid)
                slots_by_date: dict[str, list[ExamSlot]] = defaultdict(list)
                for slot in exam_slots:
                    slots_by_date[slot.exam_date].append(slot)
                for _st, st_courses in sorted(courses_by_student.items()):
                    for _dt, dt_slots in sorted(slots_by_date.items()):
                        terms = [
                            y[(cid, s.exam_slot_id)]
                            for cid in st_courses
                            for s in dt_slots
                        ]
                        if len(terms) > max_per_day:
                            model.Add(sum(terms) <= max_per_day)

            # E03 & E04: Room capacity and single exam per room per session
            enforce_e03 = self._is_enabled("E03", rule_states)
            for cid in course_ids:
                needed = student_counts.get(cid, 0)
                for slot in exam_slots:
                    y_var = y[(cid, slot.exam_slot_id)]
                    for room in eligible_rooms:
                        model.AddImplication(
                            z[(cid, slot.exam_slot_id, room.room_id)], y_var
                        )
                    if enforce_e03:
                        model.Add(
                            sum(
                                room.capacity * z[(cid, slot.exam_slot_id, room.room_id)]
                                for room in eligible_rooms
                            )
                            >= needed * y_var
                        )

            for slot in exam_slots:
                for room in eligible_rooms:
                    model.Add(
                        sum(
                            z[(cid, slot.exam_slot_id, room.room_id)]
                            for cid in course_ids
                        )
                        <= 1
                    )

            max_weight = len(course_ids) + 1
            model.Maximize(
                sum(
                    (max_weight * max_weight - idx) * placed[cid]
                    for idx, cid in enumerate(course_ids)
                )
            )
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 5.0
            solver.parameters.random_seed = int(self.random_seed)
            solver.parameters.num_search_workers = 1
            status = solver.Solve(model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                unplaced_courses = [
                    cid
                    for cid in course_ids
                    if not solver.BooleanValue(placed[cid])
                ]

        if not unplaced_courses:
            unplaced_courses = [
                cid
                for cid in course_ids
                if dsatur_colouring.get(cid, 0) >= num_defined_slots
            ] or [course_ids[-1]]

        unplaced_codes = [
            courses_by_id[cid].course_code
            if cid in courses_by_id
            else f"course_id={cid}"
            for cid in unplaced_courses
        ]

        unplaced_subgraph = conflict_graph.subgraph(unplaced_courses)
        unplaced_colours = (
            len(set(colour_conflict_graph_dsatur(unplaced_subgraph).values()))
            if unplaced_courses
            else 0
        )
        shortfall = max(
            1,
            num_dsatur_colours - num_defined_slots,
            unplaced_colours,
        )

        total_room_cap = sum(r.capacity for r in eligible_rooms)
        if self._is_enabled("E03", rule_states):
            for cid in course_ids:
                needed = student_counts.get(cid, 0)
                if needed > total_room_cap:
                    c_code = (
                        courses_by_id[cid].course_code
                        if cid in courses_by_id
                        else f"course_id={cid}"
                    )
                    reasons.append(
                        f"E03 Infeasibility: Course {c_code} (course_id={cid}) has "
                        f"student_count={needed}, which exceeds the total combined capacity "
                        f"({total_room_cap}) of all active eligible exam rooms."
                    )

        if num_dsatur_colours > num_defined_slots:
            reasons.append(
                f"E01/E05 Session Shortfall: Conflict graph requires at least "
                f"{num_dsatur_colours} exam sessions, but only {num_defined_slots} "
                f"exam_slots are defined (shortfall={shortfall} session(s)). "
                f"Unplaced courses: {unplaced_codes} (course_ids={unplaced_courses})."
            )

        if self._is_enabled("E02", rule_states):
            max_per_day = rule_states.get("E02", (True, MAX_EXAMS_PER_DAY_DEFAULT))[1]
            if max_per_day is None:
                max_per_day = MAX_EXAMS_PER_DAY_DEFAULT
            num_days = len({s.exam_date for s in exam_slots})
            max_possible_per_student = num_days * max_per_day
            courses_by_student_check: dict[str, list[int]] = defaultdict(list)
            for cid in course_ids:
                for st in sorted(course_students.get(cid, set())):
                    courses_by_student_check[st].append(cid)
            for st, st_cids in sorted(courses_by_student_check.items()):
                if len(st_cids) > max_possible_per_student:
                    st_codes = [
                        courses_by_id[c].course_code
                        if c in courses_by_id
                        else f"course_id={c}"
                        for c in st_cids
                    ]
                    reasons.append(
                        f"E02 Infeasibility: Student/cohort {st} is enrolled in "
                        f"{len(st_cids)} courses {st_codes}, exceeding the maximum "
                        f"possible {max_possible_per_student} exams across {num_days} "
                        f"exam day(s) (limit={max_per_day}/day)."
                    )

        if not reasons:
            reasons.append(
                f"Infeasible Exam Schedule: Cannot place all {len(course_ids)} courses into "
                f"{num_defined_slots} defined exam session(s) under E01–E05 "
                f"(shortfall={shortfall} session(s)). Unplaced courses: "
                f"{unplaced_codes} (course_ids={unplaced_courses})."
            )

        return shortfall, unplaced_courses, unplaced_codes, reasons

    def solve(self) -> ExamScheduleResult:
        """Execute the 4-step examination scheduling pipeline with hard (E01–E05) and soft (ES01–ES03) rules."""
        start_time = time.perf_counter()
        rule_states = self._enabled_rule_map()
        soft_weights = self._soft_rule_weights()
        es01_weight = soft_weights.get("ES01", 0)
        es02_weight = soft_weights.get("ES02", 0)
        es03_weight = soft_weights.get("ES03", 0)

        enforce_e02 = self._is_enabled("E02", rule_states)
        max_exams_per_day = rule_states.get("E02", (True, MAX_EXAMS_PER_DAY_DEFAULT))[1]
        if max_exams_per_day is None:
            max_exams_per_day = MAX_EXAMS_PER_DAY_DEFAULT
        enforce_e03 = self._is_enabled("E03", rule_states)

        student_counts = self.dataset.course_student_counts(term_id=self.term_id)
        course_students = self.dataset.course_students(term_id=self.term_id)
        course_batches = self.dataset.course_batches(term_id=self.term_id)
        course_ids = sorted(student_counts.keys())
        exam_slots = self._exam_slots_for_term()
        eligible_rooms = self._eligible_rooms()

        # Step 1: Build NetworkX conflict graph
        conflict_graph = build_conflict_graph(self.dataset, term_id=self.term_id)
        locked_slots, locked_rooms = self._extract_locked_exams()

        if not course_ids:
            elapsed = time.perf_counter() - start_time
            obj_score, max_score, soft_breakdown, soft_penalties = (
                self.evaluate_soft_constraints(
                    entries=[],
                    allocations=[],
                    soft_weights=soft_weights,
                )
            )
            schedule_meta = self._build_schedule_metadata("optimal", elapsed, obj_score)
            return ExamScheduleResult(
                status="optimal",
                schedule=schedule_meta,
                entries=[],
                room_allocations=[],
                run_time_s=elapsed,
                reasons=[],
                violations=[],
                shortfall=0,
                unplaced_courses=[],
                unplaced_course_codes=[],
                chromatic_number=0,
                used_cpsat_fallback=False,
                objective_score=obj_score,
                max_score=max_score,
                soft_penalties=soft_penalties,
                soft_breakdown=soft_breakdown,
            )

        # Step 2: Colour conflict graph with DSATUR and map colours to exam sessions
        dsatur_colouring = colour_conflict_graph_dsatur(conflict_graph)
        num_dsatur_colours = len(set(dsatur_colouring.values()))

        colour_groups = self._split_colour_classes_for_rooms(
            colouring=dsatur_colouring,
            student_counts=student_counts,
            eligible_rooms=eligible_rooms,
            enforce_e03=enforce_e03,
            es02_weight=es02_weight,
            es03_weight=es03_weight,
        )

        course_to_slot: dict[int, int] | None = None
        course_to_rooms: dict[int, list[tuple[int, int]]] | None = None
        used_cpsat = False
        solver_status: ExamSolverStatus = "optimal"

        if (
            not locked_slots
            and not locked_rooms
            and colour_groups is not None
            and len(colour_groups) <= len(exam_slots)
        ):
            mapped_slots = self._map_colour_groups_to_slots(
                colour_groups=colour_groups,
                exam_slots=exam_slots,
                course_students=course_students,
                course_batches=course_batches,
                enforce_e02=enforce_e02,
                max_exams_per_day=max_exams_per_day,
                es01_weight=es01_weight,
            )
            if mapped_slots is not None:
                # Step 4 for DSATUR mapping: Allocate rooms per session optimising ES02 & ES03
                by_slot: dict[int, list[int]] = defaultdict(list)
                for cid, slot_id in mapped_slots.items():
                    by_slot[slot_id].append(cid)

                dsatur_rooms: dict[int, list[tuple[int, int]]] = {}
                rooms_ok = True
                for _slot_id, slot_cids in sorted(by_slot.items()):
                    session_alloc = self.allocate_session_rooms(
                        course_ids=slot_cids,
                        student_counts=student_counts,
                        eligible_rooms=eligible_rooms,
                        enforce_capacity=enforce_e03,
                        es02_weight=es02_weight,
                        es03_weight=es03_weight,
                    )
                    if session_alloc is None:
                        rooms_ok = False
                        break
                    dsatur_rooms.update(session_alloc)

                if rooms_ok:
                    course_to_slot = mapped_slots
                    course_to_rooms = dsatur_rooms

        # Step 3: Fall back to exact CP-SAT step if DSATUR needed more sessions, failed E02/E03/E04, or had locked exams
        if course_to_slot is None or course_to_rooms is None:
            used_cpsat = True
            elapsed_so_far = time.perf_counter() - start_time
            remaining_s = max(1.0, self.time_limit_s - elapsed_so_far)
            cpsat_status, course_to_slot, course_to_rooms = self._solve_with_cpsat(
                course_ids=course_ids,
                exam_slots=exam_slots,
                eligible_rooms=eligible_rooms,
                conflict_graph=conflict_graph,
                student_counts=student_counts,
                course_students=course_students,
                course_batches=course_batches,
                rule_states=rule_states,
                remaining_time_s=remaining_s,
                soft_weights=soft_weights,
                locked_slots=locked_slots,
                locked_rooms=locked_rooms,
            )
            solver_status = cpsat_status

        if course_to_slot is None or course_to_rooms is None:
            elapsed = time.perf_counter() - start_time
            if solver_status == "unknown":
                return ExamScheduleResult(
                    status="unknown",
                    schedule=None,
                    entries=[],
                    room_allocations=[],
                    run_time_s=elapsed,
                    reasons=[
                        f"CP-SAT solver reached time limit ({self.time_limit_s:g}s) "
                        "without proving feasibility or infeasibility."
                    ],
                    violations=[],
                    shortfall=0,
                    unplaced_courses=[],
                    unplaced_course_codes=[],
                    chromatic_number=num_dsatur_colours,
                    used_cpsat_fallback=used_cpsat,
                    objective_score=None,
                    max_score=0,
                    soft_penalties={},
                    soft_breakdown={},
                )

            shortfall, unplaced_cids, unplaced_codes, reasons = (
                self._diagnose_infeasibility(
                    course_ids=course_ids,
                    exam_slots=exam_slots,
                    eligible_rooms=eligible_rooms,
                    conflict_graph=conflict_graph,
                    dsatur_colouring=dsatur_colouring,
                    student_counts=student_counts,
                    course_students=course_students,
                    rule_states=rule_states,
                )
            )
            return ExamScheduleResult(
                status="infeasible",
                schedule=None,
                entries=[],
                room_allocations=[],
                run_time_s=elapsed,
                reasons=reasons,
                violations=[],
                shortfall=shortfall,
                unplaced_courses=unplaced_cids,
                unplaced_course_codes=unplaced_codes,
                chromatic_number=num_dsatur_colours,
                used_cpsat_fallback=used_cpsat,
                objective_score=None,
                max_score=0,
                soft_penalties={},
                soft_breakdown={},
            )

        # Build ExamEntry and ExamRoomAllocation objects
        schedule_id = self._resolve_schedule_id()
        entries: list[ExamEntry] = []
        room_allocations: list[ExamRoomAllocation] = []
        next_alloc_id = 1

        for entry_idx, cid in enumerate(course_ids, start=1):
            slot_id = course_to_slot[cid]
            s_count = student_counts.get(cid, 0)
            entry_allocs: list[ExamRoomAllocation] = []
            for room_id, seats in course_to_rooms.get(cid, []):
                alloc = ExamRoomAllocation(
                    allocation_id=next_alloc_id,
                    exam_entry_id=entry_idx,
                    room_id=room_id,
                    seats_allocated=seats,
                )
                entry_allocs.append(alloc)
                room_allocations.append(alloc)
                next_alloc_id += 1

            entries.append(
                ExamEntry(
                    exam_entry_id=entry_idx,
                    schedule_id=schedule_id,
                    course_id=cid,
                    exam_slot_id=slot_id,
                    student_count=s_count,
                    is_locked=(cid in locked_slots),
                    is_manual_override=False,
                    room_allocations=tuple(entry_allocs),
                )
            )

        # Step 5: Validate every generated schedule through the independent ExamValidator (FR-7.7)
        validator = ExamValidator(constraints=self._constraints)
        violations = validator.validate(
            dataset=self.dataset,
            entries=entries,
            allocations=room_allocations,
            config_id=self.config_id,
        )
        elapsed = time.perf_counter() - start_time

        if violations:
            v_reasons = [
                f"Post-solve validator check failed ({v.rule_code}): {v.description}"
                for v in violations
            ]
            return ExamScheduleResult(
                status="infeasible",
                schedule=None,
                entries=[],
                room_allocations=[],
                run_time_s=elapsed,
                reasons=v_reasons,
                violations=violations,
                shortfall=0,
                unplaced_courses=[],
                unplaced_course_codes=[],
                chromatic_number=num_dsatur_colours,
                used_cpsat_fallback=used_cpsat,
                objective_score=None,
                max_score=0,
                soft_penalties={},
                soft_breakdown={},
            )

        obj_score, max_score, soft_breakdown, soft_penalties = (
            self.evaluate_soft_constraints(
                entries=entries,
                allocations=room_allocations,
                soft_weights=soft_weights,
            )
        )

        schedule_meta = self._build_schedule_metadata(solver_status, elapsed, obj_score)
        return ExamScheduleResult(
            status=solver_status,
            schedule=schedule_meta,
            entries=entries,
            room_allocations=room_allocations,
            run_time_s=elapsed,
            reasons=[],
            violations=[],
            shortfall=0,
            unplaced_courses=[],
            unplaced_course_codes=[],
            chromatic_number=num_dsatur_colours,
            used_cpsat_fallback=used_cpsat,
            objective_score=obj_score,
            max_score=max_score,
            soft_penalties=soft_penalties,
            soft_breakdown=soft_breakdown,
        )

    def _resolve_schedule_id(self) -> int:
        for sch in self.dataset.schedules:
            if sch.schedule_type == "Exam":
                return sch.schedule_id
        if self.dataset.schedules:
            return self.dataset.schedules[0].schedule_id
        return 1

    def _build_schedule_metadata(
        self,
        solver_status: str,
        run_seconds: float,
        objective_score: float = 100.0,
    ) -> Schedule:
        existing_exam_sch = None
        for sch in self.dataset.schedules:
            if sch.schedule_type == "Exam":
                existing_exam_sch = sch
                break
        if existing_exam_sch is not None:
            return Schedule(
                schedule_id=existing_exam_sch.schedule_id,
                term_id=existing_exam_sch.term_id,
                config_id=existing_exam_sch.config_id,
                schedule_type="Exam",
                version_no=existing_exam_sch.version_no,
                status="Generated",
                solver_status=solver_status,
                objective_score=objective_score,
                run_seconds=round(run_seconds, 6),
                generated_by=existing_exam_sch.generated_by,
                generated_at=existing_exam_sch.generated_at,
                approved_by=existing_exam_sch.approved_by,
                published_at=existing_exam_sch.published_at,
            )
        return Schedule(
            schedule_id=1,
            term_id=self.term_id if self.term_id is not None else 1,
            config_id=self.config_id if self.config_id is not None else 1,
            schedule_type="Exam",
            version_no=1,
            status="Generated",
            solver_status=solver_status,
            objective_score=objective_score,
            run_seconds=round(run_seconds, 6),
        )


def schedule_exams(
    dataset: TimetableDataset,
    time_limit_s: float | None = None,
    random_seed: int | None = None,
    config_id: int | None = None,
    term_id: int | None = None,
    soft_constraints: dict[str, BaseConstraint] | None = None,
) -> ExamScheduleResult:
    """Convenience function to run the hybrid examination scheduler on `dataset`."""
    scheduler = ExamScheduler(
        dataset=dataset,
        time_limit_s=time_limit_s,
        random_seed=random_seed,
        config_id=config_id,
        term_id=term_id,
        soft_constraints=soft_constraints,
    )
    return scheduler.solve()


generate_exam_schedule = schedule_exams
solve_exam_schedule = schedule_exams
