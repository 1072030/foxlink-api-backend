from typing import Dict
from fastapi import APIRouter


router = APIRouter(prefix="/health")


@router.get("/", tags=["health"])
async def view_health() -> str:
    return "Health OK"
