from app.services.auth import get_admin_active_user
from app.services.migration import import_users
from fastapi import APIRouter, Depends, File, UploadFile
from app.core.database import User


router = APIRouter(prefix="/migration")


@router.post("/user", tags=["migration"], status_code=201)
async def import_users_from_csv(file: UploadFile = File(...)):
    await import_users(file)
