import logging
from typing import List, Callable, Coroutine
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    UserShiftInfo,
    Mission,
    FactoryMap,
)
from fastapi.exceptions import HTTPException
from app.models.schema import UserCreate
from app.services.user import get_password_hash, create_user
from app.services.device import get_device_id
from fastapi import UploadFile
from datetime import datetime
import csv


async def process_csv_file(
    csv_file: UploadFile,
    callback: Callable[[List[str]], Coroutine],
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
                await callback(row)
            row_count += 1
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            400,
            f"raise an error when parsing csv file: {str(e)}, row count {row_count}",
        )


async def import_users(csv_file: UploadFile):
    """
    Improt user list form csv file
    """

    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    users: List[User] = []
    for row in reader:
        user = User(
            username=row[0],
            password_hash=get_password_hash(row[1]),
            full_name=row[2],
            expertises=row[3],
            is_active=row[4],
            is_admin=row[5],
        )
        users.append(user)

    await User.objects.bulk_create(users)


async def import_devices(csv_file: UploadFile, clear_all: bool = False):
    """
    Import device list from csv file.
    """

    async def process(row: List[str]) -> None:
        max_length = 8
        if len(row) != max_length:
            raise HTTPException(400, f"each row must be {max_length} columns long")

        workshop = await FactoryMap.objects.get(name=row[5])

        if row[2] != "rescue":
            # device_id = get_device_id(row[2], int(float(row[3])), row[4])
            device = await Device.objects.get_or_none(id=row[0])

            if device is None:
                device = await Device.objects.create(
                    id=row[0],
                    project=row[0],
                    process=int(float(1)),
                    line=int(float(row[3])),
                    device_name=row[4],
                    x_axis=float(row[6]),
                    y_axis=float(row[7]),
                    workshop=workshop,
                    is_rescue=False,
                )
            else:
                await device.update(
                    process=int(float(1)),
                    x_axis=float(row[6]),
                    y_axis=float(row[7]),
                    workshop=workshop,
                )
        else:
            # is rescue station
            device = await Device.objects.get_or_create(
                id=row[0],
                project=f"{row[3]}-{row[4]}",
                device_name=row[4],
                x_axis=float(row[6]),
                y_axis=float(row[7]),
                is_rescue=True,
                workshop=workshop,
            )

    if clear_all is True:
        await Device.objects.delete(each=True)

    await process_csv_file(csv_file, process)


async def import_employee_repair_experience_table(
    csv_file: UploadFile, clear_all: bool = False
):
    async def process(row: List[str]) -> None:
        if len(row) != 6:
            raise HTTPException(400, "each row must be 6 columns long")

        user = await User.objects.get_or_none(username=row[0])

        if user is None:
            user = await create_user(
                UserCreate(
                    username=row[0],
                    password="foxlink-password",
                    full_name=row[1],
                    expertises=[],
                )
            )

        project_names = row[2].split(",")

        try:
            devices = await Device.objects.filter(
                project__istartswith=row[2], device_name=row[3]
            ).all()
            for d in devices:
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
            arr = await Device.objects.filter(device_name=n).all()
            devices += arr

        shift_type = "Night" if row[6] == "1" else "Day"
        date_of_shift = datetime.strptime(row[5], "%Y-%m-%d")

        shift = await UserShiftInfo.objects.get_or_create(
            user=user, day_or_night=shift_type, shift_date=date_of_shift
        )
        await shift.devices.add(devices[0])

    await process_csv_file(csv_file, process)


async def import_employee_table(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        if len(row) != 2:
            raise HTTPException(400, "each row must be 2 columns long")
        user = User(
            id=row[0],
            username=row[0],
            full_name=row[1],
            password_hash=get_password_hash("foxlink"),
            expertises=[],
            is_active=True,
            is_admin=False,
        )
        await user.upsert()

    await process_csv_file(csv_file, process)


async def transform_events(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        max_length = 10
        if len(row) != max_length:
            raise HTTPException(400, f"each row must be {max_length} columns long")

        device_id = get_device_id(row[0], int(float(row[2])), row[3])
        device = await Device.objects.get_or_none(id=device_id)

        if device is None:
            return

        await Mission.objects.create(
            device=device,
            name="Mission",
            description=row[7],
            required_expertises=[],
            related_event_id=int(float(row[1])),
            is_cancel=False,
            event_start_date=datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S"),
            event_end_date=datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S"),
        )

    await process_csv_file(csv_file, process)

