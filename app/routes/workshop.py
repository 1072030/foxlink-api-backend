from typing import List, Optional
from fastapi import APIRouter, Depends
from app.core.database import FactoryMap, User
from app.services.auth import get_admin_active_user

router = APIRouter(prefix="/workshop")


@router.get("/", response_model=List[Optional[FactoryMap]], tags=["workshop"])
async def get_workshop_info_by_query(
    workshop_id: Optional[int] = None,
    workshop_name: Optional[str] = None,
    user: User = Depends(get_admin_active_user),
):
    query = {"id": workshop_id, "name": workshop_name}
    query = {k: v for k, v in query.items() if v is not None}
    return await FactoryMap.objects.filter(**query).all()  # type: ignore

async def get_workshop_device_qrcode(workshop_name: str, user: User = Depends(get_admin_active_user)):
    ...
