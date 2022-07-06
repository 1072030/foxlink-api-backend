from app.core.database import Device, User, UserLevel, WhitelistDevice, database
from typing import Dict, Optional
from fastapi.exceptions import HTTPException
from typing import List, Optional
from app.env import DAY_SHIFT_BEGIN, DAY_SHIFT_END


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

async def show_recommend_whitelist_devices(workshop_name: str):
    raw_data_in_day = await database.fetch_all(f"""
        SELECT device, COUNT(*) as count FROM missions m
        INNER JOIN devices d on d.id = m.device
        INNER JOIN factorymaps f on f.id = d.workshop
        WHERE m.created_date >= CURRENT_TIMESTAMP - INTERVAL 1 DAY AND d.is_rescue = 0 AND f.name = :workshop_name AND TIME(m.created_date + INTERVAL 8 HOUR) BETWEEN '{DAY_SHIFT_BEGIN}' AND '{DAY_SHIFT_END}'
        GROUP BY device
        ORDER BY count DESC;
    """, {'workshop_name': workshop_name})


    recommend_devices_in_day: Dict[str, int] = {}
    for x in raw_data_in_day:
        recommend_devices_in_day[x[0]] = int(x[1])

    raw_data_in_night = await database.fetch_all(f"""
        SELECT device, COUNT(*) as count FROM missions m
        INNER JOIN devices d on d.id = m.device
        INNER JOIN factorymaps f on f.id = d.workshop
        WHERE m.created_date >= CURRENT_TIMESTAMP - INTERVAL 1 DAY AND d.is_rescue = 0 AND f.name = :workshop_name
        GROUP BY device
        ORDER BY count DESC;
    """, {'workshop_name': workshop_name})

    recommend_devices_in_night: Dict[str, int] = {}
    for x in raw_data_in_night:
        recommend_devices_in_night[x[0]] = int(x[1])

    for k, v in recommend_devices_in_day.items():
        recommend_devices_in_night[k] -= v

    recommend_devices_in_night = {k: v for k, v in recommend_devices_in_night.items() if v >= 35}
    recommend_devices_in_day = {k: v for k, v in recommend_devices_in_day.items() if v >= 35}

    return recommend_devices_in_day, recommend_devices_in_night