from typing import List
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.core.database import User
from app.services.user import (
    get_users,
    create_user,
    get_password_hash,
    update_user,
    delete_user_by_id,
)
from app.services.auth import (
    get_current_active_user,
    verify_password,
    get_admin_active_user,
)
from app.models.schema import UserCreate, UserChangePassword, UserOut

router = APIRouter(prefix="/users")


@router.get("/", response_model=List[User], tags=["users"])
async def read_all_users(user: User = Depends(get_current_active_user)):
    users = await get_users()
    return users


@router.post("/", tags=["users"], status_code=201)
async def create_a_new_user(dto: UserCreate):
    return await create_user(dto)


@router.get("/info", response_model=UserOut, tags=["users"])
async def get_self_user_info(user: User = Depends(get_current_active_user)):
    return user


@router.post("/change-password", tags=["users"])
async def change_password(
    dto: UserChangePassword, user: User = Depends(get_current_active_user)
):
    if not verify_password(dto.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="The old password is not matched")

    await update_user(user.id, password_hash=get_password_hash(dto.new_password))


@router.delete("/{user_id}", tags=["users"])
async def delete_a_user_by_id(
    user_id: int, user: User = Depends(get_admin_active_user)
):
    await delete_user_by_id(user_id)
    return True

