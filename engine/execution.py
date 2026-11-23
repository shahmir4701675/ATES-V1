"""Shared monotonic budget; API supervisors additionally preempt whole processes."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from dataclasses import replace
import time

_deadline = ContextVar("ates_deadline", default=None)


class DeadlineExceeded(RuntimeError):
    pass


def check_deadline():
    end = _deadline.get()
    if end is not None and time.monotonic() >= end:
        raise DeadlineExceeded("The end-to-end generation deadline expired.")


def remaining_seconds(cap):
    check_deadline()
    end = _deadline.get()
    remaining = float(cap) if end is None else min(float(cap), end-time.monotonic())
    if remaining <= 0:
        raise DeadlineExceeded("The end-to-end generation deadline expired.")
    return remaining


def search_seconds(cap):
    # Leave time for extraction, independent validation and atomic persistence;
    # a feasible search at the hard cutoff must not consume their whole budget.
    remaining=remaining_seconds(cap)
    return remaining-min(2.0,remaining*.15)


@contextmanager
def budget_until(end):
    current = _deadline.get()
    token = _deadline.set(min(current,end) if current is not None else end)
    try:
        check_deadline()
        yield
        check_deadline()
    finally:
        _deadline.reset(token)


def bounded(kind):
    def decorate(fn):
        spec = signature(fn)
        @wraps(fn)
        def run(*args,**kwargs):
            start = time.monotonic()
            bound = spec.bind(*args,**kwargs); bound.apply_defaults()
            owner = args[0]
            if kind == "timetable":
                values = bound.arguments
                dataset = values["dataset"]
                term = owner._resolve_term_id(dataset,values["term_id"])
                _, configured, _ = owner._resolve_config(dataset,values["config_id"],term)
                limit = values["time_limit_s"] if values["time_limit_s"] is not None else values["time_limit"]
                limit = configured if limit is None else limit
            else:
                limit = owner.time_limit_s
            try:
                with budget_until(start+float(limit)):
                    result = fn(*args,**kwargs)
                elapsed = time.monotonic()-start
                if kind == "timetable":
                    record=replace(result.schedule_record,run_seconds=elapsed) if result.schedule_record else None
                    return replace(result,run_time=elapsed,schedule_record=record)
                record=replace(result.schedule,run_seconds=elapsed) if result.schedule else None
                return replace(result,run_time_s=elapsed,schedule=record)
            except DeadlineExceeded as exc:
                elapsed = time.monotonic()-start
                if kind == "timetable":
                    from engine.timetable_solver import TimetableSolveResult
                    return TimetableSolveResult([],"unknown",elapsed,reasons=[str(exc)])
                from engine.exam_scheduler import ExamScheduleResult
                return ExamScheduleResult("unknown",None,[],[],elapsed,reasons=[str(exc)])
        return run
    return decorate
