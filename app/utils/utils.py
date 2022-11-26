from pickle import TUPLE
import pytz
from typing import Tuple
from app.core.database import (
    get_ntz_now,
    ShiftType,
    Shift
) 
from datetime import datetime, timedelta,time
from app.env import (
    DAY_SHIFT_BEGIN, 
    DAY_SHIFT_END, 
    TZ
)

async def get_current_shift_details()-> Tuple[ShiftType,datetime,datetime]:
    now = get_ntz_now().astimezone(TZ)
    now_time = now.time()
    shifts = await Shift.objects.all()
    for shift in shifts:
        tz_now = now.astimezone(TZ)

        # due to the timezone specification problem, 
        # which is the timezone for shift time is set to TZ,
        # but the system uses datetime without timezones,
        # therefore need to convert the time setting from shift to non-timezoned format
        period_beg =  (
            tz_now
            .replace(
                hour=shift.shift_beg_time.hour,
                minute=shift.shift_beg_time.minute,
                second=0
            )
            .astimezone(None)
            .replace(tzinfo=None)
        )

        period_end = (    
            tz_now
            .replace(
                hour=shift.shift_end_time.hour,
                minute=shift.shift_end_time.minute,
                second=0
            )
            .astimezone(None)
            .replace(tzinfo=None)
        )
        shift_type = ShiftType(shift.id)
        if shift.shift_beg_time > shift.shift_end_time:
            if(now_time > shift.shift_beg_time or now_time < shift.shift_end_time):
                if(now_time < time.max):
                    return (
                        shift_type,
                        period_beg,
                        period_end+timedelta(days=1)
                    )
                else:
                    return (
                        shift_type,
                        period_beg-timedelta(days=1),
                        period_end
                    )

        else:
            if(now_time > shift.shift_beg_time and now_time < shift.shift_end_time):
                return (
                    shift_type,
                    period_beg,
                    period_end
                )

async def get_current_shift_type() -> (ShiftType):
   return (await get_current_shift_details())[0]

# TODO: No time, need to adjust to new in database shift structure
async def get_current_shift_time_interval() -> Tuple[datetime, datetime]:
    shift_type = await get_current_shift_type()
    now_time = get_ntz_now()

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

# TODO: No time, need to adjust to new in database shift structure
def get_previous_shift_time_interval():
    now_time = get_ntz_now()

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

# def time_within_period(at: time, beg: time,end: time):
#     if beg > end:
#         if(at > beg or at < end):
#             return True
#     else:
#         if(at > beg and at < end):
#             return True

# async def check_date_in_current_shift(date: datetime,shift: ShiftType):
#     now = get_ntz_now()
#     shift = await Shift.objects.filter(shift.value).get_or_none()
#     return time_within_period(
#         time(hour=date.hour,minute=date.minute),
#         shift.shift_beg_time,
#         shift.shift_end_time
#     )


