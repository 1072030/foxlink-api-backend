from datetime import datetime, timedelta
from typing import List, Optional
from fastapi.exceptions import HTTPException
import ormar
from app.models.schema import UserCreate
from passlib.context import CryptContext
from app.core.database import AuditActionEnum, AuditLogHeader, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password)


async def get_users() -> List[User]:
    return await User.objects.all()


async def create_user(dto: UserCreate) -> User:
    pw_hash = get_password_hash(dto.password)
    new_dto = dto.dict()
    del new_dto["password"]
    new_dto["password_hash"] = pw_hash

    user = User(**new_dto)

    try:
        return await user.save()
    except Exception as e:
        raise HTTPException(status_code=400, detail="cannot add user:" + str(e))


async def get_user_by_username(username: str) -> Optional[User]:
    user = await User.objects.filter(username=username).get_or_none()
    return user


async def update_user(username: str, **kwargs):
    user = await get_user_by_username(username)

    if user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    try:
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        await user.update(None, **filtered)
    except Exception as e:
        raise HTTPException(status_code=400, detail="cannot update user:" + str(e))

    return user


async def delete_user_by_username(username: str):
    affected_row = await User.objects.delete(username=username)

    if affected_row != 1:
        raise HTTPException(status_code=404, detail="user by this id is not found")


async def get_employee_work_timestamp_today(username: str) -> Optional[datetime]:
    """
    Get a employee's first login record past 12 hours (today)
    If the employee has not been logined in today, return None
    """
    past_12_hours = datetime.utcnow() - timedelta(hours=12)

    try:
        first_login_record = (
            await AuditLogHeader.objects.filter(
                action=AuditActionEnum.USER_LOGIN.value,
                user=username,
                created_date__gte=past_12_hours,
            )
            .order_by("created_date")
            .first()
        )
        return first_login_record.created_date
    except Exception:
        return None
