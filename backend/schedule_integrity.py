"""B004 immutable version context and publication eligibility foundations.

There is deliberately no publication HTTP endpoint here (B008). All decisions use
the independent engine validators, not saved conflict counts or solver assertions.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from importlib.metadata import version
from dataclasses import fields, is_dataclass
from functools import lru_cache
from types import UnionType
from typing import get_args, get_origin, get_type_hints, Union, Any
from threading import RLock
from types import SimpleNamespace

from sqlalchemy import event, insert, select, update, inspect, text
from sqlalchemy.orm import Session

from backend.models import Schedule, ScheduleSnapshot, ScheduleInputState, ConflictLog, ScheduleValidationReceipt
from engine.models import TimetableDataset
from engine.validator import TimetableValidator, ExamValidator

POLICY = "ates-b001-b002-b003-v1"


def implementation_identity():
    root = Path(__file__).resolve().parents[1] / "engine"
    files = ("models.py", "constraints.py", "validator.py", "weekly_grid.py", "exam_membership_validation.py", "timetable_solver.py", "exam_scheduler.py", "execution.py")
    return {"engine": {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files},
            "dependencies": {name: version(name) for name in ("ortools", "networkx")}}


@lru_cache(maxsize=None)
def _field_types(cls):
    hints = get_type_hints(cls)
    return {field.name: hints[field.name] for field in fields(cls)}


def _typed(value, expected):
    """Snapshot JSON is a strict persisted contract, not coercible request data."""
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        return any(_typed(value, item) for item in args)
    if origin is list:
        return isinstance(value, list) and all(_typed(item, args[0]) for item in value)
    if is_dataclass(expected):
        types = _field_types(expected)
        return isinstance(value, dict) and set(value) == set(types) and all(_typed(value[key], hint) for key, hint in types.items())
    if expected is float:
        return type(value) in (int, float)
    if expected is Any:
        return True
    return type(value) is expected


class SnapshotIntegrityError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def lock_inputs(session):
    result = session.execute(update(ScheduleInputState).where(ScheduleInputState.state_id == 1).values(revision=ScheduleInputState.revision))
    if result.rowcount != 1:
        raise SnapshotIntegrityError("B004 input-state migration is required.")


def make_context(dataset, term_id, schedule_type, config_id, *, source_schedule_id=None, time_limit_override=None, random_seed_override=None):
    data = deepcopy(dataset.to_dict())
    data["academic_terms"] = [t for t in data["academic_terms"] if t["term_id"] == term_id]
    data["course_offerings"] = [o for o in data["course_offerings"] if o["term_id"] == term_id]
    for key in ("time_slots", "exam_slots"):
        data[key] = [row for row in data[key] if row["term_id"] == term_id]
    ids = {o["offering_id"] for o in data["course_offerings"]}
    for key, attr in (("courses", "course_id"), ("batches", "batch_id"), ("instructors", "instructor_id")):
        needed = {o[attr] for o in data["course_offerings"]}
        data[key] = [r for r in data[key] if r[attr] in needed]
    departments = {row["department_id"] for key in ("courses", "batches", "instructors") for row in data[key]}
    data["departments"] = [row for row in data["departments"] if row["department_id"] in departments]
    instructors = {row["instructor_id"] for row in data["instructors"]}
    slots = {row["slot_id"] for row in data["time_slots"]}
    data["instructor_availability"] = [row for row in data["instructor_availability"] if row["instructor_id"] in instructors and row["slot_id"] in slots]
    data["enrollments"] = [e for e in data["enrollments"] if e["offering_id"] in ids]
    data["scheduling_configs"] = [c for c in data["scheduling_configs"] if c["config_id"] == config_id and c["term_id"] == term_id and c["schedule_type"] == schedule_type]
    if len(data["academic_terms"]) != 1 or len(data["scheduling_configs"]) != 1:
        raise SnapshotIntegrityError("Input context has an inconsistent term, type or configuration.")
    data["constraint_rules"] = [r for r in data["constraint_rules"] if r["config_id"] == config_id]
    data["schedules"] = []
    previous_timetable = sorted([e for e in data["timetable_entries"] if source_schedule_id and e["schedule_id"] == source_schedule_id],key=canonical) if schedule_type == "Timetable" else []
    data["timetable_entries"] = [e for e in data["timetable_entries"] if source_schedule_id and e["schedule_id"] == source_schedule_id and e["is_locked"]]
    data["exam_entries"] = [e for e in data["exam_entries"] if source_schedule_id and e["schedule_id"] == source_schedule_id and e["is_locked"]]
    locked_exam_ids = {e["exam_entry_id"] for e in data["exam_entries"]}
    data["exam_room_allocations"] = [a for a in data["exam_room_allocations"] if a["exam_entry_id"] in locked_exam_ids]
    if schedule_type == "Timetable":
        data["enrollments"], data["exam_slots"], data["exam_entries"], data["exam_room_allocations"] = [], [], [], []
    elif schedule_type == "Exam":
        data["time_slots"], data["instructor_availability"], data["timetable_entries"] = [], [], []
    else:
        raise SnapshotIntegrityError("Unsupported schedule type.")
    for key, rows in data.items():
        data[key] = sorted(rows, key=canonical)
    return dict(format_version=1, policy=POLICY, implementation=implementation_identity(), term_id=term_id, schedule_type=schedule_type,
                config_id=config_id, source_schedule_id=source_schedule_id,
                time_limit_override=time_limit_override, random_seed_override=random_seed_override, previous_timetable=previous_timetable, dataset=data)


def capture_inputs(session, term_id, schedule_type, config_id, **options):
    from backend.adapter import load_term_dataset
    lock_inputs(session)
    from backend.snapshot_schema import SOURCES
    # Re-read committed source values even when a caller reuses an identity map.
    for obj in list(session.identity_map.values()):
        if getattr(obj, "__tablename__", "") in set(SOURCES) | {"timetable_entries", "exam_entries", "exam_room_allocations"}:
            if obj in session.dirty:
                raise SnapshotIntegrityError("Flush source changes before capturing inputs.")
            session.expire(obj)
    source_id = options.get("source_schedule_id")
    dataset = load_term_dataset(session, term_id, config_id=config_id, schedule_id=source_id,
                                include_existing_schedules=source_id is not None, use_snapshot=False)
    return make_context(dataset, term_id, schedule_type, config_id, **options)


def check_fresh(session, context):
    fresh = capture_inputs(session, context["term_id"], context["schedule_type"], context["config_id"],
                           **{k: context[k] for k in ("source_schedule_id", "time_limit_override", "random_seed_override")})
    if digest(fresh) != digest(context):
        raise SnapshotIntegrityError("Scheduling inputs changed during generation; regenerate using current data.")


_snapshot_cache_lock = RLock()


def decode_snapshot(row, schedule):
    """Reuse verified immutable inputs, never roles, live entries or validator results.

    Every byte, persisted scope/hash and reader identity is part of the key.
    Callers receive independent copies; publication/output validation stays live.
    """
    raw = getattr(row, 'inputs_json', None)
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 2_000_000:
        return _decode_snapshot_uncached(row, schedule)
    compatibility = Path(__file__).parent / 'snapshot_compatibility'
    try:
        key = (
            row.inputs_json, row.input_hash, row.format_version, row.term_id, row.schedule_type,
            schedule.term_id, schedule.schedule_type, schedule.config_id, POLICY,
            canonical(implementation_identity()),
            tuple((compatibility / name).read_bytes() for name in ('b004_to_b005.json', 'b005_to_batch1.json')),
        )
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise SnapshotIntegrityError(f"Invalid version snapshot reader: {exc}") from exc
    # Single-flight cold decoding prevents simultaneous requests duplicating the
    # same expensive normalization. Cache hits hold this lock only for lookup.
    with _snapshot_cache_lock:
        dataset = _cached_snapshot(key)
    return deepcopy(dataset)


@lru_cache(maxsize=8)
def _cached_snapshot(key):
    raw, checksum, fmt, term, kind, schedule_term, schedule_kind, config, *_reader = key
    row = SimpleNamespace(inputs_json=raw, input_hash=checksum, format_version=fmt, term_id=term, schedule_type=kind)
    schedule = SimpleNamespace(term_id=schedule_term, schedule_type=schedule_kind, config_id=config)
    return _decode_snapshot_uncached(row, schedule)


def _decode_snapshot_uncached(row, schedule):
    try:
        context = json.loads(row.inputs_json)
        if any(type(context[key]) is not int for key in ("format_version", "term_id", "config_id")):
            raise ValueError("Snapshot scope identifiers must be integers.")
        if row.format_version != 1 or context["format_version"] != 1 or context["policy"] != POLICY:
            raise ValueError("Unsupported snapshot format/policy.")
        if digest(context) != row.input_hash:
            raise ValueError("Snapshot checksum mismatch.")
        if (row.term_id, row.schedule_type, context["term_id"], context["schedule_type"], context["config_id"]) != (schedule.term_id, schedule.schedule_type, schedule.term_id, schedule.schedule_type, schedule.config_id):
            raise ValueError("Snapshot scope mismatch.")
        data = context["dataset"]
        if not _typed(data, TimetableDataset):
            raise ValueError("Snapshot fields have invalid or missing types.")
        required = set(TimetableDataset().to_dict())
        if set(data) != required or any(not isinstance(rows, list) for rows in data.values()):
            raise ValueError("Incomplete snapshot dataset.")
        dataset = TimetableDataset.from_dict(data)
        normalization_dataset = dataset
        if "previous_timetable" in context:
            from engine.models import TimetableEntry
            if not _typed(context["previous_timetable"],list[TimetableEntry]):
                raise ValueError("Invalid previous timetable context.")
            normalization_dataset = deepcopy(dataset)
            normalization_dataset.timetable_entries = [TimetableEntry(**entry) for entry in context["previous_timetable"]]
        # Re-normalization detects forged embedded config/term/type bindings too.
        normalized = make_context(normalization_dataset, schedule.term_id, schedule.schedule_type, schedule.config_id,
                        **{k: context[k] for k in ("source_schedule_id", "time_limit_override", "random_seed_override")})
        if normalized["implementation"] != context.get("implementation"):
            # Only exact reviewed reader transitions: preserve frozen inputs,
            # hashes and receipts, and validate the original slot definitions.
            predecessor = context.get("implementation")
            for filename in ("b004_to_b005.json", "b005_to_batch1.json"):
                compatibility = json.loads((Path(__file__).parent / "snapshot_compatibility" / filename).read_text(encoding="utf-8"))
                if predecessor == compatibility["source"]: predecessor=compatibility["target"]
            if predecessor == normalized["implementation"]:
                normalized["implementation"] = context["implementation"]
                if "previous_timetable" not in context: normalized.pop("previous_timetable")
        if normalized != context:
            raise ValueError("Inconsistent snapshot dataset.")
        return dataset
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise SnapshotIntegrityError(f"Invalid version snapshot: {exc}") from exc


def validate_version(dataset, schedule_type, config_id):
    # Require referenced identities, not merely whichever rule happens to inspect them.
    if schedule_type == "Timetable":
        for entry in dataset.timetable_entries:
            offering = dataset.offerings_by_id.get(entry.offering_id)
            if (offering is None or entry.room_id not in dataset.rooms_by_id or entry.slot_id not in dataset.slots_by_id
                    or entry.instructor_id not in dataset.instructors_by_id or entry.batch_id not in dataset.batches_by_id
                    or (offering.instructor_id, offering.batch_id) != (entry.instructor_id, entry.batch_id)):
                raise SnapshotIntegrityError("Version contains inconsistent timetable references.")
            if not dataset.rooms_by_id[entry.room_id].is_active or not dataset.instructors_by_id[entry.instructor_id].is_active or not dataset.batches_by_id[entry.batch_id].is_active:
                raise SnapshotIntegrityError("Version references an inactive scheduling resource.")
        violations = TimetableValidator().validate(dataset, config_id=config_id)
    else:
        if any(e.exam_slot_id not in dataset.exam_slots_by_id or e.course_id not in dataset.courses_by_id for e in dataset.exam_entries):
            raise SnapshotIntegrityError("Version contains inconsistent exam references.")
        if any(a.room_id not in dataset.rooms_by_id for a in dataset.resolve_exam_allocations()):
            raise SnapshotIntegrityError("Version contains an unknown allocation room.")
        if any(not dataset.rooms_by_id[a.room_id].is_active for a in dataset.resolve_exam_allocations()):
            raise SnapshotIntegrityError("Version references an inactive exam room.")
        violations = ExamValidator().validate(dataset, config_id=config_id)
    hard = [v for v in violations if v.severity == "Hard"]
    if hard:
        raise SnapshotIntegrityError("Version failed independent validation: " + "; ".join(v.description for v in hard))


def store_snapshot(session, schedule, context):
    if schedule.status != "Generated":
        raise SnapshotIntegrityError("Only a Generated version may establish a new authoritative context.")
    if session.get(ScheduleSnapshot, schedule.schedule_id) is not None:
        raise SnapshotIntegrityError("An existing immutable version context cannot be replaced.")
    session.execute(insert(ScheduleSnapshot).values(schedule_id=schedule.schedule_id, term_id=schedule.term_id,
                    schedule_type=schedule.schedule_type, format_version=1, input_hash=digest(context), inputs_json=canonical(context)))


def hydrate_snapshot(session, row, schedule):
    """Load only frozen master inputs plus this version's persisted entry rows."""
    from dataclasses import fields
    from backend.models import TimetableEntry, ExamEntry, ExamRoomAllocation
    from engine import models as domain
    if schedule.status in {"Published", "Archived"}:
        receipt = session.get(ScheduleValidationReceipt, schedule.schedule_id)
        if receipt is None or receipt.input_hash != row.input_hash:
            raise SnapshotIntegrityError("Official version validation receipt is missing or inconsistent.")
    dataset = decode_snapshot(row, schedule)

    def convert(cls, obj):
        return cls(**{field.name: getattr(obj, field.name) for field in fields(cls) if hasattr(obj, field.name)})

    dataset.schedules = [convert(domain.Schedule, schedule)]
    dataset.timetable_entries = [convert(domain.TimetableEntry, e) for e in session.scalars(select(TimetableEntry).execution_options(populate_existing=True).where(TimetableEntry.schedule_id == schedule.schedule_id).order_by(TimetableEntry.entry_id))]
    dataset.exam_entries = [convert(domain.ExamEntry, e) for e in session.scalars(select(ExamEntry).execution_options(populate_existing=True).where(ExamEntry.schedule_id == schedule.schedule_id).order_by(ExamEntry.exam_entry_id))]
    dataset.exam_room_allocations = [convert(domain.ExamRoomAllocation, a) for a in session.scalars(select(ExamRoomAllocation).execution_options(populate_existing=True).join(ExamEntry).where(ExamEntry.schedule_id == schedule.schedule_id).order_by(ExamRoomAllocation.allocation_id))]
    for entry in dataset.exam_entries:
        entry.room_allocations = [a for a in dataset.exam_room_allocations if a.exam_entry_id == entry.exam_entry_id]
    validate_version(dataset, schedule.schedule_type, schedule.config_id)
    return dataset


