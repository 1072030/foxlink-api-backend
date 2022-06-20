import pytz
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

