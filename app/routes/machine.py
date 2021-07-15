from app.models.schema import MachineCreate, MachineUpdate
from typing import List
from fastapi import APIRouter, Depends
from app.services.machine import (
    get_machines,
    create_machine,
    update_machine,
    delete_machine_by_id,
)
from app.services.auth import get_admin_active_user, get_current_active_user
from app.core.database import User, Machine

router = APIRouter(prefix="/machines")


@router.get("/", response_model=List[Machine], tags=["machines"])
async def read_all_machines(user: User = Depends(get_current_active_user)):
    return await get_machines()


@router.post("/", tags=["machines"])
async def create_a_new_machine(
    dto: MachineCreate, user: User = Depends(get_admin_active_user)
):
    return await create_machine(dto)


@router.patch("/{machine_id}", tags=["machines"])
async def update_a_existing_machine(
    machine_id: int, dto: MachineUpdate, user: User = Depends(get_current_active_user)
):
    return await update_machine(machine_id, dto)


@router.delete("/{machine_id}", tags=["machines"])
async def delete_a_machine_by_id(
    machine_id: int, user: User = Depends(get_admin_active_user)
):
    await delete_machine_by_id(machine_id)
