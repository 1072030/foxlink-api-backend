from datetime import datetime, time
import logging
from app.services.auth import get_manager_active_user
from fastapi import APIRouter, HTTPException
from app.core.database import Shift, User
from app.models.schema import ShiftDto
from app.log import LOGGER_NAME
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/shift")
logger = logging.getLogger(LOGGER_NAME)


@router.get("/update", response_model=ShiftDto, tags=["shift"])
async def update_shift_time(
    id: int,
    shift_beg_time: str,
    shift_end_time: str,
    # user: User = Depends(get_manager_active_user),
):
    try:
        shift1 = await Shift.objects.filter(
            id=id,
        ).get_or_none()

        await shift1.update(shift_beg_time=shift_beg_time, shift_end_time=shift_end_time)
        
        if id == 2: id = 1
        else: id = 2
        
        shift2 = await Shift.objects.filter(
            id=id,
        ).get_or_none()

        await shift2.update(shift_beg_time=shift_end_time, shift_end_time=shift_beg_time)

    except:
        raise HTTPException(400, "bad shift time request")
