import cv2
import numpy as np
from typing import List, Mapping, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, File, UploadFile
from ormar import NoMatch
from app.core.database import FactoryMap, User, api_db
from app.models.schema import DeviceStatus, DeviceStatusEnum
from app.services.auth import get_current_user, get_manager_active_user
from app.services.workshop import create_workshop_device_qrcode, get_all_devices_status,get_factory_file_name
from urllib.parse import quote
from app.utils.utils import change_file_name


router = APIRouter(prefix="/workshop")


@router.get("/", response_model=List[Optional[FactoryMap]], tags=["workshop"])
async def get_workshop_info_by_query(
    workshop_id: Optional[int] = None,
    workshop_name: Optional[str] = None,
    user: User = Depends(get_manager_active_user),
):
    query = {"id": workshop_id, "name": workshop_name}
    query = {k: v for k, v in query.items() if v is not None}
    return await FactoryMap.objects.filter(**query).exclude_fields(["image", "map"]).all()  # type: ignore

@router.get("/filename", tags=["workshop"])
def get_workshop_file_name():
    return get_factory_file_name()


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
        404: {"description": "workshop is not found", },
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
    user: User = Depends(get_manager_active_user),
):
    raw_image = await image.read()

    try:
        temp = await FactoryMap.objects.filter(name=workshop_name).get()
        await temp.update(image=raw_image)
        change_file_name(image.filename,"images")
    except NoMatch:
        raise HTTPException(status_code=404, detail="the workshop is not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=repr(e))


@router.get(
    "/{workshop_name}/image",
    tags=["workshop"],
    description="Get workshop image",
    status_code=200,
    response_class=Response,
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "Return workshop's image in png format.",
        },
        404: {"description": "workshop is not found", },
    },
)
async def get_workshop_image(
    workshop_name: str, user: User = Depends(get_current_user()),
    max_img_value: Optional[int] = None,
    navigate_device_id: Optional[str] = None,
    navigate_worker_id: Optional[str] = None
):
    w = (
        await FactoryMap.objects.filter(name=workshop_name)
        .exclude_fields(["map", "related_devices"])
        .get_or_none()
    )

    if w is None:
        raise HTTPException(404, "the workshop is not found")

    if w.image is None:
        raise HTTPException(404, "the workshop image is not yet uploaded")

    # process
    """
    Define color
    """
    WORKING = (0, 255, 0)  # green 0
    REPAIRING = (0, 140, 255)  # orange 1
    HALT = (0, 0, 255)  # red 2
    POINT_SCALE = 120

    if navigate_worker_id or navigate_device_id:
        all_devices_status = await get_all_devices_status(workshop_name, is_rescue=True) + await get_all_devices_status(workshop_name, is_rescue=False)
    else:
        all_devices_status = await get_all_devices_status(workshop_name, False)

    img_buffer_numpy = np.frombuffer(w.image, dtype=np.uint8)
    img = cv2.imdecode(img_buffer_numpy, 1)
    height, width, _ = img.shape

    if navigate_device_id or navigate_worker_id:
        for i, obj in enumerate(all_devices_status):
            if obj.device_id == navigate_device_id:
                color = (0, 0, 255)
                if obj.x_axis >= width or obj.y_axis >= height:
                    raise HTTPException(404, "(x, y) is out of range")
                else:
                    cv2.circle(
                        img,
                        (int(obj.x_axis), int(obj.y_axis)),
                        int(height / POINT_SCALE),
                        color,
                        -1,
                    )
            if obj.device_id == navigate_worker_id:
                color = (255, 0, 0)
                if obj.x_axis >= width or obj.y_axis >= height:
                    raise HTTPException(404, "(x, y) is out of range")
                else:
                    cv2.circle(
                        img,
                        (int(obj.x_axis), int(obj.y_axis)),
                        int(height / POINT_SCALE),
                        color,
                        -1,
                    )
    else:
        for i, obj in enumerate(all_devices_status):
            if obj.x_axis >= width or obj.y_axis >= height:
                raise HTTPException(404, "(x, y) is out of range")
            color = (255, 255, 255)
            if obj.status == DeviceStatusEnum.working:
                color = WORKING
            elif obj.status == DeviceStatusEnum.repairing:
                color = REPAIRING
            else:
                color = HALT

            cv2.circle(
                img,
                (int(obj.x_axis), int(obj.y_axis)),
                int(height / POINT_SCALE),
                color,
                -1,
            )

    if max_img_value:
        bigger_side = max(height, width)
        if max_img_value == 0 or max_img_value > bigger_side:
            raise HTTPException(404, "maxImgValue too large or equal to zero")

        scale_rate = max_img_value / bigger_side
        n_h, n_w = int(height * scale_rate), int(width * scale_rate)
        img = cv2.resize(img, (n_w, n_h), interpolation=cv2.INTER_AREA)

    _, im_buf_arr = cv2.imencode(".png", img)

    return Response(im_buf_arr.tobytes(), media_type="image/png")


@router.get(
    "/{workshop_name}/projects",
    tags=["workshop"],
    description="Get project names under a workshop",
    response_model=List[str],
    status_code=200,
)
async def get_project_names_by_project(
    workshop_name: str, user: User = Depends(get_manager_active_user)
):
    w = (
        await FactoryMap.objects.filter(name=workshop_name)
        .exclude_fields(["map", "related_devices"])
        .get_or_none()
    )

    if w is None:
        raise HTTPException(404, "the workshop is not found")

    project_names: List[Mapping[str, str]] = await api_db.fetch_all(
        "SELECT DISTINCT d.project FROM devices d INNER JOIN factory_maps f ON d.workshop = :workshop_id WHERE d.project != 'rescue';",
        {"workshop_id": w.id},
    )

    return [item.project for item in project_names]  # type: ignore


@router.get(
    "/{workshop_name}/device_status",
    tags=["workshop"],
    response_model=List[DeviceStatus],
)
async def get_all_devices_status_in_workshop(
    workshop_name: str, user: User = Depends(get_manager_active_user)
):
    return await get_all_devices_status(workshop_name)
