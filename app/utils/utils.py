import pytz
from app.core.database import ShiftType
from datetime import datetime
from app.env import DAY_SHIFT_BEGIN, DAY_SHIFT_END

CST_TIMEZONE = pytz.timezone("Asia/Taipei")


def get_shift_type_now() -> ShiftType:
    now = datetime.now(CST_TIMEZONE)
    day_begin = datetime.time(datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M"))
    day_end = datetime.time(datetime.strptime(DAY_SHIFT_END, "%H:%M"))
    if now.time() >= day_begin and now.time() <= day_end:
        return ShiftType.day
    else:
        return ShiftType.night


def get_shift_type_by_datetime(dt: datetime) -> ShiftType:
    day_begin = datetime.time(datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M"))
    day_end = datetime.time(datetime.strptime(DAY_SHIFT_END, "%H:%M"))
    if dt.time() >= day_begin and dt.time() <= day_end:
        return ShiftType.day
    else:
        return ShiftType.night

