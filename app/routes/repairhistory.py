from app.models.schema import RepairHistoryCreate
from typing import List
from app.core.database import RepairHistory, User
from app.services.repairhistory import (
    create_history_for_mission,
    get_histories,
    get_history_by_id,
    get_histories_by_user,
)
from fastapi import APIRouter, Depends
from app.services.auth import get_admin_active_user, get_current_active_user

router = APIRouter(prefix="/repair-histories")


@router.get("/", tags=["repair-histories"])
async def get_all_repair_histories(user: User = Depends(get_current_active_user)):
    return await get_histories()


@router.post("/", tags=["repair-histories"], status_code=201)
async def create_a_repair_history_for_mission(
    dto: RepairHistoryCreate, user: User = Depends(get_current_active_user),
):
    return await create_history_for_mission(dto)


@router.get("/self", tags=["repair-histories"])
async def get_histories_related_to_user(user: User = Depends(get_current_active_user)):
    return await get_histories_by_user(user)


@router.get("/{history_id}", tags=["repair-histories"])
async def get_the_history_with_id(
    history_id: int, user: User = Depends(get_current_active_user)
):
    return await get_history_by_id(history_id)
