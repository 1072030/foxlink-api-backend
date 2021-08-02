from typing import List, Optional
from pydantic.types import Json
from app.core.database import User
from fastapi.exceptions import HTTPException
from app.services.user import get_password_hash
from fastapi import UploadFile
from io import StringIO
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
            phone=row[3],
            expertises=row[4],
            is_active=row[5],
            is_admin=row[6],
        )
        users.append(user)

    await User.objects.bulk_create(users)
