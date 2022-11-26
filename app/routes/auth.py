import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm
from app.mqtt import mqtt_client
from app.services.auth import authenticate_user, create_access_token, get_current_user, set_device_UUID
from datetime import datetime, timedelta
from app.core.database import (
    User,
    AuditLogHeader,
    AuditActionEnum,
    Device,
    Mission,
    UserLevel,
    WorkerStatusEnum,
)
from app.services.user import get_user_first_login_time_today
import logging


class Token(BaseModel):
    access_token: str
    token_type: str


ACCESS_TOKEN_EXPIRE_MINUTES = 60*12

router = APIRouter(prefix="/auth",tags=["auth"])


@router.post("/token",response_model=Token,responses={401: {"description": "Invalid username/password"}})
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    
    user = await authenticate_user(form_data.username, form_data.password)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    access_token = create_access_token(
        data={
            "sub": user.username,
            "UUID": 0
        },
        expires_delta=access_token_expires
    )

    # await set_device_UUID(user, form_data.client_id)

    is_first_login_today = await get_user_first_login_time_today(user.username)

    await AuditLogHeader.objects.create(
        table_name="users",
        record_pk=user.username,
        action=AuditActionEnum.USER_LOGIN.value,
        user=user,
    )

    await user.update(status=WorkerStatusEnum.idle.value)

    # if user is a maintainer, then we should mark his status as idle
    if user.level == UserLevel.maintainer.value and is_first_login_today != None:
            user.last_event_end_date = datetime.utcnow()  # type: ignore

            rescue_missions = (
                await Mission.objects.select_related(["device"])
                .filter(
                    device__is_rescue=True,
                    worker=user,
                    is_cancel=False,
                )
                .all()
            )

            for r in rescue_missions:
                await r.update(is_cancel=True)

            first_rescue_station = await Device.objects.filter(
                workshop=user.workshop, is_rescue=True
            ).first()

            user.at_device = first_rescue_station
            
            await user.update()

    await user.update( login_date = datetime.utcnow())

    return {"access_token": access_token, "token_type": "bearer"}
