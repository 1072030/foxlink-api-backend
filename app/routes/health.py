from typing import Dict
from fastapi import APIRouter, Depends


router = APIRouter()


@router.get("/api/health", tags=["health"])
async def view_health() -> str:
    return "Health OK"
