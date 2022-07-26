from pickle import TUPLE
import pytz
from typing import Tuple
from app.core.database import ShiftType
from datetime import datetime, timedelta
from app.env import DAY_SHIFT_BEGIN, DAY_SHIFT_END

CST_TIMEZONE = pytz.timezone("Asia/Taipei")

def get_shift_type_now() -> ShiftType:
    now_time = datetime.now(CST_TIMEZONE).time()
    now = datetime(1900, 1, 1, 0, 0).replace(hour=now_time.hour, minute=now_time.minute, second=now_time.second)
    day_begin = datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M")
    day_end = datetime.strptime(DAY_SHIFT_END, "%H:%M")

    if day_end < day_begin:
        day_end += timedelta(hours=24)

    if now < day_begin:
        now += timedelta(hours=24)

    if now >= day_begin and now <= day_end:
        return ShiftType.day
    else:
        return ShiftType.night


def get_shift_type_by_datetime(dt: datetime) -> ShiftType:
    day_begin = datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M")
    day_end = datetime.strptime(DAY_SHIFT_END, "%H:%M")

    china_tz_dt = dt + CST_TIMEZONE.utcoffset(dt)
    china_tz_dt = china_tz_dt.replace(year=1900, month=1, day=1)

    if day_end < day_begin:
        day_end += timedelta(hours=24)

    if china_tz_dt < day_begin:
        china_tz_dt += timedelta(hours=24)

    if china_tz_dt >= day_begin and china_tz_dt <= day_end:
        return ShiftType.day
    else:
        return ShiftType.night

def get_current_shift_time_interval() -> Tuple[datetime, datetime]:
    shift_type = get_shift_type_now()
    now_time = datetime.now(CST_TIMEZONE)

    day_begin = datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M")
    day_end = datetime.strptime(DAY_SHIFT_END, "%H:%M")

    if shift_type == ShiftType.day:
        shift_start = now_time.replace(hour=day_begin.hour, minute=day_begin.minute, second=0)
        shift_end = now_time.replace(hour=day_end.hour, minute=day_end.minute, second=0)
    else:
        shift_start = now_time.replace(hour=day_end.hour, minute=day_end.minute, second=1)
        shift_end = now_time.replace(hour=day_begin.hour, minute=day_begin.minute, second=59)
        shift_end -= timedelta(minutes=1)

        if now_time.time() < day_begin.time():
            shift_start -= timedelta(days=1)
        elif now_time.time() >= day_end.time():
            shift_end += timedelta(days=1)

    return shift_start.astimezone(pytz.utc), shift_end.astimezone(pytz.utc)

def get_previous_shift_time_interval():
    now_time = datetime.now(CST_TIMEZONE)

    day_begin = datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M")
    day_end = datetime.strptime(DAY_SHIFT_END, "%H:%M")

    day_shift_start = now_time.replace(hour=day_begin.hour, minute=day_begin.minute, second=0)
    day_shift_end = now_time.replace(hour=day_end.hour, minute=day_end.minute, second=0)

    if now_time.time() < day_end.time():
        day_shift_start -= timedelta(days=1)
        day_shift_end -= timedelta(days=1)

    night_shift_start = now_time.replace(hour=day_end.hour, minute=day_end.minute, second=1)
    night_shift_end = now_time.replace(hour=day_begin.hour, minute=day_begin.minute, second=59)

    if now_time.time() < night_shift_end.time():
        night_shift_end -= timedelta(days=1)
        night_shift_start -= timedelta(days=2)
    else:
        night_shift_start -= timedelta(days=1)

    return day_shift_start.astimezone(pytz.utc), day_shift_end.astimezone(pytz.utc), night_shift_start.astimezone(pytz.utc), night_shift_end.astimezone(pytz.utc)

    



