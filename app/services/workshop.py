import io
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from fastapi.exceptions import HTTPException
from app.core.database import FactoryMap
from zipfile import ZipFile
from PIL import ImageDraw, ImageFont

font = ImageFont.truetype("./data/NotoSansTC-Regular.otf", 16)


async def get_all_factory_maps():
    return await FactoryMap.objects.all()


async def get_factory_map_by_id(factory_map_id: int):
    return await FactoryMap.objects.filter(id=factory_map_id).get_or_none()


async def get_factory_map_by_name(factory_map_name: str):
    return await FactoryMap.objects.filter(name=factory_map_name).get_or_none()


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

            qr = qrcode.QRCode(
                version=2, error_correction=ERROR_CORRECT_M, box_size=10, border=4,
            )
            qr.add_data(device_id)
            qr.make(fit=True)
            img = qr.make_image()

            ImageDraw.Draw(img).text(
                (10, 0), device_id, fill=0, font=font
            )  # add device_id at top-left corner

            img_bytes = io.BytesIO()
            img.save(img_bytes, format=img.format)
            zip_file.writestr(f"{device_id}.png", img_bytes.getvalue())

    return zip_io.getvalue()
