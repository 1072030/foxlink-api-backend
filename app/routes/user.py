from typing import List
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.core.database import User, UserLevel, WorkerStatus, WorkerStatusEnum
from app.services.user import (
    get_users,
    create_user,
    get_password_hash,
    update_user,
    delete_user_by_username,
    update_user,
)
from app.services.auth import (
    get_current_active_user,
    verify_password,
    get_admin_active_user,
)
from app.models.schema import UserCreate, UserChangePassword, UserOut, UserPatch

router = APIRouter(prefix="/users")


@router.get("/", response_model=List[UserOut], tags=["users"])
async def read_all_users(user: User = Depends(get_admin_active_user)):
    users = await get_users()
    return [UserOut(**user.dict()) for user in users]


@router.post("/", tags=["users"], status_code=201)
async def create_a_new_user(
    dto: UserCreate, user: User = Depends(get_admin_active_user)
):
    return await create_user(dto)


@router.get("/info", response_model=UserOut, tags=["users"])
async def get_user_himself_info(user: User = Depends(get_current_active_user)):
    return UserOut(**user.dict())


@router.post("/change-password", tags=["users"])
async def change_password(
    dto: UserChangePassword, user: User = Depends(get_current_active_user)
):
    if not verify_password(dto.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="The old password is not matched")

    await update_user(user.username, password_hash=get_password_hash(dto.new_password))


@router.get("/offwork", tags=["users"])
async def get_offwork(user: User = Depends(get_current_active_user)):
    if user.level == UserLevel.maintainer.value:
        await WorkerStatus.objects.filter(worker=user).update(
            status=WorkerStatusEnum.leave.value
        )


@router.patch("/{username}", tags=["users"])
async def update_user_information(
    username: str, dto: UserPatch, user: User = Depends(get_current_active_user)
):
    if user.is_admin is False and username != user.username:
        raise HTTPException(
            status_code=400,
            detail="You are not allowed to change other user's information",
        )

    return await update_user(username, **dto.dict())


@router.delete("/{username}", tags=["users"])
async def delete_a_user_by_username(
    username: str, user: User = Depends(get_admin_active_user)
):
    await delete_user_by_username(username)
    return True

