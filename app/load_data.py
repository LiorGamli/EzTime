import pandas as pd
from sqlalchemy.orm import Session
from .db import engine
from .models import Base, Employee, Rate
from .models import TimeEntry

EXCEL_PATH = "data/EZTIME_DATA.xlsx"


def load_data():
    Base.metadata.create_all(bind=engine)

    df_emp = pd.read_excel(EXCEL_PATH, sheet_name="EmployeeData")
    df_rates = pd.read_excel(EXCEL_PATH, sheet_name="rates")
    df_times = pd.read_excel(EXCEL_PATH, sheet_name="times")

    df_times["work_date"] = pd.to_datetime(df_times["work_date"]).dt.date
    df_times["start_time"] = pd.to_datetime(df_times["start_time"], format="%H:%M").dt.time
    df_times["end_time"] = pd.to_datetime(df_times["end_time"], format="%H:%M").dt.time

    from .db import SessionLocal
    db: Session = SessionLocal()

    # Employees – merge (upsert by primary key)
    for _, row in df_emp.iterrows():
        emp = Employee(
            employee_id=row["employee_id"],
            employee_name=row["full_name"],
            daily_standard_hours=row["daily_standard_hours"]
        )
        db.merge(emp)

    # Rates – clear and reload to avoid duplicates on re-run
    db.query(Rate).delete()
    for _, row in df_rates.iterrows():
        rate = Rate(
            employee_id=row["employee_id"],
            company=row["company_name"],
            role=row["role_name"],
            hourly_rate=row["rate"]
        )
        db.add(rate)

    # Times – skip duplicates
    for _, row in df_times.iterrows():
        exists = db.query(TimeEntry).filter(
            TimeEntry.employee_id == row["employee_id"],
            TimeEntry.work_date == row["work_date"],
            TimeEntry.company_name == row["company_name"],
            TimeEntry.role_name == row["role_name"],
            TimeEntry.start_time == row["start_time"],
            TimeEntry.end_time == row["end_time"],
        ).first()
        if not exists:
            db.add(TimeEntry(
                work_date=row["work_date"],
                employee_id=row["employee_id"],
                role_name=row["role_name"],
                company_name=row["company_name"],
                start_time=row["start_time"],
                end_time=row["end_time"],
            ))

    db.commit()
    db.close()


if __name__ == "__main__":
    load_data()
