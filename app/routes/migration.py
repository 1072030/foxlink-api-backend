from app.services.auth import get_admin_active_user
from app.services.migration import (
    import_devices,
    import_devices,
    import_workshop_events,
    import_factory_worker_infos,
)
from fastapi import APIRouter, Depends, File, UploadFile, Form
from app.core.database import AuditActionEnum, User, AuditLogHeader
from fastapi.exceptions import HTTPException


router = APIRouter(prefix="/migration")


@router.post("/devices", tags=["migration"], status_code=201)
async def import_devices_from_excel(
    file: UploadFile = File(...),
    clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "xlsx":
        raise HTTPException(415)

    try:
        await import_devices(file, clear_all)
        await AuditLogHeader.objects.create(
            table_name="devices",
            action=AuditActionEnum.DATA_IMPORT_SUCCEEDED.value,
            user=user,
        )
    except Exception as e:
        await AuditLogHeader.objects.create(
            table_name="devices",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )
        raise e


@router.post("/workshop-eventbook", tags=["migration"], status_code=201)
async def import_workshop_eventbooks_from_excel(
    file: UploadFile = File(...),
    # clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "xlsx" and file.filename.split(".")[1] != "xls":
        raise HTTPException(415)

    try:
        await import_workshop_events(file)
    except Exception as e:
        await AuditLogHeader.objects.create(
            table_name="categorypris",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )
        raise e


@router.post("/factory-worker-infos", tags=["migration"], status_code=201)
async def import_factory_worker_infos_from_excel(
    workshop_name: str = Form(default="第九車間", description="要匯入員工資訊的車間名稱"),
    file: UploadFile = File(...),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "xlsx":
        raise HTTPException(415)

    try:
        await import_factory_worker_infos(workshop_name, file)
        await AuditLogHeader.objects.create(
            table_name="users",
            action=AuditActionEnum.DATA_IMPORT_SUCCEEDED.value,
            user=user,
        )
    except Exception as e:
        await AuditLogHeader.objects.create(
            table_name="users",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )
        raise e
