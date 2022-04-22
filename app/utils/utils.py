import pytz
from app.core.database import ShiftType, AuditLogHeader, AuditActionEnum
from typing import Optional
from datetime import datetime, timedelta
from app.env import NIGHT_SHIFT_BEGIN, NIGHT_SHIFT_END, DAY_SHIFT_BEGIN, DAY_SHIFT_END

CST_TIMEZONE = pytz.timezone("Asia/Taipei")


def get_shift_type_now() -> ShiftType:
    now = datetime.now(CST_TIMEZONE)
    day_begin = datetime.time(datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M"))  # type: ignore
    day_end = datetime.time(datetime.strptime(DAY_SHIFT_END, "%H:%M"))  # type: ignore
    if now.time() >= day_begin and now.time() <= day_end:
        return ShiftType.day
    else:
        return ShiftType.night


def get_shift_type_by_datetime(dt: datetime) -> ShiftType:
    day_begin = datetime.time(datetime.strptime(DAY_SHIFT_BEGIN, "%H:%M"))  # type: ignore
    day_end = datetime.time(datetime.strptime(DAY_SHIFT_END, "%H:%M"))  # type: ignore
    if dt.time() >= day_begin and dt.time() <= day_end:
        return ShiftType.day
    else:
        return ShiftType.night

async def get_user_first_login_time(username: str) -> Optional[datetime]:
    login_record = await AuditLogHeader.objects.filter(
        user=username,
        action=AuditActionEnum.USER_LOGIN.value,
        created_date__gte=datetime.utcnow() - timedelta(hours=12),
    ).order_by(AuditLogHeader.created_date.asc()).first() # type: ignore

    if login_record is None:
        return None
    else:
        return login_record.created_date