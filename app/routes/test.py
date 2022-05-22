from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from app.core.database import CategoryPRI, Device, FactoryMap, Mission, MissionEvent, database
import random

router = APIRouter(prefix="/test")

@database.transaction()
@router.post("/missions", status_code=201, tags=["test"])
async def create_fake_mission(workshop_name: str):
    w = await FactoryMap.objects.exclude_fields(['image', 'map']).filter(name=workshop_name).get_or_none()

    if w is None:
        raise HTTPException(status_code=404, detail="workshop is not found")

    pick_device_id = random.randint(0, len(w.related_devices) - 1)

    random_category = await CategoryPRI.objects.filter(
        devices__id=pick_device_id
    ).first()

    new_mission = await Mission.objects.create(device=pick_device_id, name="測試任務")

    await MissionEvent.objects.create(
        mission=new_mission,
        event_id=0,
        table_name="test",
        category=random_category.category,
        message=random_category.message,
        event_start_date=datetime.utcnow() + timedelta(hours=8),
    )

    return {
        "fake_mission_id": new_mission.id,
        "device_id": pick_device_id,
        "category": random_category.category,
        "message": random_category.message,
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
            done_verified=True,
            event_end_date=datetime.utcnow() + timedelta(hours=8),
        )

