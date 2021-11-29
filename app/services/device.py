from app.core.database import Device
from fastapi.exceptions import HTTPException
from typing import List, Optional


async def get_devices() -> List[Device]:
    devices = await Device.objects.all()
    return devices


async def get_device_by_id(id: str) -> Device:
    d = await Device.objects.get(id=id)
    return d


def get_device_id(machine: str, device_name: str, line: Optional[int]) -> str:
    if line is None:
        return f"{machine}-{device_name}"

    return f"{machine}-{line}-{device_name}"
