import datetime
from typing import List, Any, Optional
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.database import Mission, WorkerStatus, WorkerStatusEnum

from app.services.statistics import (
    EmergencyMissionInfo,
    get_top_most_crashed_devices,
    get_login_users_percentage_by_week,
    get_top_most_accept_mission_employees,
    get_top_most_reject_mission_employees,
    get_top_abnormal_missions,
    get_emergency_missions,
)

router = APIRouter(prefix="/stats")


class Stats(BaseModel):
    top_most_crashed_devices: List[Any]
    top_most_reject_mission_employees: List[Any]
    top_most_accept_mission_employees: List[Any]
    top_abnormal_missions: List[Any]
    login_users_percentage_this_week: float
    current_emergency_mission: List[EmergencyMissionInfo]


@router.get("/", response_model=Stats, tags=["statistics"])
async def get_overall_statistics():
    top_crashed_devices = await get_top_most_crashed_devices(10)
    top_abnormal_missions = await get_top_abnormal_missions(10)
    login_users_percentage = await get_login_users_percentage_by_week()
    top_mission_accept_employees = await get_top_most_accept_mission_employees(10)
    top_mission_reject_employees = await get_top_most_reject_mission_employees(3)
    emergency_missions = await get_emergency_missions()

    return Stats(
        top_most_crashed_devices=top_crashed_devices,
        top_abnormal_missions=top_abnormal_missions,
        login_users_percentage_this_week=login_users_percentage,
        top_most_accept_mission_employees=top_mission_accept_employees,
        top_most_reject_mission_employees=top_mission_reject_employees,
        current_emergency_mission=emergency_missions,
    )


class WorkerStatusDto(BaseModel):
    worker_id: str
    worker_name: str
    last_event_end_date: datetime.datetime
    at_device: str
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
            "at_device": s.at_device.id,
            "status": s.status,
            "last_event_end_date": s.last_event_end_date,
            "total_dispatches": s.dispatch_count,
        }

        missions = await Mission.objects.filter(
            assignees__id=s.worker.id,
            repair_start_date__isnull=False,
            event_end_date__isnull=True,
        ).all()

        if len(missions) > 0:
            duration = datetime.datetime.utcnow() - missions[0].repair_start_date
            item["mission_duration"] = duration.total_seconds()

        resp.append(item)

    return resp
