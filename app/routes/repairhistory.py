from typing import List
from app.core.database import RepairHistory, User
from app.services.repairhistory import (
    get_histories,
    get_history_by_id,
    get_histories_by_user,
)
from fastapi import APIRouter, Depends
from app.services.auth import get_admin_active_user, get_current_active_user

router = APIRouter(prefix="/repair-histories")


@router.get("/", response_model=List[RepairHistory], tags=["repair-histories"])
async def get_all_repair_histories(user: User = Depends(get_current_active_user)):
    return await get_histories()


@router.get("/self", tags=["repair-histories"])
async def get_histories_related_to_user(user: User = Depends(get_current_active_user)):
    return await get_histories_by_user(user)


@router.get("/{history_id}", tags=["repair-histories"])
async def get_the_history_with_id(
    history_id: int, user: User = Depends(get_current_active_user)
):
    return await get_history_by_id(history_id)

