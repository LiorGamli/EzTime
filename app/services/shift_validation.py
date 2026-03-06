from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models import AttendanceEvent


def _to_interval(work_date: date, start: time, end: time) -> Tuple[datetime, datetime]:
    """
    Convert (work_date, start_time, end_time) into a datetime interval.

    Rule:
      - If end < start => crosses midnight => end is next day.
      - If end == start => invalid (handled before calling).
    """
    start_dt = datetime.combine(work_date, start)
    end_dt = datetime.combine(work_date, end)
    if end_dt < start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _hours_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600.0


def _overlaps(a: Tuple[datetime, datetime], b: Tuple[datetime, datetime]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


def _merge_intervals(intervals: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for cur_start, cur_end in intervals[1:]:
        last_start, last_end = merged[-1]
        if cur_start <= last_end:  # overlaps or touches
            merged[-1] = (last_start, max(last_end, cur_end))
        else:
            merged.append((cur_start, cur_end))
    return merged


def validate_new_shift(
    db: Session,
    employee_id: str,
    work_date: date,
    start_time: time,
    end_time: time,
    *,
    max_shift_hours: float = 15.0,
    max_day_hours: float = 15.0,
    exclude_shift_id: int | None = None,
) -> None:
    """
    Validations:
      1) start_time != end_time
      2) duration <= max_shift_hours (handles cross-midnight)
      3) no overlap with existing shifts for same employee+work_date
      4) total unique hours per day (after merge) <= max_day_hours
    Raises ValueError with a user-friendly message.
    """
    if start_time == end_time:
        raise ValueError("Start time and end time cannot be equal.")

    new_interval = _to_interval(work_date, start_time, end_time)
    new_duration = _hours_between(*new_interval)

    if new_duration <= 0:
        raise ValueError("Invalid shift duration.")

    # Cross-midnight is allowed ONLY if duration remains reasonable.
    if new_duration > max_shift_hours:
        raise ValueError(f"Shift duration exceeds {max_shift_hours:.0f} hours. Please verify input.")

    # Fetch existing shifts for that employee/date (exclude current shift when editing)
    q = (
        db.query(AttendanceEvent)
        .filter(AttendanceEvent.employee_id == employee_id, AttendanceEvent.work_date == work_date)
    )
    if exclude_shift_id is not None:
        q = q.filter(AttendanceEvent.id != exclude_shift_id)

    existing = q.all()

    existing_intervals: List[Tuple[datetime, datetime]] = []
    for e in existing:
        # ignore corrupted rows safely
        if e.start_time == e.end_time:
            continue

        iv = _to_interval(work_date, e.start_time, e.end_time)
        existing_intervals.append(iv)

        if _overlaps(new_interval, iv):
            raise ValueError("Shift overlaps with an existing shift for this employee/day.")

    # Daily cap check using merged (unique hours only)
    all_intervals = existing_intervals + [new_interval]
    merged = _merge_intervals(all_intervals)
    total_unique_hours = sum(_hours_between(a, b) for a, b in merged)

    if total_unique_hours > max_day_hours:
        raise ValueError(f"Total work hours for the day exceed {max_day_hours:.0f} hours. Please verify input.")
