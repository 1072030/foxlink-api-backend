import logging
import math
from typing import List, Callable, Coroutine, Dict, Any
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    UserLevel,
    UserShiftInfo,
    FactoryMap,
    CategoryPRI,
    database,
)
from fastapi.exceptions import HTTPException
from app.models.schema import UserCreate
from app.services.user import get_password_hash, create_user
from app.services.device import get_device_id
from fastapi import UploadFile
from datetime import datetime
import csv
import pandas as pd
from app.dispatch import data_convert

data_converter = data_convert()


@database.transaction()
async def process_csv_file(
    csv_file: UploadFile,
    callback: Callable[..., Coroutine],
    params: Dict[str, Any] = {},
    ignore_header: bool = True,
):
    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    is_met_header = False
    row_count = 0

    try:
        for row in reader:
            if not is_met_header and ignore_header:
                is_met_header = True
            else:
                await callback(row, **params)
            row_count += 1
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            400,
            f"raise an error when parsing csv file: {str(e)}, row count {row_count}",
        )


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


async def import_employee_repair_experience_table(
    csv_file: UploadFile, clear_all: bool = False
):
    async def process(row: List[str]) -> None:
        if len(row) != 6:
            raise HTTPException(400, "each row must be 6 columns long")

        try:
            devices = await Device.objects.filter(
                project__istartswith=row[2], device_name=row[3]
            ).all()

            user = await User.objects.get_or_none(username=row[0])

            for d in devices:
                if user is None:
                    user = await create_user(
                        UserCreate(
                            username=row[0],
                            password="foxlink",
                            full_name=row[1],
                            expertises=[],
                            workshop=d.workshop.id,
                            level=UserLevel.maintainer.value,
                        )
                    )

                level = UserDeviceLevel(
                    user=user, device=d, shift=bool(row[4]), level=int(row[5])
                )
                await level.upsert()
        except Exception as e:
            raise HTTPException(
                400, f"raise an error when parsing csv file: {str(e)}",
            )

    if clear_all:
        await UserDeviceLevel.objects.delete(each=True)

    await process_csv_file(csv_file, process)


async def import_employee_shift_table(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        if len(row) != 8:
            raise HTTPException(400, "each row must be 8 columns long")

        user = await User.objects.get_or_none(full_name=row[0])

        if user is None:
            logging.error(f"user {row[0]} not found")
            return

        device_names = row[4].split(",")
        devices: List[Device] = []

        for n in device_names:
            arr = await Device.objects.filter(device_name=row[4]).all()
            devices += arr

        shift_type = "Night" if row[6] == "1" else "Day"
        date_of_shift = datetime.strptime(row[5], "%Y-%m-%d")

        shift = await UserShiftInfo.objects.get_or_create(
            user=user, day_or_night=shift_type, shift_date=date_of_shift
        )

        await shift.devices.add(devices[0])  # type: ignore

    await process_csv_file(csv_file, process)


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
async def import_factory_worker_infos(excel_file: UploadFile):
    raw_excel: bytes = await excel_file.read()
    data = data_converter.fn_factory_worker_info(raw_excel)
    print(data)

    for index, row in data.iterrows():
        worker = await User.objects.filter(username=row["worker_id"]).get_or_none()
        workshop = await FactoryMap.objects.filter(name="第九車間").get()

        if worker is None:
            worker = await User.objects.create(
                username=row["worker_id"],
                full_name=row["worker_name"],
                password_hash=get_password_hash("foxlink"),
                expertises=[],
                is_active=True,
                is_admin=False,
                location=workshop,
                level=row["job"],
            )

        # if worker is not maintainer(維修人員), we shouldn't create a device exp. for them.
        if row["job"] != UserLevel.maintainer.value:
            continue

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

