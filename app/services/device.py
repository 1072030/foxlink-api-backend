import logging
from app.core.database import Device, User, UserLevel, WhitelistDevice, api_db
from typing import Dict, Optional
from fastapi.exceptions import HTTPException
from typing import List, Optional
from app.log import LOGGER_NAME
from app.env import WHITELIST_MINIMUM_OCCUR_COUNT
from app.utils.utils import get_previous_shift_time_interval

logger = logging.getLogger(LOGGER_NAME)

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
    day_start, day_end, night_start, night_end = get_previous_shift_time_interval()

    #logger.info(f'{day_start}, {day_end}, {night_start}, {night_end}')

    raw_data_in_day = await api_db.fetch_all(f"""
        SELECT device, COUNT(*) as count FROM missions m
        INNER JOIN devices d on d.id = m.device
        INNER JOIN factorymaps f on f.id = d.workshop
        WHERE (m.created_date BETWEEN :day_start AND :day_end) AND d.is_rescue = 0 AND f.name = :workshop_name
        GROUP BY device
        ORDER BY count DESC;
    """, {'workshop_name': workshop_name, 'day_start': day_start, 'day_end': day_end})


    recommend_devices_in_day: Dict[str, int] = {}
    for x in raw_data_in_day:
        recommend_devices_in_day[x[0]] = int(x[1])

    raw_data_in_night = await api_db.fetch_all(f"""
        SELECT device, COUNT(*) as count FROM missions m
        INNER JOIN devices d on d.id = m.device
        INNER JOIN factorymaps f on f.id = d.workshop
        WHERE (m.created_date BETWEEN :night_start AND :night_end) AND d.is_rescue = 0 AND f.name = :workshop_name
        GROUP BY device
        ORDER BY count DESC;
    """, {'workshop_name': workshop_name, 'night_start': night_start, 'night_end': night_end})

    recommend_devices_in_night: Dict[str, int] = {}
    for x in raw_data_in_night:
        recommend_devices_in_night[x[0]] = int(x[1])

    recommend_devices_in_day = {k: v for k, v in recommend_devices_in_day.items() if v >= WHITELIST_MINIMUM_OCCUR_COUNT}
    recommend_devices_in_night = {k: v for k, v in recommend_devices_in_night.items() if v >= WHITELIST_MINIMUM_OCCUR_COUNT}

    return recommend_devices_in_day, recommend_devices_in_night