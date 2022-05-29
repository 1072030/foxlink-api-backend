import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from fastapi.exceptions import HTTPException
from ormar import or_, and_
from app.models.schema import (
    DayAndNightUserOverview,
    DeviceExp,
    SubordinateOut,
    UserCreate,
    UserOverviewOut,
)
from passlib.context import CryptContext
from app.core.database import (
    AuditActionEnum,
    AuditLogHeader,
    LogValue,
    Mission,
    User,
    UserDeviceLevel,
    WorkerStatus,
    database,
)
from app.models.schema import DeviceDto, MissionDto
from app.services.device import get_device_by_id

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password)


async def get_users() -> List[User]:
    return await User.objects.all()


async def create_user(dto: UserCreate) -> User:
    pw_hash = get_password_hash(dto.password)
    new_dto = dto.dict()
    del new_dto["password"]
    new_dto["password_hash"] = pw_hash

    user = User(**new_dto)

    try:
        return await user.save()
    except Exception as e:
        raise HTTPException(status_code=400, detail="cannot add user:" + str(e))


async def get_user_by_username(username: str) -> Optional[User]:
    user = await User.objects.filter(username=username).get_or_none()
    return user


async def update_user(username: str, **kwargs):
    user = await get_user_by_username(username)

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


async def delete_user_by_username(username: str):
    affected_row = await User.objects.delete(username=username)

    if affected_row != 1:
        raise HTTPException(status_code=404, detail="user by this id is not found")


async def get_user_first_login_time_today(username: str) -> Optional[datetime]:
    """
    Get a employee's first login record past 12 hours (today)
    If the employee has not been logined in today, return None
    """
    past_12_hours = datetime.utcnow() - timedelta(hours=12)

    try:
        first_login_record = (
            await AuditLogHeader.objects.filter(
                action=AuditActionEnum.USER_LOGIN.value,
                user=username,
                created_date__gte=past_12_hours,
            )
            .order_by("created_date")
            .first()
        )
        return first_login_record.created_date
    except Exception:
        return None


async def get_worker_mission_history(username: str) -> List[MissionDto]:
    missions = (
        await Mission.objects.filter(assignees__username=username)
        .select_related(["device", "workshop"])
        .exclude_fields(["workshop__map", "workshop__related_devices", "workshop__image"])
        .order_by("-created_date")
        .limit(10)
        .all()
    )

    return [MissionDto.from_mission(x) for x in missions]


async def get_user_subordinates_by_username(username: str):
    result = await database.fetch_all(
        """
        SELECT DISTINCT u.username, u.full_name, ws.at_device, ws.status, udl.shift, ws.dispatch_count, ws.last_event_end_date, mu.mission as mission_id, (UTC_TIMESTAMP() - m2.created_date) as mission_duration FROM worker_status ws
        LEFT JOIN missions_users mu ON mu.id = (
            SELECT mu2.id FROM missions m
            INNER JOIN missions_users mu2
            ON mu2.user = ws.worker
            WHERE m.repair_end_date IS NULL AND m.is_cancel = False
            LIMIT 1
        )
        LEFT JOIN missions m2 ON m2.id = mu.mission
        LEFT JOIN users u ON u.username = ws.worker
        LEFT JOIN userdevicelevels AS udl ON udl.user = ws.worker
        WHERE udl.superior = :superior;
        """,
        values={"superior": username},
    )

    return [
        SubordinateOut(
            worker_id=x["username"],
            worker_name=x["full_name"],
            at_device=x["at_device"],
            shift=x["shift"],
            status=x["status"],
            total_dispatches=x["dispatch_count"],
            last_event_end_date=x["last_event_end_date"],
            mission_duration=x["mission_duration"],
        )
        for x in result
    ]


async def move_user_to_position(username: str, device_id: str):
    user, device = await asyncio.gather(
        get_user_by_username(username), get_device_by_id(device_id)
    )

    if user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    if device is None:
        raise HTTPException(
            status_code=404, detail="the device with this id is not found"
        )

    try:
        worker_status = await WorkerStatus.objects.filter(worker=user).get()
        original_at_device = (
            worker_status.at_device.id
            if worker_status.at_device is not None
            else "None"
        )

        log, _ = await asyncio.gather(
            AuditLogHeader.objects.create(
                table_name="worker_status",
                record_pk=device_id,
                action=AuditActionEnum.USER_MOVE_POSITION.value,
                user=user,
            ),
            worker_status.update(at_device=device),
        )

        await LogValue.objects.create(
            log_header=log.id,
            field_name="at_device",
            previous_value=original_at_device,
            new_value=device_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="cannot update user's position: " + str(e)
        )


async def is_user_working_on_mission(username: str) -> bool:

    the_user = await User.objects.filter(username=username).get_or_none()

    if the_user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    # if worker has already working on other mission, skip
    if (
        await Mission.objects.filter(
            and_(
                # left: user still working on a mission, right: user is not accept a mission yet.
                or_(
                    and_(
                        repair_start_date__isnull=False, repair_end_date__isnull=True,
                    ),
                    and_(repair_start_date__isnull=True, repair_end_date__isnull=True),
                ),
                assignees__username=username,
                is_cancel=False,
            )
        ).count()
        > 0
    ):
        return True

    return False


async def get_users_overview() -> DayAndNightUserOverview:
    users = await User.objects.select_related("location").all()

    day_overview: List[UserOverviewOut] = []
    night_overview: List[UserOverviewOut] = []
    shift_types = [0, 1]

    for s in shift_types:
        for u in users:
            overview = UserOverviewOut(
                username=u.username,
                full_name=u.full_name,
                level=u.level,
                shift=s,
                experiences=[],
            )

            if u.location is not None:
                overview.workshop = u.location.name

            device_levels = (
                await UserDeviceLevel.objects.select_related(["superior", "device"])
                .filter(user=u, shift=s)
                .all()
            )

            if len(device_levels) == 0:
                continue

            for dl in device_levels:
                if overview.superior is None and dl.superior is not None:
                    overview.superior = dl.superior.full_name

                overview.experiences.append(
                    DeviceExp(
                        project=dl.device.project,
                        process=dl.device.process,
                        line=dl.device.line,
                        exp=dl.level,
                    )
                )

            if s == 0:
                day_overview.append(overview)
            else:
                night_overview.append(overview)

    return DayAndNightUserOverview(day_shift=day_overview, night_shift=night_overview)
