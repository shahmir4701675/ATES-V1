"""B003 enrollment graph/solver checks against hand-specified membership oracles.

All datasets are in memory. No solver/graph membership helper supplies expected
relationships or the independent checks on completed exam assignments.
"""
from collections import Counter
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest

from engine.constraints import E01StudentExamClash, E02DailyExamLimit
from engine.exam_scheduler import build_conflict_graph, schedule_exams
from engine.models import Enrollment, ExamEntry, load_dataset_from_json
from engine.validator import ExamValidator

ROOT = Path(__file__).resolve().parents[1]

# Offering rows: (course, batch, declared count, raw student IDs). Oracle rows:
# explicit/anonymous student witness -> the exact courses that witness takes.
CASES = [
    ("missing", [(1, 1, 2, []), (2, 1, 2, [])], {"batch:1": {1, 2}}),
    ("mixed", [(1, 1, 2, [11, 12]), (2, 1, 2, [])], {"student:11": {1, 2}, "student:12": {1, 2}, "batch:1": {2}}),
    ("partial", [(1, 1, 2, [11]), (2, 1, 2, [12])], {"student:11": {1, 2}, "student:12": {1, 2}, "batch:1": {1, 2}}),
    ("disjoint_electives", [(1, 1, 2, [11, 12]), (2, 1, 2, [21, 22])], {"student:11": {1}, "student:12": {1}, "student:21": {2}, "student:22": {2}}),
    ("cross_batch", [(1, 1, 2, [11, 12]), (2, 2, 2, [11, 21])], {"student:11": {1, 2}, "student:12": {1}, "student:21": {2}}),
    ("repeater", [(1, 1, 2, [11, 99]), (2, 2, 2, [21, 99])], {"student:11": {1}, "student:21": {2}, "student:99": {1, 2}}),
    ("duplicate_partial", [(1, 1, 2, [11, 11]), (2, 1, 2, [21, 22])], {"student:11": {1}, "student:21": {1, 2}, "student:22": {1, 2}, "batch:1": {1}}),
    ("unrelated_missing_batches", [(1, 1, 2, []), (2, 2, 2, [])], {"batch:1": {1}, "batch:2": {2}}),
    ("cross_batch_inference", [(1, 1, 1, [99]), (2, 1, 2, []), (3, 2, 1, [99])], {"student:99": {1, 2, 3}, "batch:1": {2}}),
    ("multiple_offerings", [(1, 1, 1, [11]), (1, 2, 1, [21]), (2, 2, 1, [])], {"student:11": {1}, "student:21": {1, 2}, "batch:2": {2}}),
    ("no_transitive_roster", [(1, 1, 1, [11]), (2, 1, 2, []), (2, 2, 1, [21]), (3, 2, 1, [22])], {"student:11": {1, 2}, "student:21": {2}, "student:22": {3}, "batch:1": {2}}),
    ("empty_offering", [(1, 1, 0, []), (2, 1, 1, [11])], {"student:11": {2}}),
]


def make_dataset(rows):
    ds = load_dataset_from_json(ROOT / "data/seed_exam.json")
    template = ds.course_offerings[0]
    ds.course_offerings = []
    ds.enrollments = []
    for oid, (course, batch, count, students) in enumerate(rows, 1):
        ds.course_offerings.append(replace(template, offering_id=oid, course_id=course, batch_id=batch, enrolled_count=count))
        for student in students:
            ds.enrollments.append(Enrollment(len(ds.enrollments) + 1, oid, student))
    ds.courses = [course for course in ds.courses if course.course_id in {row[0] for row in rows}]
    ds.exam_entries = []
    ds.exam_room_allocations = []
    ds.constraint_rules = [replace(rule, is_enabled=False) if rule.rule_type == "Soft" else rule for rule in ds.constraint_rules]
    return ds


def expected_edges(oracle):
    return {tuple(sorted(pair)) for courses in oracle.values() for pair in combinations(sorted(courses), 2)}


def assert_schedule_oracle(ds, entries, oracle, daily_limit=2):
    # Exact course completeness and E01/E02, computed only from test oracle rows.
    expected_courses = {off.course_id for off in ds.course_offerings}
    assert Counter(e.course_id for e in entries) == Counter({cid: 1 for cid in expected_courses})
    placements = {entry.course_id: entry.exam_slot_id for entry in entries}
    for courses in oracle.values():
        assert len({placements[cid] for cid in courses}) == len(courses)
        dates = Counter(ds.exam_slots_by_id[placements[cid]].exam_date for cid in courses)
        if daily_limit is not None:
            assert all(count <= daily_limit for count in dates.values())


