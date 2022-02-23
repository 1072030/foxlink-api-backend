from typing import List, Any
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.statistics import (
    get_top_most_crashed_devices,
    get_login_users_percentage_today,
    get_top_most_reject_mission_employee,
)

router = APIRouter(prefix="/stats")


class Stats(BaseModel):
    top_most_crashed_devices: List[Any]
    top_most_reject_mission_employee: List[Any]
    login_users_percentage_today: float


@router.get("/", response_model=Stats, tags=["statistics"])
async def get_overall_statistics():
    limit = 10

    top_devices = await get_top_most_crashed_devices(limit)
    login_users_percentage = await get_login_users_percentage_today()
    top_mission_reject_employees = await get_top_most_reject_mission_employee(limit)

    return Stats(
        top_most_crashed_devices=top_devices,
        login_users_percentage_today=login_users_percentage,
        top_most_reject_mission_employee=top_mission_reject_employees,
    )
