
from datetime import datetime, timezone

from app.main import (
    compute_late_minutes,
    compute_work_hours,
    compute_overtime,
    attendance_date,
    IST,
)

# Late-arrival boundary tests: shift starts at 09:30 IST
assert compute_late_minutes(
    datetime(2026, 7, 6, 9, 40, tzinfo=IST), "09:30"
) == 0

assert compute_late_minutes(
    datetime(2026, 7, 6, 9, 40, 1, tzinfo=IST), "09:30"
) == 10

assert compute_late_minutes(
    datetime(2026, 7, 6, 10, 15, 59, tzinfo=IST), "09:30"
) == 45

# Work duration
assert compute_work_hours(
    datetime(2026, 7, 6, 9, 0, tzinfo=IST),
    datetime(2026, 7, 6, 13, 30, tzinfo=IST),
) == 4.5

# Overtime: less than 30 minutes must be zero
assert compute_overtime(
    datetime(2026, 7, 6, 18, 55, tzinfo=IST),
    "18:30", "2026-07-06", "09:30"
) == 0

# 40 minutes overtime
assert compute_overtime(
    datetime(2026, 7, 6, 19, 10, tzinfo=IST),
    "18:30", "2026-07-06", "09:30"
) == 40

# Overnight shift: punch-in after midnight belongs to previous shift date
assert attendance_date(
    datetime(2026, 7, 7, 0, 30, tzinfo=IST),
    "22:00", "06:00"
) == "2026-07-06"

print("All helper tests passed!")

# Fractional seconds must be truncated before calculations
from app.main import truncate_seconds, as_utc, as_ist

fractional = datetime(
    2026, 7, 6, 9, 40, 0, 900000, tzinfo=IST
)
assert truncate_seconds(fractional).microsecond == 0

# UTC and IST represent the same instant
utc_time = datetime(2026, 7, 6, 4, 0, tzinfo=timezone.utc)
ist_time = as_ist(utc_time)
assert ist_time.hour == 9
assert ist_time.minute == 30

# Naive MongoDB datetimes are interpreted as UTC
naive_time = datetime(2026, 7, 6, 4, 0)
assert as_utc(naive_time).hour == 4
assert as_utc(naive_time).tzinfo == timezone.utc

print("Timestamp tests passed!")
