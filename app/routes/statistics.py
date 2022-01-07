from typing import List, Any
from fastapi import APIRouter

from app.services.statistics import get_top_most_crashed_devices

router = APIRouter(prefix="/stats")


@router.get("/", response_model=List[Any], tags=["statistics"])
async def get_top_crashed_devices(limit: int):
    result = await get_top_most_crashed_devices(limit)
    return result
