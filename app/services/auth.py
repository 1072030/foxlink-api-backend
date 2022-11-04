from jose.constants import ALGORITHMS
from jose.exceptions import JWTError, ExpiredSignatureError
from sqlalchemy import false, true
from app.core.database import User
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from jose import jwt
from .user import get_user_by_username, pwd_context
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import os
from app.env import JWT_SECRET
from app.services.user import update_user
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class TokenData(BaseModel):
    username: Optional[str] = None


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHMS.HS256)
    return encoded_jwt


async def authenticate_user(username: str, password: str):
    user = await get_user_by_username(username)

    if not user:
        return False
    if not verify_password(password, user.password_hash):
        return False

    if user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    # Check if user login twice
    if user.is_active is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="the user has logged in with another device."
        )

    await update_user_is_active(user.username, is_active=True)

    return user


# user login/logout update is_active : true/false
async def update_user_is_active(username: str, **kwargs):
    user = await get_user_by_username(username)

    if user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )
    try:
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        await user.update(None, **filtered)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="cannot update user:" + repr(e))

    return user

# Check token validation


async def get_current_user(token: str = Depends(oauth2_scheme)):

    credentials_exception = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except ExpiredSignatureError:
        payload = jwt.decode(token, JWT_SECRET,  algorithms=['HS256'], options={
                             "verify_exp": False, "verify_signature": False})
        username: str = payload["sub"]
        await update_user_is_active(username, is_active=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signature has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except:
        raise credentials_exception

    user = await get_user_by_username(username)

    if user is None:
        raise credentials_exception
    await update_user_is_active(username, is_active=True)

    return user


async def get_admin_active_user(active_user: User = Depends(get_current_user)):
    if not active_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="You're not admin!"
        )
    return active_user


async def get_manager_active_user(
    manager_user: User = Depends(get_current_user),
):
    if manager_user.level <= 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="You're not manager or admin!",
        )
    return manager_user
