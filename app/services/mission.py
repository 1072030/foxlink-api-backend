import logging
from typing import List, Dict, Any, Optional
from app.core.database import Machine, Mission
from fastapi.exceptions import HTTPException
from app.models.schema import MissionCreate, MissionUpdate
from app.services.machine import get_machine_by_id
import sys


async def get_missions() -> List[Mission]:
    missions = await Mission.objects.all()
    return missions


async def get_mission_by_id(id: int) -> Optional[Mission]:
    item = await Mission.objects.get_or_none(id=id)
    return item


async def update_mission_by_id(id: int, dto: MissionUpdate):
    mission = await get_mission_by_id(id)
    if mission is None:
        raise HTTPException(
            status_code=400, detail="cannot get a mission by the id",
        )

    updateDict: Dict[str, Any] = {}
    try:
        if dto.name is not None:
            updateDict["name"] = dto.name

        if dto.machine_id is not None:
            machine = await get_machine_by_id(dto.machine_id)
            updateDict["machine"] = machine

        if dto.description is not None:
            updateDict["description"] = dto.description

        await mission.update(None, **updateDict)
    except:
        raise HTTPException(status_code=400, detail="cannot update mission")

    return True


async def create_mission(dto: MissionCreate):
    try:
        machine = await get_machine_by_id(dto.machine_id)
        created_mission = await Mission.objects.create(
            machine=machine, name=dto.name, description=dto.description
        )
    except:
        logging.error(sys.exc_info())
        raise HTTPException(
            status_code=400, detail="raise a error when inserting mission into databse",
        )

    return created_mission