@pytest.mark.parametrize("name,rows,oracle", CASES, ids=[case[0] for case in CASES])
def test_graph_matches_independent_oracle(name, rows, oracle):
    ds = make_dataset(rows)
    graph = build_conflict_graph(ds, term_id=1)
    assert {tuple(sorted(edge)) for edge in graph.edges} == expected_edges(oracle)
    for course in graph.nodes:
        assert set(graph.nodes[course]["students"]) == {person for person, courses in oracle.items() if course in courses}
    for left, right in graph.edges:
        witnesses = sorted(person for person, courses in oracle.items() if {left, right} <= courses)
        assert graph[left][right]["shared_students"] == witnesses
        assert graph[left][right]["shared_count"] == len(witnesses)


@pytest.mark.parametrize("name,rows,oracle", CASES[:-1], ids=[case[0] for case in CASES[:-1]])
@pytest.mark.parametrize("locked", [False, True], ids=["dsatur", "cpsat_locked"])
def test_generated_schedule_matches_independent_oracle(name, rows, oracle, locked):
    ds = make_dataset(rows)
    if locked:
        count = sum(off.enrolled_count for off in ds.course_offerings if off.course_id == 1)
        ds.exam_entries = [ExamEntry(1, 2, 1, 1, count, is_locked=True)]
    result = schedule_exams(ds, time_limit_s=10, random_seed=13)
    assert result.status in {"optimal", "feasible"}, result.reasons
    assert result.used_cpsat_fallback == locked
    assert_schedule_oracle(ds, result.entries, oracle)
    assert ExamValidator().validate(ds, result.entries, result.room_allocations, config_id=2) == []
    if locked:
        assert next(e for e in result.entries if e.course_id == 1).exam_slot_id == 1


@pytest.mark.parametrize("name,rows,oracle", CASES[:-1], ids=[case[0] for case in CASES[:-1]])
def test_validator_detects_oracle_edges_without_solver_helper(name, rows, oracle):
    ds = make_dataset(rows)
    entries = [ExamEntry(i, 2, cid, 1, 2) for i, cid in enumerate(sorted({r[0] for r in rows}), 1)]
    # Simulate the historical solver-helper failure. Validation must stand alone.
    with patch.object(type(ds), "course_students", return_value={}):
        violations = E01StudentExamClash().validate(ds, entries)
        complete_violations = ExamValidator().validate(ds, entries, [], config_id=2)
    assert {tuple(v.affected_entities["course_ids"]) for v in violations} == expected_edges(oracle)
    assert {tuple(v.affected_entities["course_ids"]) for v in complete_violations if v.rule_code == "E01"} == expected_edges(oracle)


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("count,limit,enabled,feasible", [(2, 2, True, True), (3, 2, True, False), (3, 3, True, True), (3, 2, False, True)])
def test_daily_limit_mixed_membership_both_paths(locked, count, limit, enabled, feasible):
    rows = [(1, 1, 2, [11, 12])] + [(course, 1, 2, []) for course in range(2, count + 1)]
    ds = make_dataset(rows)
    times = [("08:00", "09:00"), ("10:00", "11:00"), ("12:00", "13:00")]
    ds.exam_slots = [replace(slot, exam_date="2026-12-14", start_time=start, end_time=end) for slot, (start, end) in zip(ds.exam_slots, times)]
    for rule in ds.constraint_rules:
        if rule.rule_code == "E02":
            rule.param_value, rule.is_enabled = limit, enabled
        if rule.rule_code == "E01":
            rule.is_enabled = False  # Mandatory E01 remains active.
    if locked:
        ds.exam_entries = [ExamEntry(1, 2, 1, 1, 2, is_locked=True)]
    result = schedule_exams(ds, time_limit_s=10, random_seed=1)
    assert (result.status in {"optimal", "feasible"}) == feasible, result.reasons
    if feasible:
        oracle = {"student:11": set(range(1, count + 1)), "student:12": set(range(1, count + 1)), "batch:1": set(range(2, count + 1))}
        assert_schedule_oracle(ds, result.entries, oracle, limit if enabled else None)
    else:
        assert result.used_cpsat_fallback
        assert any("E02" in reason for reason in result.reasons)


