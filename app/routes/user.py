import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.core.database import (
    AuditActionEnum,
    LogoutReasonEnum,
    User,
    UserLevel,
    FactoryMap,
    WorkerStatus,
    WorkerStatusEnum,
    AuditLogHeader,
    database,
)
from app.services.user import (
    get_user_all_level_subordinates_by_username,
    get_user_first_login_time_today,
    get_user_summary,
    create_user,
    get_password_hash,
    get_users_overview,
    update_user,
    delete_user_by_username,
    get_worker_mission_history,
    update_user,
    get_worker_attendances,
)
from app.services.auth import (
    get_current_active_user,
    get_manager_active_user,
    verify_password,
    get_admin_active_user,
)
from app.models.schema import (
    DayAndNightUserOverview,
    UserCreate,
    UserChangePassword,
    UserOut,
    UserOutWithWorkTimeAndSummary,
    UserPatch,
    MissionDto,
    WorkerAttendance,
    WorkerStatusDto,
)

router = APIRouter(prefix="/users")


@router.get("/", response_model=List[UserOut], tags=["users"])
async def read_all_users(
    user: User = Depends(get_admin_active_user), workshop_name: Optional[str] = None
):
    if workshop_name is None:
        users = await User.objects.select_related("location").all()
    else:
        users = (
            await User.objects.select_related("location")
            .filter(location__name=workshop_name)
            .exclude_fields(["location__map", "location__related_devices"])
            .all()
        )

    return [
        UserOut(
            workshop=user.location.name if user.location is not None else "無",
            **user.dict()
        )
        for user in users
    ]


@router.post("/", tags=["users"], status_code=201)
async def create_a_new_user(
    dto: UserCreate, user: User = Depends(get_admin_active_user)
):
    return await create_user(dto)


@router.get("/info", response_model=UserOutWithWorkTimeAndSummary, tags=["users"])
async def get_user_himself_info(user: User = Depends(get_current_active_user)):
    first_login_timestamp = await get_user_first_login_time_today(user.username)

    if user.location is None:
        workshop_name = "無"
    else:
        workshop_name = (
            await FactoryMap.objects.filter(id=user.location.id)
            .fields(["id", "name"])
            .get()
        ).name

    at_device = "無"
    worker_status = (
        await WorkerStatus.objects.select_related(["at_device"])
        .filter(worker=user)
        .get_or_none()
    )
    if worker_status is not None and worker_status.at_device is not None:
        at_device = worker_status.at_device.id

    if first_login_timestamp is not None:
        total_mins = (
            datetime.datetime.utcnow() - first_login_timestamp
        ).total_seconds() / 60
    else:
        total_mins = 0

    summary = await get_user_summary(user.username)

    return UserOutWithWorkTimeAndSummary(
        at_device=at_device,
        summary=summary,
        workshop=workshop_name,
        work_time=total_mins,
        **user.dict()
    )


@router.get("/worker-attendance", response_model=List[WorkerAttendance], tags=["users"])
async def get_user_attendances(user: User = Depends(get_current_active_user)):
    return await get_worker_attendances(user.username)


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
    reason: LogoutReasonEnum, to_change_status: bool = True, user: User = Depends(get_current_active_user)
):
    if to_change_status and await WorkerStatus.objects.filter(worker=user.username).exists():
        await WorkerStatus.objects.filter(worker=user.username).update(
            status=WorkerStatusEnum.leave.value
        )

    await AuditLogHeader.objects.create(
        user=user,
        table_name="users",
        action=AuditActionEnum.USER_LOGOUT.value,
        description=reason.value,
    )


@router.patch("/{username}", tags=["users"])
async def update_user_information(
    username: str, dto: UserPatch, user: User = Depends(get_current_active_user)
):
    if user.level < UserLevel.manager.value:
        raise HTTPException(401, "You do not have permission to do this")

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


@router.get("/subordinates", tags=["users"], response_model=List[WorkerStatusDto])
async def get_user_subordinates(user: User = Depends(get_manager_active_user)):
    return await get_user_all_level_subordinates_by_username(user.username)


@router.get("/overview", tags=["users"], response_model=DayAndNightUserOverview)
async def get_all_users_overview(workshop_name: str, user: User = Depends(get_manager_active_user)):
    return await get_users_overview(workshop_name)
