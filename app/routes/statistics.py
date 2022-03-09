import datetime
from typing import List, Any
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.database import WorkerStatus, WorkerStatusEnum

from app.services.statistics import (
    EmergencyMissionInfo,
    get_top_most_crashed_devices,
    get_login_users_percentage_by_week,
    get_top_most_reject_mission_employee,
    get_top_abnormal_missions,
    get_emergency_missions,
)

router = APIRouter(prefix="/stats")


class Stats(BaseModel):
    top_most_crashed_devices: List[Any]
    top_most_reject_mission_employee: List[Any]
    top_abnormal_missions: List[Any]
    login_users_percentage_this_week: float
    current_emergency_mission: List[EmergencyMissionInfo]


@router.get("/", response_model=Stats, tags=["statistics"])
async def get_overall_statistics():
    limit = 10

    top_crashed_devices = await get_top_most_crashed_devices(limit)
    top_abnormal_missions = await get_top_abnormal_missions(limit)
    login_users_percentage = await get_login_users_percentage_by_week()
    top_mission_reject_employees = await get_top_most_reject_mission_employee(limit)
    emergency_missions = await get_emergency_missions()

    return Stats(
        top_most_crashed_devices=top_crashed_devices,
        top_abnormal_missions=top_abnormal_missions,
        login_users_percentage_this_week=login_users_percentage,
        top_most_reject_mission_employee=top_mission_reject_employees,
        current_emergency_mission=emergency_missions,
    )


class WorkerStatusDto(BaseModel):
    worker_id: str
    worker_name: str
    last_event_end_date: datetime.datetime
    at_device: str
    status: WorkerStatusEnum
    total_dispatches: int


@router.get("/worker-status", response_model=List[WorkerStatusDto], tags=["statistics"])
async def get_all_worker_status():
    states = await WorkerStatus.objects.select_related("worker").all()

    return [
        {
            "worker_id": s.worker.username,
            "worker_name": s.worker.full_name,
            "at_device": s.at_device.id,
            "status": s.status,
            "last_event_end_date": s.last_event_end_date,
            "total_dispatches": s.dispatch_count,
        }
        for s in states
    ]
