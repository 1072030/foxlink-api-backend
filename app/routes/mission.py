from typing import List
from fastapi import APIRouter, Depends
from app.core.database import User, Mission
from app.services.mission import (
    get_missions,
    get_mission_by_id,
    get_missions_by_user_id,
    create_mission,
    update_mission_by_id,
)
from app.services.user import get_user_by_id
from app.services.auth import get_current_active_user, get_admin_active_user
from app.models.schema import MissionCreate, MissionUpdate
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


@router.post("/{mission_id}/assign", tags=["missions"])
async def assign_mission_to_user(
    mission_id: int, user_id: int, user: User = Depends(get_admin_active_user)
):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            status_code=404, detail="the mission you requested is not found"
        )

    if mission.assignee is None:
        the_user = await get_user_by_id(user_id)
        if the_user is None:
            raise HTTPException(
                status_code=404, detail="the user you requested is not found"
            )
        else:
            mission.assignee = the_user
            await mission.update(assignee=the_user)
    else:
        raise HTTPException(
            status_code=404, detail="this mission is already assigned to other user"
        )
    return


# TODO: implment this
@router.post("/{mission_id}/start", tags=["missions"])
async def start_mission(mission_id: int, user: User = Depends(get_current_active_user)):
    pass


# TODO: implment this
@router.post("/{mission_id}/finish", tags=["missions"])
async def finish_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    pass


# TODO: implment this
@router.post("/{mission_id}/cancel", tags=["missions"])
async def cancel_mission(
    mission_id: int, user: User = Depends(get_current_active_user)
):
    pass


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
