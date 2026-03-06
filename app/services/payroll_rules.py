from typing import Tuple

def compute_daily_deficit(total_hours: float, daily_standard: float) -> float:
    return max(0.0, round(daily_standard - total_hours, 2))

def compute_daily_salary(h100: float, h125: float, h150: float, hourly_rate: float) -> float:
    salary = (h100 * hourly_rate) + (h125 * hourly_rate * 1.25) + (h150 * hourly_rate * 1.5)
    return round(salary, 2)
