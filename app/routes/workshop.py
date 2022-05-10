from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, File, UploadFile, Form
from ormar import NoMatch
from app.core.database import FactoryMap, User
from app.services.auth import get_manager_active_user
from app.services.workshop import create_workshop_device_qrcode
from urllib.parse import quote

router = APIRouter(prefix="/workshop")


@router.get("/", response_model=List[Optional[FactoryMap]], tags=["workshop"])
async def get_workshop_info_by_query(
    workshop_id: Optional[int] = None,
    workshop_name: Optional[str] = None,
    user: User = Depends(get_manager_active_user),
):
    query = {"id": workshop_id, "name": workshop_name}
    query = {k: v for k, v in query.items() if v is not None}
    return await FactoryMap.objects.filter(**query).all()  # type: ignore


@router.get("/list", tags=["workshop"], description="Get a list of all workshop's name")
async def get_workshop_list(user: User = Depends(get_manager_active_user)):
    workshop = await FactoryMap.objects.fields(["name"]).all()
    return [w.name for w in workshop]


@router.get(
    "/qrcode",
    tags=["workshop"],
    description="Download all device qrcode in workshop",
    response_class=Response,
    responses={
        200: {
            "content": {"application/x-zip-compressed": {}},
            "description": "Return a zip file containing device qrcode in png format.",
        },
        404: {"description": "workshop is not found",},
    },
)
async def get_workshop_device_qrcode(
    workshop_name: str, user: User = Depends(get_manager_active_user)
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


@router.post(
    "/{workshop_name}/image",
    tags=["workshop"],
    description="Upload workshop image",
    status_code=201,
)
async def upload_workshop_image(
    workshop_name: str,
    image: UploadFile = File(..., description="要上傳的廠區圖（.png)", media_type="image/png"),
    user: User = Depends(get_manager_active_user)
):
    raw_image = await image.read()

    try:
        await FactoryMap.objects.filter(name=workshop_name).update(image=raw_image)
    except NoMatch:
        raise HTTPException(status_code=404, detail="the workshop is not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=repr(e))


@router.get(
    "/{workshop_name}/image",
    tags=["workshop"],
    description="Get workshop image",
    status_code=200,
)
async def get_workshop_image(workshop_name: str, user: User = Depends(get_manager_active_user)):
    w = (
        await FactoryMap.objects.filter(name=workshop_name)
        .exclude_fields(["map", "related_devices"])
        .get_or_none()
    )

    if w is None:
        raise HTTPException(404, "the workshop is not found")

    return Response(
        w.image,
        media_type="image/png"
    )
