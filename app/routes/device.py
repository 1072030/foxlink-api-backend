from typing import List
from fastapi import APIRouter, Depends
from app.services.device import get_devices
from app.services.auth import get_admin_active_user
from app.core.database import Device, User

router = APIRouter(prefix="/device")


@router.get("/", response_model=List[Device], tags=["device"])
async def get_all_devices(user: User = Depends(get_admin_active_user)):
    return await get_devices()
