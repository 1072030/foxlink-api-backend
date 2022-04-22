import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.database import AuditActionEnum, AuditLogHeader, User, Mission
from app.services.mission import (
    accept_mission,
    get_missions,
    get_mission_by_id,
    get_missions_by_username,
    create_mission,
    update_mission_by_id,
    start_mission_by_id,
    finish_mission_by_id,
    reject_mission_by_id,
    delete_mission_by_id,
    assign_mission,
)
from app.services.auth import get_current_active_user, get_admin_active_user
from app.models.schema import MissionCreate, MissionUpdate
from fastapi.exceptions import HTTPException
from app.models.schema import MissionDto, DeviceDto

router = APIRouter(prefix="/missions")


@router.get("/", response_model=List[MissionDto], tags=["missions"])
async def get_missions_by_query(
    user: User = Depends(get_admin_active_user),
    worker: Optional[str] = None,
    is_assigned: Optional[bool] = None,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None,
):
    params = {
        "created_date__gte": start_date,
        "created_date__lte": end_date,
        "assignees__username": worker,
    }

    params = {k: v for k, v in params.items() if v is not None}

    missions = await Mission.objects.select_related(["device", "assignees"]).filter(**params).all()  # type: ignore

    if is_assigned is not None:
        if is_assigned:
            missions = [mission for mission in missions if len(mission.assignees) > 0]
        else:
            missions = [mission for mission in missions if len(mission.assignees) == 0]

    return [MissionDto.from_mission(x) for x in missions]


@router.get("/self", response_model=List[MissionDto], tags=["missions"])
async def get_self_mission(user: User = Depends(get_current_active_user)):
    missions = await get_missions_by_username(user.username)

    return [MissionDto.from_mission(x) for x in missions]


@router.get("/{mission_id}", response_model=MissionDto, tags=["missions"])
async def get_a_mission_by_id(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    m = await get_mission_by_id(mission_id)

    if m is None:
        raise HTTPException(404, "the mission you request is not found")

    return MissionDto.from_mission(m)


@router.post("/{mission_id}/assign", tags=["missions"])
async def assign_mission_to_user(
    mission_id: int, user_name: str, user: User = Depends(get_admin_active_user)
):
    await assign_mission(mission_id, user_name)


@router.post("/{mission_id}/start", tags=["missions"])
async def start_mission(mission_id: int, user: User = Depends(get_current_active_user)):
    await start_mission_by_id(mission_id, user)


@router.post("/{mission_id}/accept", tags=["missions"])
async def accept_mission_by_worker(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    await accept_mission(mission_id, user)


@router.get("/{mission_id}/reject", tags=["missions"])
async def reject_a_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    await reject_mission_by_id(mission_id, user)


@router.post("/{mission_id}/finish", tags=["missions"])
async def finish_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    await finish_mission_by_id(mission_id, user)


# @router.post("/", tags=["missions"], status_code=201)
# async def create_a_mission(
#     dto: MissionCreate, user: User = Depends(get_admin_active_user)
# ):
#     return await create_mission(dto)


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
