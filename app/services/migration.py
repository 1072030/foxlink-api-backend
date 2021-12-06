from typing import List, Callable, Coroutine, Optional, Any
from app.core.database import (
    User,
    Machine,
    Device,
    UserDeviceLevel,
    UserShiftInfo,
    Mission,
)
from fastapi.exceptions import HTTPException
from app.services.user import get_password_hash
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


async def import_machines(csv_file: UploadFile):
    """
    Improt machines list form csv file
    """
    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    try:
        machines: List[Machine] = []
        for row in reader:
            machine = Machine(name=row[0], manual=row[1])
            machines.append(machine)

        await Machine.objects.bulk_create(machines)
    except:
        raise HTTPException(400, "raise an error when parsing csv file")


async def import_devices(csv_file: UploadFile, clear_all: bool = False):
    """
    Import device list from csv file.
    """

    async def process(row: List[str]) -> None:
        max_length = 10
        if len(row) != max_length:
            raise HTTPException(400, f"each row must be {max_length} columns long")

        device_id = get_device_id(row[0], int(float(row[2])), row[3])
        device = await Device.objects.get_or_none(id=device_id)

        if device is None:
            device = await Device.objects.create(
                id=device_id,
                project=row[0],
                line=int(float(row[2])),
                device_name=row[3],
                x_axis=0,
                y_axis=0,
            )

        await Mission.objects.create(
            device=device,
            name="Mission",
            description=row[7],
            required_expertises=[],
            related_event_id=int(float(row[1])),
            is_cancel=False,
        )

    await process_csv_file(csv_file, process)


async def import_employee_repair_experience_table(
    csv_file: UploadFile, clear_all: bool = False
):
    async def process(row: List[str]) -> None:
        if len(row) != 6:
            raise HTTPException(400, "each row must be 3 columns long")

        level = UserDeviceLevel(user=int(row[0]), device=row[1], level=int(row[2]))
        await level.upsert()

    if clear_all:
        await UserDeviceLevel.objects.delete(each=True)

    process_csv_file(csv_file, process)


async def import_employee_shift_table(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        if len(row) != 4:
            raise HTTPException(400, "each row must be 4 columns long")

        shift_type = "Day" if int(row[2]) == 0 else "Night"
        date_of_shift = datetime.strptime(row[3], "%Y/%m/%d")

        shift = UserShiftInfo(
            user=int(row[0]),
            attend=bool(row[1]),
            day_or_night=shift_type,
            shift_date=date_of_shift,
        )
        await shift.upsert()

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
            device = await Device.objects.create(
                id=device_id,
                project=row[0],
                line=int(float(row[2])),
                device_name=row[3],
                x_axis=0,
                y_axis=0,
            )

        await Mission.objects.create(
            device=device,
            name="Mission",
            description=row[7],
            required_expertises=[],
            related_event_id=int(float(row[1])),
            is_cancel=False,
        )

    await process_csv_file(csv_file, process)

