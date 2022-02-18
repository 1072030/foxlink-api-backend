from fastapi import APIRouter
import datetime
from app.core.database import AuditActionEnum, AuditLogHeader
from typing import Optional

router = APIRouter(prefix="/logs")


@router.get("/", tags=["logs"])
async def get_logs(
    action: AuditActionEnum,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None,
):
    params = {
        "action": action.value,
        "created_date__gte": start_date,
        "created_date__lte": end_date,
    }
    params = {k: v for k, v in params.items() if v is not None}

    return await AuditLogHeader.objects.filter(**params).all() # type: ignore
