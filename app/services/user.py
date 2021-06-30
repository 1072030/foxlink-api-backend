from typing import List
from fastapi.exceptions import HTTPException
from app.models.schema import UserCreate
from passlib.context import CryptContext
from app.core.database import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password)


async def get_users() -> List[User]:
    users = await User.objects.select_all().all()
    return users


async def create_user(dto: UserCreate):
    pw_hash = get_password_hash(dto.password)

    user = User(
        email=dto.email, password_hash=pw_hash, phone=dto.phone, full_name=dto.full_name
    )

    try:
        await user.save()
    except:
        raise HTTPException(status_code=400, detail="duplicate email in database")

    return user


async def get_user_by_id(user_id: int) -> User:
    user = await User.objects.filter(id=user_id).get()
    return user


async def get_user_by_email(email: str) -> User:
    user = await User.objects.filter(email=email).get()
    return user


async def update_user(user_id: int, **kwargs):
    user = await get_user_by_id(user_id)

    try:
        await user.update(None, **kwargs)
    except:
        raise HTTPException(status_code=400, detail="cannot update user")

    return user
