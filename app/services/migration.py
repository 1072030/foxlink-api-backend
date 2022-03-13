import math
from typing import List, Optional
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    FactoryMap,
    CategoryPRI,
    database,
)
from fastapi.exceptions import HTTPException
from app.services.user import get_password_hash
from fastapi import UploadFile
import pandas as pd
from foxlink_dispatch.dispatch_20220313_v2 import data_convert

data_converter = data_convert()


@database.transaction()
async def import_devices(excel_file: UploadFile, clear_all: bool = False):
    if clear_all is True:
        await Device.objects.delete(each=True)

    raw_excel: bytes = await excel_file.read()
    frame = pd.read_excel(raw_excel, sheet_name=0)

    bulk: List[Device] = []
    for index, row in frame.iterrows():
        workshop = await FactoryMap.objects.get_or_none(name=row["workshop"])

        if workshop is None:
            workshop = await FactoryMap.objects.create(
                name=row["workshop"], related_devices="[]", map="[]"
            )

        is_rescue: bool = row["project"] == "rescue"

        device = Device(
            id=row["id"],
            project=row["project"],
            process=row["process"] if type(row["process"]) is str else None,
            device_name=row["device_name"],
            line=int(row["line"]) if math.isnan(row["line"]) == False else None,
            x_axis=float(row["x_axis"]),
            y_axis=float(row["y_axis"]),
            is_rescue=is_rescue,
            workshop=workshop,
        )

        bulk.append(device)

    await Device.objects.bulk_create(bulk)
    # calcuate factroy map matrix
    await calcuate_factory_layout_matrix(raw_excel)


# 匯入 Device's Category & Priority
@database.transaction()
async def import_workshop_events(excel_file: UploadFile):
    raw_excel: bytes = await excel_file.read()
    data = data_converter.fn_proj_eventbooks(excel_file.filename, raw_excel)

    for index, row in data.iterrows():
        devices = await Device.objects.filter(
            project__iexact=row["project"],
            device_name=row["Device_Name"].replace(" ", "_"),
        ).all()

        p = await CategoryPRI.objects.create(
            category=row["Category"], message=row["MESSAGE"], priority=row["优先顺序"],
        )

        for d in devices:
            await p.devices.add(d)  # type: ignore


async def calcuate_factory_layout_matrix(raw_excel: bytes):
    data = data_converter.fn_factorymap(raw_excel)
    matrix: List[List[float]] = []

    for index, row in data.iterrows():
        matrix.append(row.values.tolist())

    await FactoryMap.objects.filter(name="第九車間").update(
        related_devices=data.columns.values.tolist(), map=matrix
    )


@database.transaction()
async def import_factory_worker_infos(workshop_name: str, excel_file: UploadFile):
    raw_excel: bytes = await excel_file.read()

    try:
        factory_woker_info, worker_info = data_converter.fn_factory_worker_info(
            excel_file.filename, raw_excel
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=repr(e))

    create_user_bulk = []
    update_user_bulk = []
    for index, row in worker_info.iterrows():
        workshop = (
            await FactoryMap.objects.filter(name=row["車間"])
            .fields(["id", "name"])
            .get_or_none()
        )

        if workshop is None:
            raise HTTPException(
                status_code=400, detail=f"unknown workshop name: {row['車間']}"
            )

        worker = await User.objects.get_or_none(username=row["員工工號"])

        superior_id: Optional[str] = None
        if row["員工名字"] != row["負責人"]:
            superior_id = worker_info[worker_info["員工名字"] == row["負責人"]]["員工工號"].item()

        if worker is None:
            worker = User(
                username=row["員工工號"],
                full_name=row["員工名字"],
                password_hash=get_password_hash("foxlink"),
                location=workshop.id,
                is_active=True,
                expertises=[],
                level=row["職務"],
                shift=row["班別"],
                superior=superior_id,
            )
            create_user_bulk.append(worker)
        else:
            worker.full_name = row["員工名字"]
            worker.level = row["職務"]
            worker.shift = row["班別"]
            worker.location = workshop
            worker.superior = superior_id
            update_user_bulk.append(worker)

    await User.objects.bulk_create(create_user_bulk)
    await User.objects.bulk_update(update_user_bulk)

    for index, row in factory_woker_info.iterrows():
        worker = await User.objects.filter(username=row["worker_id"]).get_or_none()

        if worker is None:
            worker = await User.objects.create(
                username=row["worker_id"],
                full_name=row["worker_name"],
                password_hash=get_password_hash("foxlink"),
                expertises=[],
                is_active=True,
                is_admin=False,
                location=workshop,
                shift=row["shift"],
                level=row["job"],
            )

        related_devices = await Device.objects.filter(
            workshop=workshop.id,
            process=row["process"],
            project__iexact=row["project"],
            device_name=row["device_name"],
        ).all()

        bulk = []
        for d in related_devices:
            bulk.append(
                UserDeviceLevel(
                    device=d, user=worker, shift=row["shift"], level=row["level"]
                )
            )
        await UserDeviceLevel.objects.bulk_create(bulk)

