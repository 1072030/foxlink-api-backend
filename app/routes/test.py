from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta

from ormar import NoMatch
from app.core.database import (
    CategoryPRI,
    Device,
    FactoryMap,
    Mission,
    MissionEvent,
    api_db,
)
import random

router = APIRouter(prefix="/test")

CRASH_MESSAGES = [
    "进料打码站故障",
    "PP搬运站故障",
    "扫码读取站故障",
    "出料反转站故障",
    "扫码重复异常",
    "扫码检查连线异常",
    "扫码格式错误",
    "house上料站故障",
    "Bracket组装站故障",
    "转盘下料站故障",
    "DD转盘站故障",
    "出料站故障",
    "tray盘站故障",
    "UV检测站故障",
    "供料站故障",
    "搬送站故障",
    "托盘站故障",
    "进料站故障",
    "搬送站故障",
    "CCD站故障",
    "产品翻转站故障",
    "扫码站故障",
    "排不良站画面",
    "包装搬送站故障",
    "1#包装站故障",
    "2#包装站故障",
]


@api_db.transaction()
@router.post("/missions", status_code=201, tags=["test"])
async def create_fake_mission(workshop_name: str):
    w = (
        await FactoryMap.objects.exclude_fields(["image", "map"])
        .filter(name=workshop_name)
        .get_or_none()
    )

    if w is None:
        raise HTTPException(status_code=404, detail="workshop is not found")

    all_device_ids = [x for x in w.related_devices if not x.startswith('rescue')]

    pick_device_id = None
    for device in all_device_ids:
        if await Mission.objects.filter(
            device=device, repair_end_date__isnull=True, is_cancel=False
        ).exists():
            continue
        else:
            pick_device_id = device
            break
            
    if pick_device_id is None:
        raise HTTPException(status_code=404, detail="no device is available")

    new_mission = await Mission.objects.create(
        device=pick_device_id, name="測試任務", description="測試任務", required_expertises=[]
    )

    while True:
        try:
            event = await MissionEvent.objects.create(
                mission=new_mission,
                event_id=random.randint(0, 99999999),
                table_name="test",
                category=random.randint(1, 200),
                message=random.sample(CRASH_MESSAGES, 1)[0],
                event_start_date=datetime.utcnow() + timedelta(hours=8),
            )
            break
        except Exception:
            continue

    return {
        "fake_mission_id": new_mission.id,
        "device_id": pick_device_id,
        "category": event.category,
        "message": event.message,
    }


@router.post("/missions/{mission_id}/done", status_code=200, tags=["test"])
async def mark_mission_as_done(mission_id: int):
    mission = (
        await Mission.objects.filter(id=mission_id)
        .select_related(["missionevents"])
        .get_or_none()
    )

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    for e in mission.missionevents:
        await e.update(
            done_verified=True, event_end_date=datetime.utcnow() + timedelta(hours=8),
        )

