from app.services.auth import get_admin_active_user
from app.services.migration import import_users, import_machines
from fastapi import APIRouter, Depends, File, UploadFile
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


@router.post("/machines", tags=["migration"], status_code=201)
async def import_machines_from_csv(
    file: UploadFile = File(...), user: User = Depends(get_admin_active_user)
):
    if file.filename.split(".")[1] != "csv":
        raise HTTPException(415)
    await import_machines(file)
