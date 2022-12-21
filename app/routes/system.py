import logging
from app.log import LOGGER_NAME
from fastapi import APIRouter, Depends
import shutil
from app.services.auth import get_manager_active_user
from app.core.database import User

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(LOGGER_NAME)


@router.get("/space")
async def space_statistic(user: User = Depends(get_manager_active_user)) -> str:
    total, used, _ = shutil.disk_usage("/")
    return used/total
