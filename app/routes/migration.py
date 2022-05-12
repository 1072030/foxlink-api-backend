from app.models.schema import ImportDevicesOut
from app.services.auth import get_admin_active_user
from app.services.migration import (
    import_devices,
    import_workshop_events,
    import_factory_worker_infos,
)
from fastapi import APIRouter, Depends, File, Response, UploadFile, Form
from app.core.database import AuditActionEnum, User, AuditLogHeader
from fastapi.exceptions import HTTPException
from typing import List


router = APIRouter(prefix="/migration")


@router.post("/devices", tags=["migration"], status_code=201, response_model=ImportDevicesOut)
async def import_devices_from_excel(
    file: UploadFile = File(...),
    clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "xlsx":
        raise HTTPException(415)

    try:
        device_ids, params = await import_devices(file, clear_all)
        await AuditLogHeader.objects.create(
            table_name="devices",
            action=AuditActionEnum.DATA_IMPORT_SUCCEEDED.value,
            user=user,
        )
        return ImportDevicesOut(device_ids=device_ids, parameter=params.to_csv())
    except Exception as e:
        await AuditLogHeader.objects.create(
            table_name="devices",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
            description="Import devices layout failed",
        )
        raise HTTPException(status_code=400, detail=repr(e))


@router.post("/workshop-eventbook", tags=["migration"], status_code=201,
    responses={
        201: {
            "content": {"image/csv": {}},
            "description": "Return parameters in csv format",
        },
        400: {"description": "There's is an error in your document."},
        415: {"description": "The file you uploaded is not in correct format.",},
    }
)
async def import_workshop_eventbooks_from_excel(
    file: UploadFile = File(...),
    # clear_all: bool = Form(default=False),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "xlsx" and file.filename.split(".")[1] != "xls":
        raise HTTPException(415)

    try:
        params = await import_workshop_events(file)
        return Response(
            content=params.to_csv(),
            status_code=201,
            media_type='text/csv'
        )
    except Exception as e:
        await AuditLogHeader.objects.create(
            table_name="categorypris",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
            description="Import workshop eventbooks failed",
        )
        raise HTTPException(status_code=400, detail=repr(e))


@router.post("/factory-worker-infos", tags=["migration"], status_code=201,
    responses={
        201: {
            "content": {"image/csv": {}},
            "description": "Return parameters in csv format",
        },
        400: {"description": "There's is an error in your document."},
        415: {"description": "The file you uploaded is not in correct format.",},
    }
)
async def import_factory_worker_infos_from_excel(
    workshop_name: str = Form(default="第九車間", description="要匯入員工資訊的車間名稱"),
    file: UploadFile = File(...),
    user: User = Depends(get_admin_active_user),
):
    if file.filename.split(".")[1] != "xlsx":
        raise HTTPException(415)

    try:
        params = await import_factory_worker_infos(workshop_name, file)
        await AuditLogHeader.objects.create(
            table_name="users",
            action=AuditActionEnum.DATA_IMPORT_SUCCEEDED.value,
            user=user,
        )

        return Response(
            content=params.to_csv(),
            status_code=201,
            media_type='text/csv'
        )
    except Exception as e:
        await AuditLogHeader.objects.create(
            table_name="users",
            action=AuditActionEnum.DATA_IMPORT_FAILED.value,
            user=user,
        )
        raise e
