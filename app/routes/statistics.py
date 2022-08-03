import datetime, logging
from typing import List, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.database import FactoryMap, Mission, ShiftType, WorkerStatus, UserLevel, WorkerStatusEnum
import asyncio
from app.env import LOGGER_NAME
from app.models.schema import MissionDto, WorkerMissionStats, WorkerStatusDto

from app.services.statistics import (
    AbnormalDeviceInfo,
    AbnormalMissionInfo,
    get_top_abnormal_missions,
    get_top_most_crashed_devices,
    get_login_users_percentage_by_recent_24_hours,
    get_top_most_accept_mission_employees,
    get_top_most_reject_mission_employees,
    get_top_abnormal_devices,
    get_emergency_missions,
)

from app.services.user import get_worker_status

logger = logging.getLogger(LOGGER_NAME)
router = APIRouter(prefix="/stats")


class DeviceStats(BaseModel):
    # 最常故障的設備
    most_frequent_crashed_devices: List[Any]
    # 照設備的 Category 去統計各個異常處理時間，並依照處理時間由高到小排序。
    top_abnormal_devices: List[AbnormalDeviceInfo]
    # 統計當月所有異常任務，並依照處理時間由高到小排序。
    top_abnormal_missions_this_month: List[AbnormalMissionInfo]


class Stats(BaseModel):
    devices_stats: DeviceStats
    top_most_reject_mission_employees: List[WorkerMissionStats]
    top_most_accept_mission_employees: List[WorkerMissionStats]
    login_users_percentage_this_week: float
    current_emergency_mission: List[MissionDto]


@router.get("/", response_model=Stats, tags=["statistics"])
async def get_overall_statistics(workshop_name: str, start_date: datetime.datetime, end_date: datetime.datetime, is_night_shift: Optional[bool] = None):
    """
    Parameters:
        start_date - Should be UTC timezone.
        end_date - Should be UTC timezone.
    """

    if start_date > end_date:
        raise HTTPException(400, "start_date should be less than end_date")

    if not await FactoryMap.objects.filter(name=workshop_name).exists():
        raise HTTPException(404, "workshop_name is not existed")

    shift = ShiftType.day if is_night_shift == False else (ShiftType.night if is_night_shift == True else None)

    workshop_id = (await FactoryMap.objects.filter(name=workshop_name).exclude_fields(['map', 'image', 'related_devices']).get()).id
        
    top_crashed_devices = await get_top_most_crashed_devices(workshop_id, start_date, end_date, shift, 10)
    top_abnormal_devices = await get_top_abnormal_devices(workshop_id, start_date, end_date, shift, 10)
    top_abnormal_missions = await get_top_abnormal_missions(workshop_id, start_date, end_date, shift, 10)
    login_users_percentage = await get_login_users_percentage_by_recent_24_hours(workshop_id, start_date, end_date, shift)
    top_mission_accept_employees = await get_top_most_accept_mission_employees(workshop_id, start_date, end_date, shift, 10)
    top_mission_reject_employees = await get_top_most_reject_mission_employees(workshop_id, start_date, end_date, shift, 3)
    emergency_missions = await get_emergency_missions(workshop_id)

    return Stats(
        devices_stats=DeviceStats(
            most_frequent_crashed_devices=top_crashed_devices,
            top_abnormal_devices=top_abnormal_devices,
            top_abnormal_missions_this_month=top_abnormal_missions,
        ),
        login_users_percentage_this_week=login_users_percentage,
        top_most_accept_mission_employees=top_mission_accept_employees,
        top_most_reject_mission_employees=top_mission_reject_employees,
        current_emergency_mission=emergency_missions,
    )


@router.get("/{workshop_name}/worker-status", response_model=List[WorkerStatusDto], tags=["statistics"])
async def get_all_worker_status(workshop_name: str):
    states = (
        await WorkerStatus.objects.select_related(["worker", "worker__location"])
        .exclude_fields(['worker__location__related_devices', 'worker__location__image', 'worker__location__map'])
        .filter(worker__level=UserLevel.maintainer.value, worker__location__name=workshop_name)
        .all()
    )

    resp: List[WorkerStatusDto] = []

    promises = [get_worker_status(s.worker.username) for s in states]
    resp = await asyncio.gather(*promises)
    return resp
