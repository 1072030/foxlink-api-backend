from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.core.database import (
    Mission,
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
from app.services.mission import set_mission_by_rescue_position
from app.services.user import (
    check_user_begin_shift,
    get_user_summary,
    # create_user,
    get_password_hash,
    delete_user_by_badge,
    get_worker_attendances,
    get_users_overview,
    get_user_all_level_subordinates_by_badge,
    get_worker_mission_history,
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
    UserStatus,
    WorkerAttendance,
    WorkerStatusDto,
    WorkerStatus
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
    user = await User.objects.select_related("workshop").get(badge=user.badge)
    if user.workshop is None:
        workshop_name = "無"
    else:
        workshop_name = user.workshop.name

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
        summary=summary,
        workshop=workshop_name,
        change_pwd=user.change_pwd,
        work_time=total_mins,
        badge=user.badge,
        username=user.username,
        level=user.level,
        at_device=user.at_device.id if user.at_device != None else ""
    )


@router.get("/worker-attendance", response_model=List[WorkerAttendance], tags=["users"])
async def get_user_attendances(user: User = Depends(get_current_user)):
    return await get_worker_attendances(user.badge)


@router.get("/check-user-status", response_model=UserStatus, tags=["users"])
async def check_user_status(user: User = Depends(get_current_user)):
    userStatus = user.status
    work_type = ""
    mission = await Mission.objects.select_related(['worker', "device"]).filter(worker=user.badge, is_done=False).get_or_none()

    if mission is not None:
        work_type = "dispatch"
        if user.status == WorkerStatusEnum.notice.value:
            if mission.notify_recv_date is None:
                userStatus = WorkerStatusEnum.idle.value
            if mission.device.is_rescue is True:
                work_type = "rescue"

    return UserStatus(status=userStatus, work_type=work_type)


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


@router.get("/set-user-start-position", tags=["users"])
async def set_user_start_position(user: User = Depends(get_current_user)):
    try:
        # if(
        #     user.status == WorkerStatusEnum.idle.value and
        #     user.level == UserLevel.maintainer.value and
        #     not user.start_position == None and
        #     await check_user_just_login(user)
        # ):
        await set_mission_by_rescue_position(user, user.start_position)
    except:
        raise HTTPException(404, "The User don't need to set start position.")


@transaction
@router.post("/get-off-work", tags=["users"])
async def get_off_work(
    reason: LogoutReasonEnum, to_change_status: bool = True, user: User = Depends(get_current_user)
):
    if user.status != WorkerStatusEnum.idle.value and user.level == UserLevel.maintainer.value:
        raise HTTPException(404, 'You are not allow to logout except idle.')

    user.logout_date = get_ntz_now()
    user.current_UUID = "0"
    if (not user.level == UserLevel.admin.value):
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


@router.get("/subordinates", tags=["users"], response_model=List[WorkerStatusDto])
async def get_user_subordinates(user: User = Depends(get_manager_active_user)):
    return await get_user_all_level_subordinates_by_badge(user.badge)


@router.get("/mission-history", tags=["users"], response_model=List[MissionDto])
async def get_user_mission_history(user: User = Depends(get_current_user)):
    return await get_worker_mission_history(user.badge)


@router.get("/overview", tags=["users"], response_model=DayAndNightUserOverview)
async def get_all_users_overview(workshop_name: str, user: User = Depends(get_manager_active_user)):
    return await get_users_overview(workshop_name)
