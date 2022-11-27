from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.core.database import (
    get_ntz_now,
    AuditActionEnum,
    LogoutReasonEnum,
    User,
    UserLevel,
    FactoryMap,
    WorkerStatusEnum,
    AuditLogHeader,
    api_db,
    transaction
)
from app.services.user import (
    # get_user_all_level_subordinates_by_badge,
    get_user_summary,
    # create_user,
    get_password_hash,
    delete_user_by_badge,
    get_worker_attendances,
)
from app.services.auth import (
    set_device_UUID,
    get_current_user,
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
        users = await User.objects.select_related("workshop").all()
    else:
        users = (
            await User.objects.select_related("workshop")
            .filter(location__name=workshop_name)
            .exclude_fields(["location__map", "location__related_devices"])
            .all()
        )

    return [
        UserOut(
            workshop=user.workshop.name if user.workshop is not None else "無",
            **user.dict()
        )
        for user in users
    ]


@router.get("/info", response_model=UserOutWithWorkTimeAndSummary, tags=["users"])
async def get_user_himself_info(user: User = Depends(get_current_user)):
    first_login_timestamp = user.login_date

    if user.workshop is None:
        workshop_name = "無"
    else:
        workshop_name = (
            await FactoryMap.objects.filter(id=user.workshop.id)
            .fields(["id", "name"])
            .get()
        ).name

    at_device = "無"

    if user.at_device is not None:
        at_device = user.at_device.id

    if first_login_timestamp is not None:
        total_mins = (
            get_ntz_now() - first_login_timestamp
        ).total_seconds() / 60
    else:
        total_mins = 0

    summary = await get_user_summary(user.badge)

    return UserOutWithWorkTimeAndSummary(
        at_device=at_device,
        summary=summary,
        workshop=workshop_name,
        work_time=total_mins,
        **user.dict()
    )


@router.get("/worker-attendance", response_model=List[WorkerAttendance], tags=["users"])
async def get_user_attendances(user: User = Depends(get_current_user)):
    return await get_worker_attendances(user.badge)


@router.post("/change-password", tags=["users"])
async def change_password(
    dto: UserChangePassword, user: User = Depends(get_current_user)
):
    if not verify_password(dto.old_password, user.password_hash):
        raise HTTPException(
            status_code=401, detail="The old password is not matched")

    await user.update(
        password_hash=get_password_hash(dto.new_password),
        change_pwd=True
    )


@transaction
@router.post("/get-off-work", tags=["users"])
async def get_off_work(
    reason: LogoutReasonEnum, to_change_status: bool = True, user: User = Depends(get_current_user)
):
    user.logout_date = get_ntz_now()

    if(not user.level == UserLevel.admin.value):
        user.status = WorkerStatusEnum.leave.value

    await user.update()

    await AuditLogHeader.objects.create(
        user=user,
        table_name="users",
        action=AuditActionEnum.USER_LOGOUT.value,
        description=reason.value,
    )


@router.patch("/{badge}", tags=["users"])
async def update_user_information(
    badge: str, dto: UserPatch, user: User = Depends(get_current_user)
):
    if user.level < UserLevel.manager.value:
        raise HTTPException(401, "You do not have permission to do this")

    return await user.update(**dto.dict())


@router.delete("/{badge}", tags=["users"])
async def delete_a_user_by_badge(
    badge: str, user: User = Depends(get_admin_active_user)
):
    await delete_user_by_badge(badge)
    return True
