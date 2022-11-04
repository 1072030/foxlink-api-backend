import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm
from app.mqtt.main import publish
from app.services.auth import authenticate_user, create_access_token, get_current_user, set_device_UUID
from datetime import datetime, timedelta
from app.core.database import (
    User,
    AuditLogHeader,
    AuditActionEnum,
    Device,
    Mission,
    UserLevel,
    WorkerStatus,
    WorkerStatusEnum,
)
from app.services.user import get_user_first_login_time_today


class Token(BaseModel):
    access_token: str
    token_type: str


ACCESS_TOKEN_EXPIRE_MINUTES = 60*12

router = APIRouter(prefix="/auth")


@router.post(
    "/token",
    response_model=Token,
    tags=["auth"],
    responses={401: {"description": "Invalid username/password"}},
)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrent credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    await set_device_UUID(user, form_data.client_id)
    access_token = create_access_token(
        data={"sub": user.username, "UUID": user.current_UUID}, expires_delta=access_token_expires
    )

    today_login_timestamp = await get_user_first_login_time_today(user.username)
    is_first_login_today = today_login_timestamp is None

    await AuditLogHeader.objects.create(
        table_name="users",
        record_pk=user.username,
        action=AuditActionEnum.USER_LOGIN.value,
        user=user,
    )

    worker_status = await WorkerStatus.objects.filter(worker=user).get_or_none()

    if worker_status is not None:
        await worker_status.update(status=WorkerStatusEnum.idle.value)

    # if user is a maintainer, then we should mark his status as idle
    if user.level == UserLevel.maintainer.value and is_first_login_today:
        if worker_status is not None:
            worker_status.last_event_end_date = datetime.utcnow()  # type: ignore

            rescue_missions = (
                await Mission.objects.select_related(["device", "assignees"])
                .filter(
                    device__is_rescue=True,
                    assignees__username=user.username,
                    is_cancel=False,
                )
                .all()
            )

            for r in rescue_missions:
                await r.update(is_cancel=True)

            first_rescue_station = await Device.objects.filter(
                workshop=user.location, is_rescue=True
            ).first()

            worker_status.at_device = first_rescue_station
            await worker_status.update()

    # remove it (check login twice)
    publish(f"foxlink/users/{user.username}/connected",
            payload={"connected": True}, qos=2)
    return {"access_token": access_token, "token_type": "bearer"}