def finish_version(session, schedule, context):
    from types import SimpleNamespace
    if context is None:
        raise SnapshotIntegrityError("Successful persistence requires the original captured input context.")
    if (context["term_id"], context["schedule_type"], context["config_id"]) != (schedule.term_id, schedule.schedule_type, schedule.config_id):
        raise SnapshotIntegrityError("Result/input scope mismatch.")
    check_fresh(session, context)
    row = SimpleNamespace(format_version=1, term_id=schedule.term_id, schedule_type=schedule.schedule_type,
                          inputs_json=canonical(context), input_hash=digest(context))
    hydrate_snapshot(session, row, schedule)
    store_snapshot(session, schedule, context)


def publication_eligibility(session, schedule_id):
    """Stable independent review foundation; does not publish/archive or grant roles."""
    from backend.adapter import load_term_dataset
    lock_inputs(session)
    sch = session.get(Schedule, schedule_id)
    persisted_status = session.scalar(select(Schedule.status).where(Schedule.schedule_id == schedule_id))
    if sch is None or sch.status != "Generated" or persisted_status != "Generated":
        raise SnapshotIntegrityError("Only Generated versions are eligible for publication.")
    dataset = load_term_dataset(session, sch.term_id, config_id=sch.config_id, schedule_id=sch.schedule_id)
    validate_version(dataset, sch.schedule_type, sch.config_id)
    if session.scalar(select(ConflictLog.conflict_id).where(ConflictLog.schedule_id == schedule_id, ConflictLog.severity == "Hard", ConflictLog.is_resolved.is_(False)).limit(1)):
        raise SnapshotIntegrityError("Unresolved hard conflicts prevent publication.")
    if session.get(ScheduleSnapshot, schedule_id) is None:
        # A legacy Generated version may establish context only at explicit review,
        # while independently valid. Never reconstruct an already official version.
        context = capture_inputs(session, sch.term_id, sch.schedule_type, sch.config_id)
        store_snapshot(session, sch, context)
    snapshot = session.get(ScheduleSnapshot, schedule_id)
    # Both supported dialects implement ON CONFLICT; no mutable input snapshot.
    session.execute(text(
        "INSERT INTO schedule_validation_receipts(schedule_id,input_hash) VALUES(:sid,:hash) "
        "ON CONFLICT(schedule_id) DO UPDATE SET input_hash=excluded.input_hash, reviewed_at=CURRENT_TIMESTAMP"
    ), {"sid": schedule_id, "hash": snapshot.input_hash})
    return dataset


@event.listens_for(Session, "before_flush")
def _review_official_transition(session, flush_context, instances):
    for sch in list(session.dirty):
        if not isinstance(sch, Schedule):
            continue
        change = inspect(sch).attrs.status.history
        if change.has_changes() and sch.status == "Published":
            if not change.deleted or change.deleted[0] != "Generated":
                raise SnapshotIntegrityError("Publication requires a Generated version.")
            # Simultaneous source/entry mutations must be flushed and reviewed first.
            from backend.snapshot_schema import SOURCES
            protected = set(SOURCES) | {"timetable_entries", "exam_entries", "exam_room_allocations"}
            if any(getattr(obj, "__tablename__", "") in protected for obj in session.new | session.deleted | session.dirty):
                raise SnapshotIntegrityError("Flush input/entry changes before publication review.")
            sch.status = "Generated"
            try:
                publication_eligibility(session, sch.schedule_id)
            finally:
                sch.status = "Published"
