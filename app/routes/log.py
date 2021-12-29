from fastapi import APIRouter
import datetime
from app.core.database import AuditActionEnum, AuditLogHeader

router = APIRouter(prefix="/logs")


@router.get("/", tags=["logs"])
async def get_logs(
    action: AuditActionEnum,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
):
    return await AuditLogHeader.objects.filter(action=action).all()
