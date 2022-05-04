from typing import List, Optional
from fastapi import APIRouter, Depends
from app.models.schema import DeviceOut
from app.services.auth import get_admin_active_user
from app.core.database import Device, User

router = APIRouter(prefix="/device")


@router.get("/", response_model=List[DeviceOut], tags=["device"])
async def get_all_devices(workshop_name: Optional[str] = None, user: User = Depends(get_admin_active_user)):
    params = {
        "workshop__name": workshop_name
    }

    params = {k: v for k, v in params.items() if v is not None}

    devices = (
        await Device.objects
        .select_related('workshop')
        .exclude_fields(["workshop__map", "workshop__related_devices"])
        .filter(**params).all() # type:ignore
    )

    return [DeviceOut.from_device(d) for d in devices]