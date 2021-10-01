from app.services.auth import get_admin_active_user
from app.services.migration import (
    import_users,
    import_machines,
    import_devices,
    import_employee_repair_experience_table,
    import_employee_shift_table,
)
from fastapi import APIRouter, Depends, File, UploadFile, Form
from app.core.database import User
from fastapi.exceptions import HTTPException


router = APIRouter(prefix="/migration")


@router.post("/users", tags=["migration"], status_code=201)
async def import_users_from_csv(
    file: UploadFile = File(...), user: User = Depends(get_admin_active_user)
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_users(file)


@router.post("/users/shift", tags=["migration"], status_code=201)
async def import_users_shift_info_from_csv(
    file: UploadFile = File(...), user: User = Depends(get_admin_active_user)
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_employee_shift_table(file)


@router.post("/machines", tags=["migration"], status_code=201)
async def import_machines_from_csv(
    file: UploadFile = File(...), user: User = Depends(get_admin_active_user)
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_machines(file)


@router.post("/devices", tags=["migration"], status_code=201)
async def import_devices_from_csv(
    file: UploadFile = File(...),
    clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_devices(file, clear_all)


@router.post("/repair-experiences", tags=["migration"], status_code=201)
async def import_repair_experiences_from_csv(
    file: UploadFile = File(...),
    clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_employee_repair_experience_table(file, clear_all)
