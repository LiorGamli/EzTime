from datetime import date, datetime

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import engine, get_db
from app.models import Base, Employee, Rate, AttendanceEvent, TimeEntry
from app.services.day_summary import calculate_day
from app.services.shift_validation import validate_new_shift

app = FastAPI(title="EZTIME POC")
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    employee_id: str | None = None,
    work_date: str | None = None,
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).order_by(Employee.employee_id.asc()).all()

    if employee_id is None and employees:
        employee_id = employees[0].employee_id

    if work_date is None:
        work_date = date.today().isoformat()

    summary = None
    if employee_id:
        summary = calculate_day(
            db,
            employee_id=employee_id,
            work_date=date.fromisoformat(work_date),
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "employees": employees,
            "selected_employee_id": employee_id,
            "selected_date": work_date,
            "summary": summary,
            "today": date.today().isoformat(),
        },
    )


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("analytics.html", {"request": request})


@app.get("/api/v1/options", response_class=JSONResponse)
def get_options(employee_id: str, db: Session = Depends(get_db)):
    rates = db.query(Rate).filter(Rate.employee_id == employee_id).all()
    companies = sorted(list({r.company for r in rates if r.company}))
    roles_tmp: dict[str, set[str]] = {}
    for r in rates:
        if not r.company or not r.role:
            continue
        roles_tmp.setdefault(r.company, set()).add(r.role)
    roles_by_company = {c: sorted(list(rs)) for c, rs in roles_tmp.items()}
    return {"companies": companies, "roles_by_company": roles_by_company}


@app.get("/api/v1/analytics/options", response_class=JSONResponse)
def analytics_options(db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.employee_id.asc()).all()
    companies = sorted([r[0] for r in db.query(AttendanceEvent.company).distinct().all() if r[0]])
    roles = sorted([r[0] for r in db.query(AttendanceEvent.role).distinct().all() if r[0]])
    return {
        "employees": [{"id": e.employee_id, "name": e.employee_name} for e in employees],
        "companies": companies,
        "roles": roles,
    }


