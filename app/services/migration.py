from typing import List, Optional
from app.core.database import User, Machine, Device
from fastapi.exceptions import HTTPException
from app.services.user import get_password_hash
from fastapi import UploadFile
import csv


async def import_users(csv_file: UploadFile):
    """
    Improt user list form csv file
    """

    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    users: List[User] = []
    for row in reader:
        user = User(
            email=row[0],
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


async def import_devices(csv_file: UploadFile):
    """
    Import device list from csv file.
    """
    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    try:
        devices: List[Device] = []
        for row in reader:
            if len(row) != 7:
                raise HTTPException(400, "each row must be 7 columns long")
            device = Device(
                id=row[0],
                process=row[1],
                machine=row[2],
                line=row[3],
                device=row[4],
                x_axis=row[5],
                y_axis=row[6],
            )
            devices.append(device)

        await Device.objects.bulk_create(devices)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(400, "raise an error when parsing csv file: " + str(e))

async def import_employee_repair_experience_table(csv_file: UploadFile):
    pass