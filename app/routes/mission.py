from typing import List
from fastapi import APIRouter, Depends
from app.services.mission import get_missions, create_mission
from app.services.auth import get_current_active_user
from app.models.schema import User, Mission, MissionCreate

router = APIRouter(prefix="/missions")


@router.get("/", response_model=List[Mission], tags=["missions"])
async def read_all_missions(user: User = Depends(get_current_active_user)):
    return await get_missions()


@router.post("/", tags=["missions"])
async def create_a_new_mission(
    dto: MissionCreate, user: User = Depends(get_current_active_user)
):
    return await create_mission(dto)
