from app.core.database import Device, User, UserLevel, WhitelistDevice
from typing import Optional
from fastapi.exceptions import HTTPException
from typing import List, Optional


async def get_devices() -> List[Device]:
    devices = await Device.objects.all()
    return devices


async def get_device_by_id(id: str) -> Optional[Device]:
    return await Device.objects.get_or_none(id=id)


def get_device_id(project_name: str, line: Optional[int], device_name: str) -> str:
    if line is None:
        return f"{project_name}-{device_name}"

    return f"{project_name}-{line}-{device_name}"

async def get_workers_from_whitelist_devices(device_id: str):
    whitelist_device = await WhitelistDevice.objects.select_related(['workers']).filter(device=device_id).get_or_none()

    if whitelist_device is None:
        return []

    return [x.username for x in whitelist_device.workers]

async def add_worker_to_device_whitelist(username: str, device_id: str):
    user = await User.objects.filter(username=username).get_or_none()

    if user is None:
        raise HTTPException(404, 'user is not found')

    if user.level != UserLevel.maintainer.value:
        raise HTTPException(400, 'user is not maintainer')

    if not await Device.objects.filter(id=device_id).exists():
        raise HTTPException(404, 'device is not existed')

    whitelist_device, is_created = await WhitelistDevice.objects.get_or_create(device=device_id)

    try:
        await whitelist_device.workers.add(user)
    except:
        raise HTTPException(400, 'cannot add this user to whitelist due to duplicate entry.')