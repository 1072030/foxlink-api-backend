import io
import qrcode
from app.core.database import FactoryMap
from zipfile import ZipFile


async def get_all_factory_maps():
    return await FactoryMap.objects.all()


async def get_factory_map_by_id(factory_map_id: int):
    return await FactoryMap.objects.filter(id=factory_map_id).get_or_none()


async def get_factory_map_by_name(factory_map_name: str):
    return await FactoryMap.objects.filter(name=factory_map_name).get_or_none()


async def create_workshop_device_qrcode(workshop_name: str):
    workshop = await get_factory_map_by_name(workshop_name)

    if workshop is None:
        raise Exception("workshop is not found")

    zip_io = io.BytesIO()
    with ZipFile(zip_io, "w") as zip_file:
        for device_id in workshop.related_devices:
            # we don't need to create rescue station qrcode.
            if 'rescue' in device_id:
                continue

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(device_id)
            qr.make(fit=True)
            img = qr.make_image()
            img_bytes = io.BytesIO()
            img.save(img_bytes, format=img.format)
            zip_file.writestr(f"{device_id}.png", img_bytes.getvalue())

    return zip_io.getvalue()
