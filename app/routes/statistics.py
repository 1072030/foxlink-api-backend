import datetime
import logging
from typing import List, Any, Optional
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.database import Mission, WorkerStatus, WorkerStatusEnum
import asyncio
from app.env import LOGGER_NAME
from app.models.schema import MissionDto

from app.services.statistics import (
    AbnormalDeviceInfo,
    AbnormalMissionInfo,
    EmergencyMissionInfo,
    get_top_abnormal_missions,
    get_top_most_crashed_devices,
    get_login_users_percentage_by_recent_24_hours,
    get_top_most_accept_mission_employees,
    get_top_most_reject_mission_employees,
    get_top_abnormal_devices,
    get_emergency_missions,
)

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
    top_most_reject_mission_employees: List[Any]
    top_most_accept_mission_employees: List[Any]
    login_users_percentage_this_week: float
    current_emergency_mission: List[MissionDto]


@router.get("/", response_model=Stats, tags=["statistics"])
async def get_overall_statistics():

    (
        top_crashed_devices,
        top_abnormal_devices,
        top_abnormal_missions,
        login_users_percentage,
        top_mission_accept_employees,
        top_mission_reject_employees,
        emergency_missions,
    ) = await asyncio.gather(
        get_top_most_crashed_devices(10),
        get_top_abnormal_devices(10),
        get_top_abnormal_missions(10),
        get_login_users_percentage_by_recent_24_hours(),
        get_top_most_accept_mission_employees(10),
        get_top_most_reject_mission_employees(3),
        get_emergency_missions(),
    )

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


class WorkerStatusDto(BaseModel):
    worker_id: str
    worker_name: str
    last_event_end_date: datetime.datetime
    at_device: Optional[str]
    status: WorkerStatusEnum
    total_dispatches: int
    mission_duration: Optional[int]


@router.get("/worker-status", response_model=List[WorkerStatusDto], tags=["statistics"])
async def get_all_worker_status():
    states = await WorkerStatus.objects.select_related(["worker"]).all()

    resp: List[WorkerStatusDto] = []

    for s in states:
        item = {
            "worker_id": s.worker.username,
            "worker_name": s.worker.full_name,
            "at_device": s.at_device.id if s.at_device is not None else None,
            "status": s.status,
            "last_event_end_date": s.last_event_end_date,
            "total_dispatches": s.dispatch_count,
        }

        missions = await Mission.objects.filter(
            assignees__username=s.worker.username,
            repair_start_date__isnull=False,
            repair_end_date__isnull=True,
        ).order_by("repair_start_date").all()

        if len(missions) > 0:
            duration = datetime.datetime.utcnow() - missions[0].repair_start_date
            item["mission_duration"] = duration.total_seconds()

        resp.append(item)

    return resp
