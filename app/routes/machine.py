from typing import List
from fastapi import APIRouter, Depends
from app.services.machine import get_machines, create_machine
from app.services.auth import get_current_active_user
from app.core.database import User, Machine

router = APIRouter(prefix="/machines")


@router.get("/", response_model=List[Machine], tags=["machines"])
async def read_all_machines(user: User = Depends(get_current_active_user)):
    return await get_machines()


@router.post("/", tags=["machines"])
async def create_a_new_machine(
    dto: Machine, user: User = Depends(get_current_active_user)
):
    return await create_machine(dto)
