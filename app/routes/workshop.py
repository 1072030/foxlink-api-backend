from typing import List, Optional
from fastapi import APIRouter, Depends, Response
from app.core.database import FactoryMap, User
from app.services.auth import get_admin_active_user
from app.services.workshop import create_workshop_device_qrcode
from urllib.parse import quote

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


@router.get(
    "/qrcode",
    tags=["workshop"],
    description="Download all device qrcode in workshop",
    response_class=Response,
    responses={
        200: {
            "content": {"application/x-zip-compressed": {}},
            "description": "Return a zip file containing device qrcode in png format.",
        }
    },
)
async def get_workshop_device_qrcode(
    workshop_name: str, user: User = Depends(get_admin_active_user)
):
    zip_bytes = await create_workshop_device_qrcode(workshop_name)

    return Response(
        zip_bytes,
        media_type="application/x-zip-compressed",
        headers={
            "Content-Disposition": "attachment; filename*=utf-8''{}.zip".format(
                quote(workshop_name + "-QRCodes")
            )
        },
    )

