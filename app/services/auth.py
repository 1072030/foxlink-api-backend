import logging
from jose.constants import ALGORITHMS
from jose.exceptions import ExpiredSignatureError
from app.core.database import (
    WorkerStatusEnum,
    get_ntz_now,
    User,
    Mission
)
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from jose import jwt
from .user import get_user_by_badge, pwd_context
from fastapi import Depends, HTTPException, status as HTTPStatus
from fastapi.security import OAuth2PasswordBearer
from app.env import (
    JWT_SECRET,
)
from app.core.database import UserLevel

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class TokenData(BaseModel):
    badge: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = get_ntz_now() + expires_delta
    else:
        expire = get_ntz_now()
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHMS.HS256)
    return encoded_jwt


async def authenticate_user(badge: str, password: str):
    user = await get_user_by_badge(badge)

    if user is None:
        raise HTTPException(
            status_code=HTTPStatus.HTTP_401_UNAUTHORIZED, detail="the user with this id is not found."
        )

    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=HTTPStatus.HTTP_401_UNAUTHORIZED, detail="the password is incorrect."
        )

    return user


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        badge: str = payload.get("sub")
        decode_UUID: str = payload.get("UUID")

        if badge is None:
            raise HTTPException(403, 'Could not validate credentials')
    except ExpiredSignatureError:
        payload = jwt.decode(token, JWT_SECRET,  algorithms=['HS256'], options={
                             "verify_exp": False, "verify_signature": False})
        badge: str = payload.get("sub")
        decode_UUID: str = payload.get("UUID")
        user = await get_user_by_badge(badge)

        if decode_UUID == user.current_UUID:
            await user.update(current_UUID="0")

        raise HTTPException(403, 'Signature has expired')

    except:
        raise HTTPException(403, 'Could not validate credentials')

    user = await get_user_by_badge(badge)

    if user is None:
        raise HTTPException(403, 'Could not validate credentials')

    if user.current_UUID != decode_UUID and user.level == UserLevel.maintainer.value:
        raise HTTPException(403, 'log on another device. Should log out')

    return user


async def get_admin_active_user(active_user: User = Depends(get_current_user)):
    if not active_user.level == UserLevel.admin.value:
        raise HTTPException(
            status_code=HTTPStatus.HTTP_403_FORBIDDEN, detail="Permission Denied"
        )
    return active_user


async def get_manager_active_user(
    manager_user: User = Depends(get_current_user),
):
    if manager_user.level <= UserLevel.maintainer.value:
        raise HTTPException(
            status_code=HTTPStatus.HTTP_403_FORBIDDEN,
            detail="Permission Denied",
        )
    return manager_user


async def check_user_status_by_badge(user: User):
    if user.status is WorkerStatusEnum.notice.value:
        mission = await Mission.objects.select_related(['worker']).get_or_none()
        if mission.notify_recv_date is None:
            return WorkerStatusEnum.idle.value
    return user.status


async def set_device_UUID(
    user: User, UUID: str
):
    await user.update(current_UUID=UUID)
