from fastapi import APIRouter
import datetime
from app.core.database import AuditActionEnum, AuditLogHeader
from typing import Optional

router = APIRouter(prefix="/logs")


@router.get("/", tags=["logs"])
async def get_logs(
    action: Optional[AuditActionEnum] = None,
    limit: int = 20,
    page: int = 0,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None,
):
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    if page <= 0:
        raise ValueError("limit must be greater than 0")

    params = {
        "created_date__gte": start_date,
        "created_date__lte": end_date,
    }

    if action is not None:
        params["action"] = action.value  # type: ignore

    params = {k: v for k, v in params.items() if v is not None}

    return await AuditLogHeader.objects.filter(**params).paginate(page, limit).order_by("-created_date").all()  # type: ignore