def test_validator_daily_counts_do_not_depend_on_solver_membership():
    ds = make_dataset([(1, 1, 2, [11, 12]), (2, 1, 2, []), (3, 1, 2, [11])])
    ds.exam_slots = [replace(slot, exam_date="2026-12-14") for slot in ds.exam_slots[:3]]
    entries = [ExamEntry(i, 2, i, i, 2) for i in (1, 2, 3)]
    with patch.object(type(ds), "course_students", return_value={}):
        violations = E02DailyExamLimit().validate(ds, entries, param_value=2)
    assert {v.affected_entities["student_ref"] for v in violations} == {"student:11", "student:12"}
    assert all(v.affected_entities["exam_count"] == 3 for v in violations)
    assert E02DailyExamLimit().validate(ds, entries, param_value=3) == []


@pytest.mark.parametrize("locked", [False, True])
def test_e01_one_session_is_infeasible_even_when_disabled(locked):
    ds = make_dataset([(1, 1, 2, [11, 12]), (2, 1, 2, [])])
    ds.exam_slots = ds.exam_slots[:1]
    for rule in ds.constraint_rules:
        if rule.rule_code == "E01":
            rule.is_enabled = False
    if locked:
        ds.exam_entries = [ExamEntry(1, 2, 1, 1, 2, is_locked=True)]
    result = schedule_exams(ds, time_limit_s=10)
    assert result.status == "infeasible"
    assert result.entries == []
    assert result.used_cpsat_fallback


def test_duplicate_records_and_input_order_do_not_change_graph_or_counts():
    ds = make_dataset(CASES[1][1])
    expected = build_conflict_graph(ds, term_id=1)
    counts = ds.course_student_counts(1)
    ds.enrollments += [replace(enr, enrollment_id=enr.enrollment_id + 100) for enr in ds.enrollments]
    ds.enrollments.reverse()
    ds.course_offerings.reverse()
    ds.courses.reverse()
    actual = build_conflict_graph(ds, term_id=1)
    assert nx.node_link_data(actual, edges="edges") == nx.node_link_data(expected, edges="edges")
    assert ds.course_student_counts(1) == counts
    a = schedule_exams(ds, time_limit_s=10, random_seed=7)
    b = schedule_exams(ds, time_limit_s=10, random_seed=7)
    assert a.status in {"optimal", "feasible"}
    assert [(e.course_id, e.exam_slot_id) for e in a.entries] == [(e.course_id, e.exam_slot_id) for e in b.entries]


def test_other_term_enrollments_do_not_create_conflicts():
    ds = make_dataset(CASES[3][1])
    ds.course_offerings.append(replace(ds.course_offerings[0], offering_id=100, term_id=2))
    ds.enrollments.extend([Enrollment(100, 100, 21), Enrollment(101, 100, 22)])
    assert list(build_conflict_graph(ds, term_id=1).edges) == []
    assert ds.course_students(1)[1] == {"student:11", "student:12"}
    entries = [ExamEntry(i, 2, i, 1, 2) for i in (1, 2)]
    assert E01StudentExamClash().validate(ds, entries) == []
    assert E02DailyExamLimit().validate(ds, entries, param_value=1) == []


def test_sample_saved_schedule_is_valid_under_conservative_fallback():
    ds = load_dataset_from_json(ROOT / "data/seed_exam.json")
    oracle = {"student:9001": {1, 2, 3, 4, 5}, "batch:1": {1, 2, 3}, "batch:2": {1, 4, 5}}
    assert_schedule_oracle(ds, ds.exam_entries, oracle)
    assert ExamValidator().validate(ds, config_id=2) == []


def test_inactive_course_can_supply_batch_membership_evidence():
    ds = make_dataset([(1, 1, 2, []), (2, 1, 1, [99]), (3, 2, 1, [99])])
    ds.courses = [replace(course, is_active=False) if course.course_id == 2 else course for course in ds.courses]
    graph = build_conflict_graph(ds, term_id=1)
    assert set(graph.nodes) == {1, 3}
    assert set(graph.edges) == {(1, 3)}
    entries = [ExamEntry(i, 2, cid, 1, 2) for i, cid in enumerate((1, 3), 1)]
    with patch.object(type(ds), "course_students", return_value={}):
        assert len(E01StudentExamClash().validate(ds, entries)) == 1
