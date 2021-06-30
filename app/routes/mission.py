from typing import List
from fastapi import APIRouter, Depends
from app.core.database import User, Mission
from app.services.mission import get_mission_by_id, get_missions, create_mission, update_mission_by_id
from app.services.auth import get_current_active_user
from app.models.schema import MissionCreate, MissionUpdate

router = APIRouter(prefix="/missions")


@router.get("/", response_model=List[Mission], tags=["missions"])
async def read_all_missions(user: User = Depends(get_current_active_user)):
    return await get_missions()

@router.get("/{mission_id}", response_model=List[Mission], tags=["missions"])
async def get_a_mission_by_id(mission_id: int, user: User = Depends(get_current_active_user)):
    return await get_mission_by_id(mission_id)


@router.post("/", tags=["missions"])
async def create_a_new_mission(
    dto: MissionCreate, user: User = Depends(get_current_active_user)
):
    return await create_mission(dto)


@router.patch("/{mission_id}", tags=["missions"])
async def update_a_mission(
    mission_id: int, dto: MissionUpdate, user: User = Depends(get_current_active_user)
):
    return await update_mission_by_id(mission_id, dto)
