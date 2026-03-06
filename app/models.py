from sqlalchemy import Column, Integer, String, Float, Time, Date
from .db import Base


class Employee(Base):
    __tablename__ = "employee_data"

    employee_id = Column(String, primary_key=True, index=True)
    employee_name = Column(String)
    daily_standard_hours = Column(Float)


class Rate(Base):
    __tablename__ = "rates"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String)
    company = Column(String)
    role = Column(String)
    hourly_rate = Column(Float)


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String)
    work_date = Column(Date)
    company = Column(String)
    role = Column(String)
    start_time = Column(Time)
    end_time = Column(Time)


class TimeEntry(Base):
    __tablename__ = "times"

    id = Column(Integer, primary_key=True, index=True)
    work_date = Column(Date, index=True)
    employee_id = Column(String, index=True)
    role_name = Column(String)
    company_name = Column(String)
    start_time = Column(Time)
    end_time = Column(Time)