@app.get("/api/v1/analytics/data", response_class=JSONResponse)
def analytics_data(
    db: Session = Depends(get_db),
    employee_id: str | None = None,
    company: str | None = None,
    role: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    from datetime import datetime as _dt, timedelta
    from collections import defaultdict

    q = db.query(AttendanceEvent)
    if employee_id:
        q = q.filter(AttendanceEvent.employee_id == employee_id)
    if company:
        q = q.filter(AttendanceEvent.company == company)
    if role:
        q = q.filter(AttendanceEvent.role == role)
    if date_from:
        q = q.filter(AttendanceEvent.work_date >= date.fromisoformat(date_from))
    if date_to:
        q = q.filter(AttendanceEvent.work_date <= date.fromisoformat(date_to))

    events = q.order_by(AttendanceEvent.work_date.desc()).all()

    # Group by (employee_id, work_date) – each row = one day for one employee
    grouped: dict = defaultdict(list)
    for e in events:
        grouped[(e.employee_id, e.work_date)].append(e)

    rows = []
    emp_cache = {}
    rate_cache = {}

    for (eid, wdate), evts in grouped.items():
        if eid not in emp_cache:
            emp = db.query(Employee).filter(Employee.employee_id == eid).first()
            emp_cache[eid] = emp

        emp = emp_cache[eid]
        emp_name = emp.employee_name if emp else eid

        total_hours = 0.0
        companies_set = set()
        roles_set = set()
        max_rate = 0.0

        for e in evts:
            start_dt = _dt.combine(wdate, e.start_time)
            end_dt = _dt.combine(wdate, e.end_time)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            total_hours += (end_dt - start_dt).total_seconds() / 3600.0
            companies_set.add(e.company)
            roles_set.add(e.role)

            key = (eid, e.company, e.role)
            if key not in rate_cache:
                r = db.query(Rate).filter(
                    Rate.employee_id == eid,
                    Rate.company == e.company,
                    Rate.role == e.role,
                ).first()
                rate_cache[key] = r.hourly_rate if r else 0.0
            if rate_cache[key] > max_rate:
                max_rate = rate_cache[key]

        # Simple salary estimate (no OT breakdown for summary)
        from app.services.time_rules import compute_night_hours, compute_overtime_buckets, Shift
        shifts = [Shift(start_time=e.start_time, end_time=e.end_time, role_name=e.role, company_name=e.company) for e in evts]
        from app.services.time_rules import compute_total_hours as _cth
        total_h = _cth(wdate, shifts)
        night_h = compute_night_hours(wdate, shifts)
        h100, h125, h150, _ = compute_overtime_buckets(total_h, night_h)
        from app.services.payroll_rules import compute_daily_salary
        salary = compute_daily_salary(h100, h125, h150, max_rate)

        rows.append({
            "employee_id": eid,
            "employee_name": emp_name,
            "work_date": wdate.isoformat(),
            "companies": sorted(list(companies_set)),
            "roles": sorted(list(roles_set)),
            "total_hours": round(total_h, 2),
            "daily_salary": salary,
        })

    rows.sort(key=lambda x: (x["work_date"], x["employee_name"]), reverse=True)
    return {"rows": rows, "count": len(rows)}


@app.post("/api/v1/load-test-data", response_class=JSONResponse)
def load_test_data(db: Session = Depends(get_db)):
    entries = db.query(TimeEntry).all()
    count = 0
    skipped = 0
    for e in entries:
        exists = db.query(AttendanceEvent).filter(
            AttendanceEvent.employee_id == e.employee_id,
            AttendanceEvent.work_date == e.work_date,
            AttendanceEvent.start_time == e.start_time,
            AttendanceEvent.end_time == e.end_time,
            AttendanceEvent.company == e.company_name,
            AttendanceEvent.role == e.role_name,
        ).first()
        if not exists:
            db.add(AttendanceEvent(
                employee_id=e.employee_id,
                work_date=e.work_date,
                company=e.company_name,
                role=e.role_name,
                start_time=e.start_time,
                end_time=e.end_time,
            ))
            count += 1
        else:
            skipped += 1
    db.commit()
    return {"loaded": count, "skipped": skipped}


@app.post("/api/v1/shifts", response_class=JSONResponse)
def add_shift(payload: dict, db: Session = Depends(get_db)):
    try:
        employee_id = str(payload["employee_id"])
        work_date = date.fromisoformat(payload["work_date"])
        company = str(payload["company"])
        role = str(payload["role"])
        start_time = datetime.strptime(payload["start_time"], "%H:%M").time()
        end_time = datetime.strptime(payload["end_time"], "%H:%M").time()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload format")

    emp = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    rate_exists = (
        db.query(Rate)
        .filter(Rate.employee_id == employee_id, Rate.company == company, Rate.role == role)
        .first()
    )
    if not rate_exists:
        raise HTTPException(status_code=400, detail="No rate found for selected company/role")

    try:
        validate_new_shift(
            db,
            employee_id=employee_id,
            work_date=work_date,
            start_time=start_time,
            end_time=end_time,
            max_shift_hours=15.0,
            max_day_hours=15.0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ev = AttendanceEvent(
        employee_id=employee_id,
        work_date=work_date,
        company=company,
        role=role,
        start_time=start_time,
        end_time=end_time,
    )
    db.add(ev)
    db.commit()

    return calculate_day(db, employee_id=employee_id, work_date=work_date)


@app.delete("/api/v1/shifts/{shift_id}", response_class=JSONResponse)
def delete_shift(shift_id: int, db: Session = Depends(get_db)):
    ev = db.query(AttendanceEvent).filter(AttendanceEvent.id == shift_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Shift not found")

    employee_id = ev.employee_id
    work_date = ev.work_date

    db.delete(ev)
    db.commit()

    return calculate_day(db, employee_id=employee_id, work_date=work_date)


@app.put("/api/v1/shifts/{shift_id}", response_class=JSONResponse)
def update_shift(shift_id: int, payload: dict, db: Session = Depends(get_db)):
    ev = db.query(AttendanceEvent).filter(AttendanceEvent.id == shift_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Shift not found")

    try:
        company = str(payload["company"])
        role = str(payload["role"])
        start_time = datetime.strptime(payload["start_time"], "%H:%M").time()
        end_time = datetime.strptime(payload["end_time"], "%H:%M").time()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload format")

    employee_id = ev.employee_id
    work_date = ev.work_date

    rate_exists = (
        db.query(Rate)
        .filter(Rate.employee_id == employee_id, Rate.company == company, Rate.role == role)
        .first()
    )
    if not rate_exists:
        raise HTTPException(status_code=400, detail="No rate found for selected company/role")

    try:
        validate_new_shift(
            db,
            employee_id=employee_id,
            work_date=work_date,
            start_time=start_time,
            end_time=end_time,
            max_shift_hours=15.0,
            max_day_hours=15.0,
            exclude_shift_id=shift_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ev.company = company
    ev.role = role
    ev.start_time = start_time
    ev.end_time = end_time
    db.commit()

    return calculate_day(db, employee_id=employee_id, work_date=work_date)


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    employee_id: str | None = None,
    work_date: str | None = None,
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).order_by(Employee.employee_id.asc()).all()

    if employee_id is None and employees:
        employee_id = employees[0].employee_id

    if work_date is None:
        work_date = date.today().isoformat()

    summary = None
    if employee_id:
        summary = calculate_day(
            db,
            employee_id=employee_id,
            work_date=date.fromisoformat(work_date),
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "employees": employees,
            "selected_employee_id": employee_id,
            "selected_date": work_date,
            "summary": summary,
            "today": date.today().isoformat(),
        },
    )


@app.get("/api/v1/options", response_class=JSONResponse)
def get_options(employee_id: str, db: Session = Depends(get_db)):
    rates = db.query(Rate).filter(Rate.employee_id == employee_id).all()

    companies = sorted(list({r.company for r in rates if r.company}))

    roles_tmp: dict[str, set[str]] = {}
    for r in rates:
        if not r.company or not r.role:
            continue
        roles_tmp.setdefault(r.company, set()).add(r.role)

    roles_by_company = {c: sorted(list(rs)) for c, rs in roles_tmp.items()}
    return {"companies": companies, "roles_by_company": roles_by_company}


@app.post("/api/v1/shifts", response_class=JSONResponse)
def add_shift(payload: dict, db: Session = Depends(get_db)):
    try:
        employee_id = str(payload["employee_id"])
        work_date = date.fromisoformat(payload["work_date"])
        company = str(payload["company"])
        role = str(payload["role"])
        start_time = datetime.strptime(payload["start_time"], "%H:%M").time()
        end_time = datetime.strptime(payload["end_time"], "%H:%M").time()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload format")

    emp = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    rate_exists = (
        db.query(Rate)
        .filter(Rate.employee_id == employee_id, Rate.company == company, Rate.role == role)
        .first()
    )
    if not rate_exists:
        raise HTTPException(status_code=400, detail="No rate found for selected company/role")

    try:
        validate_new_shift(
            db,
            employee_id=employee_id,
            work_date=work_date,
            start_time=start_time,
            end_time=end_time,
            max_shift_hours=15.0,
            max_day_hours=15.0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ev = AttendanceEvent(
        employee_id=employee_id,
        work_date=work_date,
        company=company,
        role=role,
        start_time=start_time,
        end_time=end_time,
    )
    db.add(ev)
    db.commit()

    return calculate_day(db, employee_id=employee_id, work_date=work_date)


@app.delete("/api/v1/shifts/{shift_id}", response_class=JSONResponse)
def delete_shift(shift_id: int, db: Session = Depends(get_db)):
    ev = db.query(AttendanceEvent).filter(AttendanceEvent.id == shift_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Shift not found")

    employee_id = ev.employee_id
    work_date = ev.work_date

    db.delete(ev)
    db.commit()

    return calculate_day(db, employee_id=employee_id, work_date=work_date)


@app.put("/api/v1/shifts/{shift_id}", response_class=JSONResponse)
def update_shift(shift_id: int, payload: dict, db: Session = Depends(get_db)):
    ev = db.query(AttendanceEvent).filter(AttendanceEvent.id == shift_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Shift not found")

    try:
        company = str(payload["company"])
        role = str(payload["role"])
        start_time = datetime.strptime(payload["start_time"], "%H:%M").time()
        end_time = datetime.strptime(payload["end_time"], "%H:%M").time()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload format")

    employee_id = ev.employee_id
    work_date = ev.work_date

    rate_exists = (
        db.query(Rate)
        .filter(Rate.employee_id == employee_id, Rate.company == company, Rate.role == role)
        .first()
    )
    if not rate_exists:
        raise HTTPException(status_code=400, detail="No rate found for selected company/role")

    try:
        validate_new_shift(
            db,
            employee_id=employee_id,
            work_date=work_date,
            start_time=start_time,
            end_time=end_time,
            max_shift_hours=15.0,
            max_day_hours=15.0,
            exclude_shift_id=shift_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ev.company = company
    ev.role = role
    ev.start_time = start_time
    ev.end_time = end_time
    db.commit()

    return calculate_day(db, employee_id=employee_id, work_date=work_date)
