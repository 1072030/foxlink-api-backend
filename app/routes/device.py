from app.models.schema import FactoryMapCreate
from typing import List
from fastapi import APIRouter, Depends
from app.services.device import get_devices
from app.services.auth import get_admin_active_user, get_current_active_user
from app.core.database import Device, User

router = APIRouter(prefix="/device")


@router.get("/", response_model=List[Device], tags=["device"])
async def get_all_devices(user: User = Depends(get_admin_active_user)):
    return await get_devices()


# @router.get("/{map_id}", response_model=FactoryMap, tags=["device"])
# async def get_factory_map_by_id(
#     map_id: int, user: User = Depends(get_admin_active_user)
# ):
#     return await get_map_by_id(map_id)

