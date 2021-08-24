from typing import List, Optional
from fastapi.exceptions import HTTPException
from app.models.schema import UserCreate
from passlib.context import CryptContext
from app.core.database import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password)


async def get_users() -> List[User]:
    return await User.objects.all()


async def create_user(dto: UserCreate):
    pw_hash = get_password_hash(dto.password)
    new_dto = dto.dict()
    del new_dto["password"]
    new_dto["password_hash"] = pw_hash

    user = User(**new_dto)

    try:
        await user.save()
    except:
        raise HTTPException(status_code=400, detail="duplicate email in database")

    return


async def get_user_by_id(user_id: int) -> Optional[User]:
    user = await User.objects.filter(id=user_id).get_or_none()
    return user


async def get_user_by_email(email: str) -> Optional[User]:
    user = await User.objects.filter(email=email).get_or_none()
    return user


async def update_user(user_id: int, **kwargs):
    user = await get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    try:
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        await user.update(None, **filtered)
    except Exception as e:
        raise HTTPException(status_code=400, detail="cannot update user:" + str(e))

    return user


async def delete_user_by_id(user_id: int):
    affected_row = await User.objects.delete(id=user_id)

    if affected_row != 1:
        raise HTTPException(status_code=404, detail="user by this id is not found")
