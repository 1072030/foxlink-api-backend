from datetime import datetime, time
import logging
from app.services.auth import get_manager_active_user
from fastapi import APIRouter, HTTPException
from app.core.database import Shift, User
from app.models.schema import ShiftDto
from app.env import LOGGER_NAME
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/shift")
logger = logging.getLogger(LOGGER_NAME)

@router.get("/update", response_model=ShiftDto, tags=["shift"])
async def update_shift_time(
    id: int,
    shift_beg_time: time,
    shift_end_time: time,
    user: User = Depends(get_manager_active_user),
):
    try:
        shift = await Shift.objects.filter(
            id=id,
        ).get_or_none()

        await shift.update(shift_beg_time=shift_beg_time, shift_end_time=shift_end_time)

    except:
        raise HTTPException(400, "bad shift time request")