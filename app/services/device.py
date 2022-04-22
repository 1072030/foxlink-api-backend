from app.core.database import Device
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
