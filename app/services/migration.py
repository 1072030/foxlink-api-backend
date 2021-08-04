from typing import List, Optional
from app.core.database import User, Machine
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
