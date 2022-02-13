from typing import List
from fastapi import APIRouter, Depends
from app.core.database import User, Mission
from app.services.mission import (
    get_missions,
    get_mission_by_id,
    get_missions_by_user_id,
    create_mission,
    update_mission_by_id,
    start_mission_by_id,
    finish_mission_by_id,
    cancel_mission_by_id,
    reject_mission_by_id,
)
from app.services.user import get_user_by_id
from app.services.auth import get_current_active_user, get_admin_active_user
from app.models.schema import MissionCancel, MissionCreate, MissionUpdate, MissionFinish
from app.mqtt.main import publish
from fastapi.exceptions import HTTPException

router = APIRouter(prefix="/missions")


@router.get("/", response_model=List[Mission], tags=["missions"])
async def read_all_missions(user: User = Depends(get_current_active_user)):
    return await get_missions()


@router.get("/self", response_model=List[Mission], tags=["missions"])
async def get_self_mission(user: User = Depends(get_current_active_user)):
    return await get_missions_by_user_id(user.id)


@router.get("/{mission_id}", response_model=Mission, tags=["missions"])
async def get_a_mission_by_id(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    return await get_mission_by_id(mission_id)


# TODO: Refactor this method
@router.post("/{mission_id}/assign", tags=["missions"])
async def assign_mission_to_user(
    mission_id: int, user_id: str, user: User = Depends(get_admin_active_user)
):
    mission = await Mission.objects.select_related(["assignees", "device"]).get(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(
            status_code=404, detail="the mission you requested is not found"
        )

    if mission.is_closed:
        raise HTTPException(
            status_code=400, detail="the mission you requested is closed"
        )

    the_user = await get_user_by_id(user_id)

    if the_user is None:
        raise HTTPException(
            status_code=404, detail="the user you requested is not found"
        )

    for e in mission.required_expertises:
        if e not in the_user.expertises:
            raise HTTPException(
                status_code=400,
                detail="the user does not have the expertise this mission requires.",
            )

    filter = [u for u in mission.assignees if u.id == the_user.id]

    if len(filter) == 0:
        await mission.assignees.add(the_user)  # type: ignore
        publish(
            f"foxlink/users/{the_user.username}/missions",
            {
                "type": "new",
                "mission_id": mission.id,
                "device": {
                    "project": mission.device.project,
                    "process": mission.device.process,
                    "line": mission.device.line,
                    "name": mission.device.device_name,
                },
            },
            1,
        )
    else:
        raise HTTPException(400, detail="the user is already assigned to this mission")


@router.post("/{mission_id}/start", tags=["missions"])
async def start_mission(mission_id: int, user: User = Depends(get_current_active_user)):
    await start_mission_by_id(mission_id, user)


# TODO: Implement this
@router.get("/{mission_id}/reject", tags=["missions"])
async def reject_a_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    return await reject_mission_by_id(mission_id, user)


@router.post("/{mission_id}/finish", tags=["missions"])
async def finish_mission(
    mission_id: int, dto: MissionFinish, user: User = Depends(get_current_active_user)
):
    await finish_mission_by_id(mission_id, dto, user)


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

