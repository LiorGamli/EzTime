from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Tuple

NIGHT_START = time(22, 0)
NIGHT_END = time(6, 0)

@dataclass
class Shift:
    start_time: time
    end_time: time
    role_name: str
    company_name: str

def _shift_datetimes(work_date: date, s: Shift) -> Tuple[datetime, datetime]:
    """
    Assumption for POC:
    If end_time < start_time => shift crosses midnight; we attach the end to next day.
    All hours are still attributed to work_date (shift-based day).
    """
    start_dt = datetime.combine(work_date, s.start_time)
    end_dt = datetime.combine(work_date, s.end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt

def _overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)

def compute_total_hours(work_date: date, shifts: List[Shift]) -> float:
    total_minutes = 0
    for s in shifts:
        start_dt, end_dt = _shift_datetimes(work_date, s)
        total_minutes += int((end_dt - start_dt).total_seconds() // 60)
    return total_minutes / 60.0

def compute_night_hours(work_date: date, shifts: List[Shift]) -> float:
    """
    Night window is 22:00-06:00 (spans midnight).
    We calculate overlap with two windows:
      [work_date 22:00, work_date+1 06:00]
    """
    night_start_dt = datetime.combine(work_date, NIGHT_START)
    night_end_dt = datetime.combine(work_date + timedelta(days=1), NIGHT_END)

    night_minutes = 0
    for s in shifts:
        start_dt, end_dt = _shift_datetimes(work_date, s)
        night_minutes += _overlap_minutes(start_dt, end_dt, night_start_dt, night_end_dt)

    return night_minutes / 60.0

def compute_overtime_buckets(total_hours: float, night_hours: float) -> Tuple[float, float, float, int]:
    """
    Rules:
      - Up to threshold hours: 100%
      - Next 2 hours: 125%
      - Beyond: 150%
      - threshold = 7 if night_hours >= 2 else 8
    """
    threshold = 7 if night_hours >= 2 else 8

    h100 = min(total_hours, threshold)
    remaining = max(0.0, total_hours - threshold)

    h125 = min(2.0, remaining)
    remaining = max(0.0, remaining - h125)

    h150 = remaining
    return round(h100, 2), round(h125, 2), round(h150, 2), threshold
