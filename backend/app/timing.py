"""작업의 소요 시간과 병렬 단계의 실행 시간을 기록한다."""

import json
import logging
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from threading import Lock
from time import monotonic

logger = logging.getLogger("uvicorn.error").getChild(__name__)
_current: ContextVar["JobTiming | None"] = ContextVar("job_timing", default=None)


class JobTiming:
    def __init__(self):
        self.status = "failed"
        self._intervals: dict[str, list[tuple[float, float, bool]]] = defaultdict(list)
        self._lock = Lock()

    def add(self, name: str, start: float, end: float, failed: bool) -> None:
        with self._lock:
            self._intervals[name].append((start, end, failed))

    def summary(self) -> dict[str, dict[str, int | float]]:
        result = {}
        for name, intervals in sorted(self._intervals.items()):
            busy = total = longest = previous_end = 0.0
            for start, end, _ in sorted(intervals):
                duration = end - start
                total += duration
                longest = max(longest, duration)
                # 같은 단계의 병렬 호출이 겹치는 시간은 한 번만 센다.
                busy += max(0.0, end - max(start, previous_end))
                previous_end = max(previous_end, end)
            result[name] = {
                "calls": len(intervals),
                "failed": sum(failed for _, _, failed in intervals),
                "busy_s": round(busy, 3),
                "sum_s": round(total, 3),
                "max_s": round(longest, 3),
            }
        return result


@contextmanager
def job_timing(kind: str, analysis_id: str):
    timing = JobTiming()
    token = _current.set(timing)
    started = monotonic()
    try:
        yield timing
    finally:
        elapsed = monotonic() - started
        _current.reset(token)
        logger.info(
            "analysis.timing_summary analysis_id=%s kind=%s status=%s elapsed_s=%.3f stages=%s",
            analysis_id, kind, timing.status, elapsed, json.dumps(timing.summary(), separators=(",", ":")),
        )


@contextmanager
def measure(name: str):
    timing = _current.get()
    if timing is None:
        yield
        return
    started = monotonic()
    failed = True
    try:
        yield
        failed = False
    finally:
        timing.add(name, started, monotonic(), failed)


def submit_timed(executor, func, *args):
    """작업별 계측 정보를 자식 스레드로 이어 준다."""
    return executor.submit(copy_context().run, func, *args)


def run_timed_job(kind: str, analysis_id: str, func, *args) -> None:
    with job_timing(kind, analysis_id) as timing:
        if func(*args):
            timing.status = "done"
