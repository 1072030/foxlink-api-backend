import datetime, logging
from typing import List, Any
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.database import Mission, WorkerStatus, UserLevel, WorkerStatusEnum
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
async def get_overall_statistics():
    top_crashed_devices = await get_top_most_crashed_devices(10)
    top_abnormal_devices = await get_top_abnormal_devices(10)
    top_abnormal_missions = await get_top_abnormal_missions(10)
    login_users_percentage = await get_login_users_percentage_by_recent_24_hours()
    top_mission_accept_employees = await get_top_most_accept_mission_employees(10)
    top_mission_reject_employees = await get_top_most_reject_mission_employees(3)
    emergency_missions = await get_emergency_missions()

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


"""
SELECT u.username, u.full_name, ws.at_device, ws.dispatch_count, ws.last_event_end_date,  mu.mission as mission_id, (UTC_TIMESTAMP() - m2.created_date) as mission_duration FROM worker_status ws
LEFT JOIN missions_users mu ON mu.id = (
	SELECT mu2.id FROM missions m
	INNER JOIN missions_users mu2
	ON mu2.user = ws.worker
	WHERE m.repair_end_date IS NULL AND m.is_cancel = False
	LIMIT 1
)
LEFT JOIN missions m2 ON m2.id = mu.mission
LEFT JOIN users u ON u.username = ws.worker;
"""


@router.get("/worker-status", response_model=List[WorkerStatusDto], tags=["statistics"])
async def get_all_worker_status():
    states = (
        await WorkerStatus.objects.select_related(["worker"])
        .filter(worker__level=UserLevel.maintainer.value)
        .all()
    )

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

        if s.status == WorkerStatusEnum.working.value:
            try:
                mission = (
                    await Mission.objects.filter(
                        assignees__username=s.worker.username,
                        repair_start_date__isnull=False,
                        repair_end_date__isnull=True,
                    )
                    .order_by("repair_start_date")
                    .first()
                )

                duration = datetime.datetime.utcnow() - mission.repair_start_date
                item["mission_duration"] = duration.total_seconds()
            except:
                ...
        resp.append(item)

    return resp
