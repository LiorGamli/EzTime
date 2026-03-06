from __future__ import annotations

from datetime import date
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.models import AttendanceEvent, Employee, Rate
from app.services.time_rules import Shift, compute_total_hours, compute_night_hours, compute_overtime_buckets
from app.services.payroll_rules import compute_daily_deficit, compute_daily_salary


def calculate_day(db: Session, employee_id: str, work_date: date) -> Dict[str, Any]:
    emp = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not emp:
        raise ValueError("Employee not found")

    events: List[AttendanceEvent] = (
        db.query(AttendanceEvent)
        .filter(AttendanceEvent.employee_id == employee_id, AttendanceEvent.work_date == work_date)
        .order_by(AttendanceEvent.start_time.asc())
        .all()
    )

    shifts_for_calc = [
        Shift(
            start_time=e.start_time,
            end_time=e.end_time,
            role_name=e.role,
            company_name=e.company,
        )
        for e in events
    ]

    total_hours = compute_total_hours(work_date, shifts_for_calc) if shifts_for_calc else 0.0
    night_hours = compute_night_hours(work_date, shifts_for_calc) if shifts_for_calc else 0.0
    h100, h125, h150, threshold = compute_overtime_buckets(total_hours, night_hours)

    max_rate = 0.0
    for s in shifts_for_calc:
        r = (
            db.query(Rate)
            .filter(
                Rate.employee_id == employee_id,
                Rate.company == s.company_name,
                Rate.role == s.role_name,
            )
            .first()
        )
        if r and r.hourly_rate and r.hourly_rate > max_rate:
            max_rate = r.hourly_rate

    daily_salary = compute_daily_salary(h100, h125, h150, max_rate) if max_rate > 0 else 0.0
    daily_deficit = compute_daily_deficit(total_hours, emp.daily_standard_hours or 0.0)

    # Aggregate hours per (company, role)
    from collections import defaultdict
    from datetime import datetime as _dt
    hours_map: dict = defaultdict(float)
    for e in events:
        start_dt = _dt.combine(work_date, e.start_time)
        end_dt = _dt.combine(work_date, e.end_time)
        if end_dt <= start_dt:
            from datetime import timedelta
            end_dt += timedelta(days=1)
        h = (end_dt - start_dt).total_seconds() / 3600.0
        hours_map[(e.company, e.role)] += h

    hours_by_company_role = [
        {
            "company": company,
            "role": role,
            "hours": round(hours, 2),
        }
        for (company, role), hours in sorted(hours_map.items())
    ]

    return {
        "employee_id": employee_id,
        "employee_name": emp.employee_name,
        "work_date": work_date.isoformat(),
        "total_hours": round(total_hours, 2),
        "night_hours": round(night_hours, 2),
        "overtime_threshold": threshold,
        "h100": h100,
        "h125": h125,
        "h150": h150,
        "max_rate": round(max_rate, 2),
        "daily_salary": daily_salary,
        "daily_deficit": daily_deficit,
        "hours_by_company_role": hours_by_company_role,
        "shifts": [
            {
                "id": e.id,
                "company": e.company,
                "role": e.role,
                "start_time": e.start_time.strftime("%H:%M"),
                "end_time": e.end_time.strftime("%H:%M"),
            }
            for e in events
        ],
    }
