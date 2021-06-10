from typing import List
from fastapi.exceptions import HTTPException
from passlib.context import CryptContext
from app.models.schema import User, UserCreate
from app.core.database import users, database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password)


async def get_users() -> List[User]:
    query = users.select()
    return await database.fetch_all(query)


async def create_user(dto: UserCreate):
    pw_hash = get_password_hash(dto.password)
    query = users.insert(None).values(
        email=dto.email,
        password_hash=pw_hash,
        phone=dto.phone,
        full_name=dto.full_name,
    )

    try:
        last_record_id = await database.execute(query)
    except:
        raise HTTPException(status_code=400, detail="duplicate email in database")

    return {"id": last_record_id}


async def get_user_by_id(user_id: int) -> User:
    query = users.select().where(users.c.id == user_id)
    return await database.fetch_one(query)


async def get_user_by_email(email: str) -> User:
    query = users.select().where(users.c.email == email)
    return await database.fetch_one(query)


async def update_user(user_id: int, **kwargs):
    query = users.update(None).where(users.c.id == user_id).values(kwargs)

    try:
        result = await database.execute(query)
    except:
        raise HTTPException(status_code=400, detail="cannot update user")

    return result
