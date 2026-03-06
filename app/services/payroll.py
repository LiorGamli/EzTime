from datetime import datetime, time


def hours_between(start, end):
    delta = datetime.combine(datetime.today(), end) - datetime.combine(datetime.today(), start)
    return delta.total_seconds() / 3600


def compute_total_hours(shifts):
    total = 0
    for s in shifts:
        total += hours_between(s["start"], s["end"])
    return total


def compute_overtime(total_hours, night_shift=False):
    threshold = 7 if night_shift else 8

    h100 = min(total_hours, threshold)

    remaining = max(0, total_hours - threshold)
    h125 = min(2, remaining)

    remaining -= h125
    h150 = max(0, remaining)

    return h100, h125, h150


def compute_salary(h100, h125, h150, rate):
    return (
        h100 * rate +
        h125 * rate * 1.25 +
        h150 * rate * 1.5
    )
