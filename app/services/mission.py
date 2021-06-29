from typing import List
from app.core.database import Mission
from fastapi.exceptions import HTTPException


async def get_missions() -> List[Mission]:
    missions = await Mission.objects.select_all().all()
    return missions


async def create_mission(mission: Mission):
    try:
        await mission.save()
    except:
        raise HTTPException(
            status_code=400, detail="raise a error when inserting mission into databse"
        )

    return mission

