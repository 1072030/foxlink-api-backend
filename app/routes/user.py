from typing import List
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.core.database import (
    AuditActionEnum,
    LogoutReasonEnum,
    User,
    UserLevel,
    WorkerStatus,
    WorkerStatusEnum,
    AuditLogHeader,
    database,
)
from app.services.user import (
    get_users,
    create_user,
    get_password_hash,
    update_user,
    delete_user_by_username,
    get_worker_mission_history,
    update_user,
)
from app.services.auth import (
    get_current_active_user,
    verify_password,
    get_admin_active_user,
)
from app.models.schema import (
    UserCreate,
    UserChangePassword,
    UserOut,
    UserPatch,
    MissionDto,
)

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

    await update_user(
        user.username,
        password_hash=get_password_hash(dto.new_password),
        is_changepwd=True,
    )


@database.transaction()
@router.post("/get-off-work", tags=["users"])
async def get_off_work(
    reason: LogoutReasonEnum, user: User = Depends(get_current_active_user)
):
    if user.level == UserLevel.maintainer.value:
        await WorkerStatus.objects.filter(worker=user).update(
            status=WorkerStatusEnum.leave.value
        )

    await AuditLogHeader.objects.create(
        user=user, table_name="users", action=AuditActionEnum.USER_LOGOUT.value, description=reason.value,
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


@router.get("/mission-history", tags=["users"], response_model=List[MissionDto])
async def get_user_mission_history(user: User = Depends(get_current_active_user)):
    return await get_worker_mission_history(user.username)
