from app.core.database import Device
from fastapi.exceptions import HTTPException
from typing import List


async def get_devices() -> List[Device]:
    devices = await Device.objects.all()
    return devices


async def get_device_by_id(id: str) -> Device:
    d = await Device.objects.get(id=id)
    return d
