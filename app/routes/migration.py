from app.services.auth import get_admin_active_user
from app.services.migration import (
    import_users,
    import_devices,
    import_employee_repair_experience_table,
    import_employee_shift_table,
    import_project_category_priority,
    transform_events,
)
from fastapi import APIRouter, Depends, File, UploadFile, Form
from app.core.database import AuditActionEnum, User, AuditLogHeader
from fastapi.exceptions import HTTPException


router = APIRouter(prefix="/migration")


@router.post("/users", tags=["migration"], status_code=201)
async def import_users_from_csv(
    file: UploadFile = File(...), user: User = Depends(get_admin_active_user)
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    
    try:
        await import_users(file)
    except:
        await AuditLogHeader.objects.create(
            table_name="users",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )


@router.post("/users/shift", tags=["migration"], status_code=201)
async def import_users_shift_info_from_csv(
    file: UploadFile = File(...), user: User = Depends(get_admin_active_user)
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_employee_shift_table(file)


@router.post("/devices", tags=["migration"], status_code=201)
async def import_devices_from_csv(
    file: UploadFile = File(...),
    clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)

    try:
        await import_devices(file, clear_all)
    except:
        await AuditLogHeader.objects.create(
            table_name="devices",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )


@router.post("/repair-experiences", tags=["migration"], status_code=201)
async def import_repair_experiences_from_csv(
    file: UploadFile = File(...),
    clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_employee_repair_experience_table(file, clear_all)


@router.post("/project-category-priority", tags=["migration"], status_code=201)
async def import_project_category_priority_from_csv(
    file: UploadFile = File(...),
    # clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)

    try:
        await import_project_category_priority(file)
    except:
        await AuditLogHeader.objects.create(
            table_name="categorypris",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )


@router.post("/pre-processing", tags=["migration"], status_code=201)
async def import_transform_table(
    file: UploadFile = File(...), clear_all: bool = Form(default=False),
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await transform_events(file)
