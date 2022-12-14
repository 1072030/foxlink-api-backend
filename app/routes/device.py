from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException
from app.models.schema import (
    # CategoryPriorityOut,
    DeviceDispatchableWorker,
    DeviceOut,
    WhitelistRecommendDevice
)
from app.services.auth import (
    get_manager_active_user,
    get_current_user
)
from app.core.database import (
    # CategoryPRI,
    Device,
    ShiftType,
    User,
    FactoryMap,
    UserDeviceLevel,
    UserLevel,
    WhitelistDevice
)
from app.services.device import (
    add_worker_to_device_whitelist,
    get_workers_from_whitelist_devices,
    show_recommend_whitelist_devices
)

router = APIRouter(prefix="/device")


@router.get("/", response_model=List[DeviceOut], tags=["device"])
async def get_all_devices(
    workshop_name: Optional[str] = None, user: User = Depends(get_manager_active_user)
):
    params = {"workshop__name": workshop_name}

    params = {k: v for k, v in params.items() if v is not None}

    devices = (
        await Device.objects
        .select_related("workshop")
        .exclude_fields(FactoryMap.heavy_fields("workshop"))
        .filter(**params)  # type:ignore
        .all()
    )

    return [DeviceOut.from_device(d) for d in devices]


# @router.get(
#     "/category-priority", response_model=List[CategoryPriorityOut], tags=["device"]
# )
# async def get_category_priority_by_project(
#     workshop_name: str, project: str, user: User = Depends(get_manager_active_user)
# ):
#     workshop = (
#         await FactoryMap.objects.filter(name=workshop_name)
#         .exclude_fields(["map", "image"])
#         .get_or_none()
#     )

#     if workshop is None:
#         raise HTTPException(404, "the workshop is not found")

#     category_pri = (
#         await CategoryPRI.objects.select_related(["devices"])
#         .filter(devices__project__iexact=project, devices__workshop=workshop.id)
#         .all()
#     )
#     return [CategoryPriorityOut.from_categorypri(c) for c in category_pri]

@router.get("/whitelist", tags=['whitelist device'])
async def get_whitelist_devices(workshop_name: str):
    whitelist_devices = (
        await WhitelistDevice.objects
        .select_related(['device', 'device__workshop', 'workers'])
        .exclude_fields(FactoryMap.heavy_fields("device__workshop"))
        .filter(device__workshop__name=workshop_name).all()
    )

    resp = {}
    for w in whitelist_devices:
        badges = []
        for u in w.workers:
            badges.append({'badge': u.badge, 'username': u.username})

        if len(badges) != 0:
            resp[w.device.id] = badges
    return resp


@router.get("/whitelist/recommend", tags=['whitelist device'], response_model=WhitelistRecommendDevice)
async def get_recommend_day_and_night_whitelist_devices(workshop_name: str):
    day_data, night_data = await show_recommend_whitelist_devices(workshop_name)
    return {
        'day': day_data,
        'night': night_data
    }


@router.get("/{device_id}/whitelist", tags=['whitelist device'])
async def get_workers_from_a_whitelist_device(device_id: str):
    return await get_workers_from_whitelist_devices(device_id)


@router.post("/{device_id}/whitelist", tags=['whitelist device'])
async def add_worker_to_whitelist_device(device_id: str, badge: str):
    await add_worker_to_device_whitelist(badge, device_id)


@router.delete("/{device_id}/whitelist", tags=['whitelist device'])
async def remove_worker_from_whitelist_device(device_id: str, badge: str):
    user = await User.objects.get_or_none(badge=badge)
    if user is None:
        raise HTTPException(404, 'the user is not found')

    whitelist_device = await WhitelistDevice.objects.filter(device=device_id, workers__badge=badge).get_or_none()

    if whitelist_device is None:
        raise HTTPException(404, 'the user is not in whitelist')

    await whitelist_device.workers.remove(user)


@router.get("/{device_id}/workers", tags=["device"], response_model=List[DeviceDispatchableWorker], description="Get dispatchable workers of devices.\n shift_type=0: day shift\n shift_type=1: night shift")
async def get_device_dispatchable_workers(device_id: str, shift_type: bool):
    user_device_levels = await UserDeviceLevel.objects.select_related(['user']).filter(device=device_id, shift=shift_type, level__gt=0, user__level=UserLevel.maintainer.value).all()
    return [DeviceDispatchableWorker(badge=x.user.badge, username=x.user.username) for x in user_device_levels]


@router.get("/{device_id}", response_model=DeviceOut, tags=["device"])
async def get_device_by_id(
    device_id: str, user: User = Depends(get_current_user())
):
    device = (
        await Device.objects
        .select_related("workshop")
        .exclude_fields(FactoryMap.heavy_fields("workshop"))
        .filter(id=device_id)
        .get_or_none()
    )

    if device is None:
        raise HTTPException(404, "the device is not found")

    return DeviceOut.from_device(device)
