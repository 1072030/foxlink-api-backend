import logging
from jose.constants import ALGORITHMS
from jose.exceptions import  ExpiredSignatureError
from app.core.database import (
    get_ntz_now,
    User,
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

    credentials_exception = HTTPException(
        status_code=HTTPStatus.HTTP_403_FORBIDDEN,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        badge: str = payload.get("sub")
        # current_UUID: str = payload.get("UUID")
        if badge is None:
            raise credentials_exception
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=HTTPStatus.HTTP_403_FORBIDDEN,
            detail="Signature has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except:
        raise credentials_exception

    user = await get_user_by_badge(badge)

    if user is None:
        raise credentials_exception

    # if user.current_UUID != current_UUID:
    #     raise HTTPException(
    #         status_code=HTTPStatus.HTTP_403_FORBIDDEN,
    #         detail="log on other device, should log out.",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )

    return user


async def get_admin_active_user(active_user: User = Depends(get_current_user)):
    if not active_user.level == UserLevel.admin.value:
        raise HTTPException(
            status_code=HTTPStatus.HTTP_401_UNAUTHORIZED, detail="You're not admin!"
        )
    return active_user


async def get_manager_active_user(
    manager_user: User = Depends(get_current_user),
):
    if manager_user.level <= 1:
        raise HTTPException(
            status_code=HTTPStatus.HTTP_401_UNAUTHORIZED,
            detail="You're not manager or admin!",
        )
    return manager_user


async def set_device_UUID(
    user: User, UUID: str
):
    return None
    # await user.update(current_UUID=UUID)
