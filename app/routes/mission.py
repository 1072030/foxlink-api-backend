from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.database import AuditActionEnum, AuditLogHeader, User, Mission
from app.services.mission import (
    get_missions,
    get_mission_by_id,
    get_missions_by_username,
    create_mission,
    update_mission_by_id,
    start_mission_by_id,
    finish_mission_by_id,
    cancel_mission_by_id,
    reject_mission_by_id,
    delete_mission_by_id,
    assign_mission,
)
from app.services.auth import get_current_active_user, get_admin_active_user
from app.models.schema import MissionCancel, MissionCreate, MissionUpdate, MissionFinish
from app.mqtt.main import publish
from fastapi.exceptions import HTTPException
import datetime

router = APIRouter(prefix="/missions")


class DeviceDto(BaseModel):
    device_id: str
    device_name: str
    project: str
    process: str
    line: int


class MissionDto(BaseModel):
    mission_id: int
    device: DeviceDto
    name: str
    description: str
    assignees: List[str]
    is_started: bool
    is_closed: bool
    done_verified: bool
    event_start_date: Optional[datetime.datetime]
    event_end_date: Optional[datetime.datetime]
    created_date: datetime.datetime
    updated_date: datetime.datetime


@router.get("/", response_model=List[MissionDto], tags=["missions"])
async def read_all_missions(user: User = Depends(get_admin_active_user)):
    missions = await get_missions()

    return [
        MissionDto(
            mission_id=x.id,
            name=x.name,
            device=DeviceDto(
                device_id=x.device.id,
                device_name=x.device.device_name,
                project=x.device.project,
                process=x.device.process,
                line=x.device.line,
            ),
            description=x.description,
            is_started=x.is_started,
            is_closed=x.is_closed,
            done_verified=x.done_verified,
            assignees=[u.username for u in x.assignees],
            event_start_date=x.event_start_date,
            event_end_date=x.event_end_date,
            created_date=x.created_date,
            updated_date=x.updated_date,
        )
        for x in missions
    ]


@router.get("/self", response_model=List[MissionDto], tags=["missions"])
async def get_self_mission(user: User = Depends(get_current_active_user)):
    missions = await get_missions_by_username(user.username)

    return [
        MissionDto(
            mission_id=x.id,
            name=x.name,
            device=DeviceDto(
                device_id=x.device.id,
                device_name=x.device.device_name,
                project=x.device.project,
                process=x.device.process,
                line=x.device.line,
            ),
            description=x.description,
            is_started=x.is_started,
            is_closed=x.is_closed,
            done_verified=x.done_verified,
            assignees=[u.username for u in x.assignees],
            event_start_date=x.event_start_date,
            event_end_date=x.event_end_date,
            created_date=x.created_date,
            updated_date=x.updated_date,
        )
        for x in missions
    ]


@router.get("/{mission_id}", response_model=MissionDto, tags=["missions"])
async def get_a_mission_by_id(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    m = await get_mission_by_id(mission_id)

    if m is None:
        raise HTTPException(404, "the mission you request is not found")

    return MissionDto(
        mission_id=m.id,
        name=m.name,
        device=DeviceDto(
            device_id=m.device.id,
            device_name=m.device.device_name,
            project=m.device.project,
            process=m.device.process,
            line=m.device.line,
        ),
        description=m.description,
        is_started=m.is_started,
        is_closed=m.is_closed,
        done_verified=m.done_verified,
        assignees=[u.username for u in m.assignees],
        event_start_date=m.event_start_date,
        event_end_date=m.event_end_date,
        created_date=m.created_date,
        updated_date=m.updated_date,
    )


@router.post("/{mission_id}/assign", tags=["missions"])
async def assign_mission_to_user(
    mission_id: int, user_name: str, user: User = Depends(get_admin_active_user)
):
    await assign_mission(mission_id, user_name)


@router.post("/{mission_id}/start", tags=["missions"])
async def start_mission(mission_id: int, user: User = Depends(get_current_active_user)):
    await start_mission_by_id(mission_id, user)


@router.get("/{mission_id}/reject", tags=["missions"])
async def reject_a_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    return await reject_mission_by_id(mission_id, user)


@router.post("/{mission_id}/finish", tags=["missions"])
async def finish_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    await finish_mission_by_id(mission_id, user)


@router.post("/{mission_id}/cancel", tags=["missions"])
async def cancel_mission(
    dto: MissionCancel, user: User = Depends(get_current_active_user)
):
    await cancel_mission_by_id(dto, user)


@router.post("/", tags=["missions"], status_code=201)
async def create_a_mission(
    dto: MissionCreate, user: User = Depends(get_admin_active_user)
):
    return await create_mission(dto)


@router.patch("/{mission_id}", tags=["missions"])
async def update_mission(
    mission_id: int, dto: MissionUpdate, user: User = Depends(get_admin_active_user)
):
    return await update_mission_by_id(mission_id, dto)


@router.delete("/{mission_id}", tags=["missions"])
async def delete_mission(mission_id: int, user: User = Depends(get_admin_active_user)):
    await delete_mission_by_id(mission_id)
    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_DELETED.value,
        record_pk=str(mission_id),
        user=user,
    )
