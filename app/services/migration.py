import math
from typing import Dict, List, Optional
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


def generate_device_id(project: str, line: int, device_name: str) -> str:
    return f"{project}@{int(line)}@{device_name}"


@database.transaction()
async def import_devices(excel_file: UploadFile, clear_all: bool = False):
    if clear_all is True:
        await Device.objects.delete(each=True)

    raw_excel: bytes = await excel_file.read()
    frame = pd.read_excel(raw_excel, sheet_name=0)

    create_device_bulk: List[Device] = []
    for index, row in frame.iterrows():
        workshop = await FactoryMap.objects.get_or_none(name=row["workshop"])

        if workshop is None:
            workshop = await FactoryMap.objects.create(
                name=row["workshop"], related_devices="[]", map="[]"
            )

        is_rescue: bool = row["project"] == "rescue"

        if is_rescue:
            device_id = f"{row['project']}@{row['workshop']}@{row['device_name']}"
        else:
            device_id = generate_device_id(
                row["project"], row["line"], row["device_name"]
            )
        frame.at[index, "id"] = device_id

        device = Device(
            id=device_id,
            project=row["project"],
            process=row["process"] if type(row["process"]) is str else None,
            device_name=row["device_name"],
            line=int(row["line"]) if math.isnan(row["line"]) == False else None,
            x_axis=float(row["x_axis"]),
            y_axis=float(row["y_axis"]),
            sop_link=row["sop_link"],
            is_rescue=is_rescue,
            workshop=workshop,
        )
        create_device_bulk.append(device)

    await Device.objects.bulk_create(create_device_bulk)
    # calcuate factroy map matrix
    await calcuate_factory_layout_matrix(frame)


# 匯入 Device's Category & Priority
@database.transaction()
async def import_workshop_events(excel_file: UploadFile):
    raw_excel: bytes = await excel_file.read()
    data = data_converter.fn_proj_eventbooks(excel_file.filename, raw_excel)

    for index, row in data.iterrows():
        devices = await Device.objects.filter(
            project__iexact=row["project"],
            device_name__iexact=row["Device_Name"].replace(" ", "_"),
        ).all()

        p = await CategoryPRI.objects.create(
            category=row["Category"], message=row["MESSAGE"], priority=row["优先顺序"],
        )

        for d in devices:
            await p.devices.add(d)  # type: ignore


async def calcuate_factory_layout_matrix(frame: pd.DataFrame):
    data = data_converter.fn_factorymap(frame)
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
        factory_worker_info, worker_info = data_converter.fn_factory_worker_info(
            excel_file.filename, raw_excel
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=repr(e))

    full_name_mapping: Dict[str, str] = {}
    create_user_bulk: List[User] = []
    for index, row in factory_worker_info.iterrows():
        workshop = (
            await FactoryMap.objects.filter(name=row["workshop"])
            .fields(["id", "name"])
            .get_or_none()
        )

        if workshop is None:
            raise HTTPException(
                status_code=400, detail=f"unknown workshop name: {row['workshop']}"
            )

        full_name_mapping[row["worker_name"]] = str(row["worker_id"])
        worker = await User.objects.get_or_none(username=row["worker_id"])

        # superior_id: Optional[str] = None
        # if row["員工名字"] != row["負責人"]:
        #     superior_id = str(
        #         worker_info[worker_info["員工名字"] == row["負責人"]]["員工工號"].item()
        #     )

        if (
            worker is None
            and len(
                [u for u in create_user_bulk if u.username == str(row["worker_id"])]
            )
            == 0
        ):
            worker = User(
                username=str(row["worker_id"]),
                full_name=row["worker_name"],
                password_hash=get_password_hash("foxlink"),
                location=workshop.id,
                is_active=True,
                expertises=[],
                level=row["job"],
            )
            create_user_bulk.append(worker)
        # else:
        #     await worker.update(
        #         full_name=row["員工名字"], level=row["職務"], location=workshop.id,
        #     )

    await User.objects.bulk_create(create_user_bulk)

    for index, row in factory_worker_info.iterrows():
        workshop = (
            await FactoryMap.objects.filter(name=row["workshop"])
            .fields(["id", "name"])
            .get()
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
                    device=d,
                    user=row["worker_id"],
                    superior=full_name_mapping.get(row["superior"]),
                    shift=row["shift"],
                    level=row["level"],
                )
            )
        await UserDeviceLevel.objects.bulk_create(bulk)

