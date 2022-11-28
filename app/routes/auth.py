import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm
from app.mqtt import mqtt_client
from app.services.auth import authenticate_user, create_access_token, get_current_user, set_device_UUID
from datetime import datetime, timedelta, timezone
from app.core.database import (
    transaction,
    api_db,
    User,
    AuditLogHeader,
    AuditActionEnum,
    Device,
    Mission,
    UserLevel,
    WorkerStatusEnum
)
from app.core.database import get_ntz_now
from app.services.mission import set_mission_by_rescue_position
from app.services.user import check_user_begin_shift
import logging
import traceback


class Token(BaseModel):
    access_token: str
    token_type: str


ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12

router = APIRouter(prefix="/auth", tags=["auth"])


@transaction
@router.post("/token", response_model=Token, responses={401: {"description": "Invalid username/password"}})
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):

    user = await authenticate_user(form_data.username, form_data.password)

    if user.status == WorkerStatusEnum.working.value:
        raise HTTPException(
            403, f'the worker on device : {user.current_UUID} is working now.')

    await set_device_UUID(user, form_data.client_id)
    access_token = create_access_token(
        data={
            "sub": user.badge,
            "UUID": form_data.client_id
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    user.login_date = get_ntz_now()

    await AuditLogHeader.objects.create(
        table_name="users",
        record_pk=user.badge,
        action=AuditActionEnum.USER_LOGIN.value,
        user=user,
    )
    
    await user.update(status=WorkerStatusEnum.idle.value)
    if user.level == UserLevel.maintainer.value and await check_user_begin_shift(user):

        # reset user parameters
        user.shift_beg_date = get_ntz_now()
        user.finish_event_date = get_ntz_now()
        user.shift_reject_count = 0
        user.shift_accept_count = 0

        rescue_station = (
            await Device.objects
            .filter(
                workshop=user.workshop, is_rescue=True
            )
            .first()
        )

        user.at_device = rescue_station

        # TODO: Weird Check, this section is required due to design flaws?
        rescue_missions = (
            await Mission.objects
            .select_related(["device"])
            .filter(
                worker=user,
                is_done=False,
                device__is_rescue=True,
            )
            .all()
        )

        for r in rescue_missions:
            await r.update(
                is_done=True,
                is_done_cancel=True
            )
        #######################################################

        await user.update()

        if user.start_position is not None:
            await set_mission_by_rescue_position(user, user.start_position)

    return {"access_token": access_token, "token_type": "bearer"}
