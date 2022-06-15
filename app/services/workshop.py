import io
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from fastapi.exceptions import HTTPException
from app.core.database import Device, FactoryMap, Mission
from zipfile import ZipFile
from PIL import ImageDraw, ImageFont
from typing import List
from app.models.schema import DeviceStatus, DeviceStatusEnum

font = ImageFont.truetype("./data/NotoSansTC-Regular.otf", 14)




async def get_all_factory_maps():
    return await FactoryMap.objects.all()


async def get_factory_map_by_id(factory_map_id: int):
    return await FactoryMap.objects.filter(id=factory_map_id).get_or_none()


async def get_factory_map_by_name(factory_map_name: str):
    return await FactoryMap.objects.filter(name=factory_map_name).get_or_none()


async def get_all_devices_status(workshop_name: str, is_rescue=False):
    workshop = await get_factory_map_by_name(workshop_name)
    if workshop is None:
        raise HTTPException(404, "workshop is not found")

    device_status_arr: List[DeviceStatus] = []
    devices = await Device.objects.filter(workshop=workshop, is_rescue=is_rescue).all()

    for d in devices:
        related_missions = (
            await Mission.objects.filter(
                device=d, is_cancel=False, repair_end_date__isnull=True
            )
            .select_related(["assignees"])
            .order_by("-created_date")
            .all()
        )

        device_status = DeviceStatus(
            device_id=d.id,
            x_axis=d.x_axis,
            y_axis=d.y_axis,
            status=DeviceStatusEnum.working,
        )

        if len(related_missions) == 0:
            device_status.status = DeviceStatusEnum.working
        else:
            m = related_missions[0]
            if len(m.assignees) > 0:
                device_status.status = DeviceStatusEnum.repairing
            else:
                device_status.status = DeviceStatusEnum.halt

        device_status_arr.append(device_status)

    return device_status_arr


async def create_workshop_device_qrcode(workshop_name: str):
    workshop = await get_factory_map_by_name(workshop_name)

    if workshop is None:
        raise HTTPException(404, "workshop is not found")

    zip_io = io.BytesIO()
    with ZipFile(zip_io, "w") as zip_file:
        for device_id in workshop.related_devices:
            # we don't need to create rescue station qrcode.
            # if "rescue" in device_id:
            #     continue

            split_text = device_id.split("@")

            qr = qrcode.QRCode(
                version=2, error_correction=ERROR_CORRECT_M, box_size=10, border=6,
            )
            qr.add_data(device_id)
            qr.make(fit=True)
            img = qr.make_image()

            # add device_id at top-left corner
            if split_text[0] == "rescue":
                ImageDraw.Draw(img).text(
                    (10, 0),
                    f"車間：{split_text[1]}\n救援站編號：{split_text[2]}",
                    fill=0,
                    font=font,
                )
            else:
                ImageDraw.Draw(img).text(
                    (10, 0),
                    f"Project: {split_text[0]} Line: {split_text[1]}\nDevice Name: {split_text[2]}",
                    fill=0,
                    font=font,
                )

            img_bytes = io.BytesIO()
            img.save(img_bytes, format=img.format)
            zip_file.writestr(f"{device_id}.png", img_bytes.getvalue())

    return zip_io.getvalue()
