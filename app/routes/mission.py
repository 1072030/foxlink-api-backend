import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends
from app.core.database import (
    AuditActionEnum,
    AuditLogHeader,
    User,
    Mission,
    UserLevel,
    database,
)
from app.services.mission import (
    accept_mission,
    cancel_mission_by_id,
    get_mission_by_id,
    request_assistance,
    update_mission_by_id,
    start_mission_by_id,
    finish_mission_by_id,
    reject_mission_by_id,
    delete_mission_by_id,
    assign_mission,
)
from app.services.auth import (
    get_current_user,
    get_manager_active_user,
)
from app.models.schema import MissionUpdate, MissionDto
from fastapi.exceptions import HTTPException

from app.services.user import is_user_working_on_mission

router = APIRouter(prefix="/missions")


@router.get("/", response_model=List[MissionDto], tags=["missions"])
async def get_missions_by_query(
    user: User = Depends(get_manager_active_user),
    worker: Optional[str] = None,
    workshop_name: Optional[str] = None,
    is_assigned: Optional[bool] = None,
    is_started: Optional[bool] = None,
    is_closed: Optional[bool] = None,
    is_cancel: Optional[bool] = None,
    is_emergency: Optional[bool] = None,
    is_rescue: Optional[bool] = None,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None,
):
    params = {
        "created_date__gte": start_date,
        "created_date__lte": end_date,
        "assignees__username": worker,
        "is_cancel": is_cancel,
        "is_emergency": is_emergency,
        "device__is_rescue": is_rescue,
        "device__workshop__name": workshop_name,
        "repair_start_date__isnull": not is_started if is_started is not None else None,
        "repair_end_date__isnull": not is_closed if is_closed is not None else None,
    }

    params = {k: v for k, v in params.items() if v is not None}

    missions = (
        await Mission.objects.select_related(
            ["device", "assignees", "missionevents", "device__workshop"]
        )
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .filter(**params)  # type: ignore
        .order_by("-created_date")
        .all()
    )

    if is_assigned is not None:
        if is_assigned:
            missions = [mission for mission in missions if len(
                mission.assignees) > 0]
        else:
            missions = [mission for mission in missions if len(
                mission.assignees) == 0]

    mission_list = [MissionDto.from_mission(x) for x in missions]

    return mission_list


@router.get("/self", response_model=List[MissionDto], tags=["missions"])
async def get_self_mission(
    user: User = Depends(get_current_user),
    is_assigned: Optional[bool] = None,
    is_started: Optional[bool] = None,
    is_closed: Optional[bool] = None,
    is_cancel: Optional[bool] = None,
    is_emergency: Optional[bool] = None,
    is_rescue: Optional[bool] = None,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None,
):
    params = {
        "created_date__gte": start_date,
        "created_date__lte": end_date,
        "is_cancel": is_cancel,
        "is_emergency": is_emergency,
        "device__is_rescue": is_rescue,
        "repair_start_date__isnull": not is_started if is_started is not None else None,
        "repair_end_date__isnull": not is_closed if is_closed is not None else None,
    }
    params = {k: v for k, v in params.items() if v is not None}

    missions = (
        await Mission.objects.select_related(
            ["device", "assignees", "missionevents", "device__workshop"]
        )
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .filter(assignees__username=user.username, **params)  # type: ignore
        .order_by("-created_date")
        .all()
    )

    if is_assigned is not None:
        if is_assigned:
            missions = [mission for mission in missions if len(
                mission.assignees) > 0]
        else:
            missions = [mission for mission in missions if len(
                mission.assignees) == 0]

    return [MissionDto.from_mission(x) for x in missions]



@router.get("/{mission_id}", response_model=MissionDto, tags=["missions"])
async def get_a_mission_by_id(
    mission_id: int, user: User = Depends(get_current_user)
):
    m = await get_mission_by_id(mission_id)

    if m is None:
        raise HTTPException(404, "the mission you request is not found")

    if user.level == UserLevel.maintainer.value and user.username not in [
        n.username for n in m.assignees
    ]:
        raise HTTPException(401, "you are not one of this mission's assignees")

    return MissionDto.from_mission(m)


@router.post("/{mission_id}/assign", tags=["missions"])
async def assign_mission_to_user(
    mission_id: int, user_name: str, user: User = Depends(get_manager_active_user)
):
    if (await is_user_working_on_mission(user_name)) == True:
        raise HTTPException(400, "the user is working on other mission")

    async with database.transaction():
        await assign_mission(mission_id, user_name)
        await AuditLogHeader.objects.create(
            table_name="missions",
            record_pk=mission_id,
            action=AuditActionEnum.MISSION_ASSIGNED.value,
            user=user_name,
            description=f"From Web API (Reqeust by {user.username})",
        )


@router.post("/{mission_id}/cancel", tags=["missions"])
async def cancel_a_mission_by_id(
    mission_id: int, user: User = Depends(get_manager_active_user)
):
    await cancel_mission_by_id(mission_id)
    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_CANCELED.value,
        table_name="missions",
        record_pk=str(mission_id),
        user=user,
    )


@router.post("/{mission_id}/start", tags=["missions"])
async def start_mission(mission_id: int, user: User = Depends(get_current_user)):
    await start_mission_by_id(mission_id, user)


@router.post("/{mission_id}/accept", tags=["missions"])
async def accept_mission_by_worker(
    mission_id: int, user: User = Depends(get_current_user)
):
    await accept_mission(mission_id, user)


@router.get("/{mission_id}/reject", tags=["missions"])
async def reject_a_mission(
    mission_id: int, user: User = Depends(get_current_user)
):
    await reject_mission_by_id(mission_id, user)

@router.post("/{mission_id}/finish", tags=["missions"])
async def finish_mission(
    mission_id: int, user: User = Depends(get_current_user)
):
    await finish_mission_by_id(mission_id, user)


@router.get("/{mission_id}/emergency", tags=["missions"], status_code=201)
async def mark_mission_emergency(
    mission_id: int, user: User = Depends(get_current_user)
):
    await request_assistance(mission_id, user)


@database.transaction()
@router.patch("/{mission_id}", tags=["missions"])
async def update_mission(
    mission_id: int, dto: MissionUpdate, user: User = Depends(get_manager_active_user)
):
    await update_mission_by_id(mission_id, dto)
    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_UPDATED.value,
        record_pk=str(mission_id),
        user=user,
        description=str(dto),
    )


@database.transaction()
@router.delete("/{mission_id}", tags=["missions"])
async def delete_mission(
    mission_id: int, user: User = Depends(get_manager_active_user)
):
    await delete_mission_by_id(mission_id)
    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_DELETED.value,
        record_pk=str(mission_id),
        user=user,
    )
