from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from app.models.schema import CategoryPriorityOut, DeviceOut
from app.services.auth import get_manager_active_user, get_current_active_user
from app.core.database import CategoryPRI, Device, User, FactoryMap

router = APIRouter(prefix="/device")


@router.get("/", response_model=List[DeviceOut], tags=["device"])
async def get_all_devices(
    workshop_name: Optional[str] = None, user: User = Depends(get_manager_active_user)
):
    params = {"workshop__name": workshop_name}

    params = {k: v for k, v in params.items() if v is not None}

    devices = (
        await Device.objects.select_related("workshop")
        .exclude_fields(["workshop__map", "workshop__related_devices", "workshop__image"])
        .filter(**params)  # type:ignore
        .all()
    )

    return [DeviceOut.from_device(d) for d in devices]


@router.get(
    "/category-priority", response_model=List[CategoryPriorityOut], tags=["device"]
)
async def get_category_priority_by_project(
    workshop_name: str, project: str, user: User = Depends(get_manager_active_user)
):
    workshop = (
        await FactoryMap.objects.filter(name=workshop_name)
        .exclude_fields(["map", "image"])
        .get_or_none()
    )

    if workshop is None:
        raise HTTPException(404, "the workshop is not found")

    category_pri = (
        await CategoryPRI.objects.select_related(["devices"])
        .filter(devices__project__iexact=project, devices__workshop=workshop.id)
        .all()
    )
    return [CategoryPriorityOut.from_categorypri(c) for c in category_pri]


@router.get("/{device_id}", response_model=DeviceOut, tags=["device"])
async def get_device_by_id(
    device_id: str, user: User = Depends(get_current_active_user)
):
    device = (
        await Device.objects.select_related("workshop")
        .exclude_fields(["workshop__map", "workshop__related_devices", "workshop__image"])
        .filter(id=device_id)
        .get_or_none()
    )

    if device is None:
        raise HTTPException(404, "the device is not found")

    return DeviceOut.from_device(device)
