"""Fixed-length weekly grid invariants, independent of the API and CP-SAT.

Intervals are local, minute-aligned, half-open [start, end) windows. Slot indexes
are positive/unique per weekday and must follow clock order; gaps are allowed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import time
import re
from typing import Any, Iterable


def clock_minutes(value: str | time) -> int:
    """Parse a local 24-hour HH:MM[:00] clock without truncation or rollover."""
    if isinstance(value, time):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Weekly times must be local and aligned to whole minutes.")
        return value.hour * 60 + value.minute
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}(?::00)?", value.strip()):
        raise ValueError("Expected a local 24-hour time HH:MM or HH:MM:00.")
    hour, minute = map(int, value.strip().split(":")[:2])
    if hour > 23 or minute > 59:
        raise ValueError("Hours must be 00-23 and minutes 00-59; midnight rollover is not allowed.")
    return hour * 60 + minute


def slot_interval(slot: Any) -> tuple[int, int]:
    """Reject empty, reversed and cross-midnight intervals rather than guessing 60m."""
    start, end = clock_minutes(slot.start_time), clock_minutes(slot.end_time)
    if end <= start:
        raise ValueError("end_time must be after start_time on the same day; cross-midnight slots are not allowed.")
    return start, end


@dataclass(frozen=True)
class GridIssue:
    kind: str
    description: str
    slot_ids: tuple[int, ...] = ()
    term_id: int | None = None


def validate_weekly_grid(
    slots: Iterable[Any], *, allow_unassigned_ids: bool = False,
    expected_duration_minutes: int | None = None,
) -> list[GridIssue]:
    """Check an entire candidate grid, including blocked and unscheduled slots."""
    issues: list[GridIssue] = []
    by_term: dict[int, list[tuple[Any, int, int]]] = defaultdict(list)
    ids: set[int] = set()
    indexes: set[tuple[int, int, int]] = set()
    for slot in slots:
        slot_id = slot.slot_id
        ref = (slot_id,) if isinstance(slot_id, int) else ()
        term_id = slot.term_id
        if not isinstance(term_id, int) or isinstance(term_id, bool) or term_id <= 0:
            issues.append(GridIssue("term", "term_id must be a positive integer.", ref))
            continue
        if not (allow_unassigned_ids and slot_id is None):
            if not isinstance(slot_id, int) or isinstance(slot_id, bool) or slot_id <= 0:
                issues.append(GridIssue("slot_id", "slot_id must be a positive integer.", ref, term_id))
            elif slot_id in ids:
                issues.append(GridIssue("duplicate_id", f"Duplicate slot_id={slot_id}.", ref, term_id))
            if isinstance(slot_id, int):
                ids.add(slot_id)
        day, index = slot.day_of_week, slot.slot_index
        if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 7:
            issues.append(GridIssue("weekday", "day_of_week must be an integer from 1 to 7.", ref, term_id))
            continue
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= 32767:
            issues.append(GridIssue("index", "slot_index must be a positive SMALLINT (1-32767).", ref, term_id))
            continue
        key = (term_id, day, index)
        if key in indexes:
            issues.append(GridIssue("duplicate_index", f"Duplicate slot_index={index} on weekday={day}.", ref, term_id))
        indexes.add(key)
        try:
            start, end = slot_interval(slot)
        except (ValueError, TypeError) as exc:
            issues.append(GridIssue("interval", str(exc), ref, term_id))
            continue
        by_term[term_id].append((slot, start, end))
    for term_id, rows in by_term.items():
        duration = expected_duration_minutes if expected_duration_minutes is not None else rows[0][2] - rows[0][1]
        for slot, start, end in rows:
            if end - start != duration:
                issues.append(GridIssue("duration", f"All slots in term_id={term_id} must have the configured duration of {duration} minutes.", (slot.slot_id,) if slot.slot_id is not None else (), term_id))
        days: dict[int, list[tuple[Any, int, int]]] = defaultdict(list)
        for row in rows:
            days[row[0].day_of_week].append(row)
        for day, daily in days.items():
            ordered = sorted(daily, key=lambda row: row[0].slot_index)
            if any(left[1] > right[1] for left, right in zip(ordered, ordered[1:])):
                issues.append(GridIssue("order", f"Slot indexes must follow chronological order on weekday={day}.", term_id=term_id))
            chronological = sorted(daily, key=lambda row: row[1])
            for position, (left, start, end) in enumerate(chronological):
                for right, next_start, next_end in chronological[position + 1:]:
                    if next_start >= end:
                        break
                    if start < next_end:
                        refs = tuple(s.slot_id for s in (left, right) if s.slot_id is not None)
                        issues.append(GridIssue("overlap", f"Overlapping weekly slots on weekday={day}: indexes {left.slot_index} and {right.slot_index}.", refs, term_id))
    return issues


def overlap_windows(slots: Iterable[Any]) -> list[list[Any]]:
    """CP-SAT occupancy cliques. A chain of overlaps is not one exclusive window."""
    days: dict[tuple[int, int], list[tuple[Any, int, int]]] = defaultdict(list)
    for slot in slots:
        start, end = slot_interval(slot)
        days[(slot.term_id, slot.day_of_week)].append((slot, start, end))
    windows: list[list[Any]] = []
    for key in sorted(days):
        daily = days[key]
        seen: set[tuple[int, ...]] = set()
        for point in sorted({row[1] for row in daily}):
            active = sorted((s for s, start, end in daily if start <= point < end), key=lambda s: s.slot_id)
            signature = tuple(slot.slot_id for slot in active)
            if signature not in seen:
                windows.append(active)
                seen.add(signature)
    return windows
