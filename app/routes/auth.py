from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm
from app.services.auth import authenticate_user, create_access_token
from datetime import timedelta
from app.core.database import (
    AuditLogHeader,
    AuditActionEnum,
    UserLevel,
    WorkerStatus,
    WorkerStatusEnum,
)


class Token(BaseModel):
    access_token: str
    token_type: str


ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12
router = APIRouter(prefix="/auth")


@router.post("/token", response_model=Token, tags=["auth"], responses={401: {"description": "Invalid username/password"}})
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrent credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    await AuditLogHeader.objects.create(
        table_name="users",
        record_pk=user.username,
        action=AuditActionEnum.USER_LOGIN.value,
        user=user,
    )

    # if user is a maintainer, then we should mark his status as idle
    if user.level == UserLevel.maintainer.value:
        await WorkerStatus.objects.filter(worker=user).update(
            status=WorkerStatusEnum.idle.value
        )

    return {"access_token": access_token, "token_type": "bearer"}
