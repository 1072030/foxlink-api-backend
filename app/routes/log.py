from fastapi import APIRouter
import datetime
from app.core.database import LogCategoryEnum, Log

router = APIRouter(prefix="/logs")


@router.get("/", tags=["logs"])
async def get_logs(
    category: LogCategoryEnum,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
):
    data = await Log.objects.filter(category=category).all()
