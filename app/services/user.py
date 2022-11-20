import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import aiohttp
from fastapi.exceptions import HTTPException
from ormar import NoMatch, or_, and_
from app.env import EMQX_PASSWORD, EMQX_USERNAME, MQTT_BROKER, TIMEZONE_OFFSET, WEEK_START
from app.models.schema import (
    DayAndNightUserOverview,
    DeviceExp,
    UserCreate,
    UserOverviewOut,
    WorkerAttendance,
    WorkerStatusDto,
    WorkerSummary,
)
from passlib.context import CryptContext
from app.core.database import (
    AuditActionEnum,
    AuditLogHeader,
    LogValue,
    Mission,
    ShiftType,
    User,
    UserDeviceLevel,
    UserLevel,
    WhitelistDevice,
    WorkerStatus,
    WorkerStatusEnum,
    api_db,
)
from app.models.schema import MissionDto
from app.services.device import get_device_by_id
from app.utils.utils import get_current_shift_time_interval

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
        raise HTTPException(
            status_code=400, detail="cannot add user:" + str(e))


async def check_user_workstatus(username: str):
    workerStatus = await WorkerStatus.objects.filter(worker=username).get_or_none()
    # if workerStatus.status != WorkerStatusEnum.idle.value:
    #     raise HTTPException(
    #         status_code=404, detail="You are not allow to logout."
    #     )


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

        if filtered.get("password") is not None:
            filtered["password_hash"] = get_password_hash(filtered["password"])
            del filtered["password"]

        await user.update(None, **filtered)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="cannot update user:" + repr(e))

    return user


async def delete_user_by_username(username: str):
    affected_row = await User.objects.delete(username=username)

    if affected_row != 1:
        raise HTTPException(
            status_code=404, detail="user by this id is not found")


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
        .select_related(["device", "device__workshop"])
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .order_by("-created_date")
        .limit(10)
        .all()
    )

    return [MissionDto.from_mission(x) for x in missions]


async def get_subordinates_list_by_username(username: str):
    the_user = await User.objects.filter(username=username).get_or_none()

    if the_user is None:
        raise HTTPException(404, "the user with this id is not found")

    async def get_subsordinates_list(username: str) -> List[str]:
        result = await api_db.fetch_all("""
        SELECT DISTINCT user FROM userdevicelevels u 
        WHERE u.superior = :superior
        """, {'superior': username})

        return [row[0] for row in result]

    all_subsordinates = await get_subsordinates_list(username)

    while True:
        temp = []
        for name in all_subsordinates:
            t2 = await get_subsordinates_list(name)

            for x in t2:
                if x not in temp and x not in all_subsordinates:
                    temp.append(x)
        if len(temp) == 0:
            break
        all_subsordinates.extend(temp)
    return all_subsordinates


async def get_user_all_level_subordinates_by_username(username: str):
    subsordinates = await get_subordinates_list_by_username(username)
    promises = [get_worker_status(name) for name in subsordinates]
    result = await asyncio.gather(*promises)
    return [x for x in result if x is not None]


async def move_user_to_position(username: str, device_id: str):
    user = await get_user_by_username(username)
    device = await get_device_by_id(device_id)

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

        log = await AuditLogHeader.objects.create(
            table_name="worker_status",
            record_pk=device_id,
            action=AuditActionEnum.USER_MOVE_POSITION.value,
            user=user,
        )

        await worker_status.update(
            at_device=device, last_event_end_date=datetime.utcnow()
        )

        await LogValue.objects.create(
            log_header=log.id,
            field_name="at_device",
            previous_value=original_at_device,
            new_value=device_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="cannot update user's position: " + repr(e)
        )


async def get_user_working_mission(username: str) -> Optional[Mission]:
    the_user = await User.objects.filter(username=username).get_or_none()

    if the_user is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    try:
        mission = await Mission.objects.select_related(['device']).filter(
            and_(
                # left: user still working on a mission, right: user is not accept a mission yet.
                or_(
                    and_(
                        repair_start_date__isnull=False, repair_end_date__isnull=True,
                    ),
                    and_(repair_start_date__isnull=True,
                         repair_end_date__isnull=True),
                ),
                assignees__username=username,
                is_cancel=False,
            )
        ).order_by("-id").first()
        return mission
    except NoMatch:
        return None


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
                    and_(repair_start_date__isnull=True,
                         repair_end_date__isnull=True),
                ),
                assignees__username=username,
                is_cancel=False,
            )
        ).count()
        > 0
    ):
        return True

    return False


async def get_users_overview(workshop_name: str) -> DayAndNightUserOverview:
    users = await User.objects.select_related("location").filter(location__name=workshop_name).all()

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
                        device_name=dl.device.device_name,
                        line=dl.device.line,
                        exp=dl.level,
                    )
                )

            if s == 0:
                day_overview.append(overview)
            else:
                night_overview.append(overview)

    return DayAndNightUserOverview(day_shift=day_overview, night_shift=night_overview)


async def get_user_summary(username: str) -> Optional[WorkerSummary]:
    worker = await User.objects.filter(username=username).get_or_none()

    if worker is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    if worker.level != UserLevel.maintainer.value:
        return None

    total_accepted_count_this_month = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk)
        FROM auditlogheaders
        WHERE `action` = '{AuditActionEnum.MISSION_ACCEPTED.value}'
        AND user='{username}'
        AND MONTH(`created_date` + HOUR({TIMEZONE_OFFSET})) = MONTH(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}))
        """,
    )

    total_accepted_count_this_week = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk) FROM auditlogheaders
        WHERE `action` = '{AuditActionEnum.MISSION_ACCEPTED.value}'
        AND user='{username}'
        AND YEARWEEK(`created_date` + HOUR({TIMEZONE_OFFSET}), {WEEK_START}) = YEARWEEK(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}), {WEEK_START})
        """,
    )

    total_rejected_count_this_month = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk)
        FROM auditlogheaders
        WHERE `action` = '{AuditActionEnum.MISSION_REJECTED.value}'
        AND user='{username}'
        AND MONTH(`created_date` + HOUR({TIMEZONE_OFFSET})) = MONTH(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}))
        """,
    )

    total_rejected_count_this_week = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk) FROM auditlogheaders
        WHERE `action` = '{AuditActionEnum.MISSION_REJECTED.value}'
        AND user='{username}'
        AND YEARWEEK(`created_date` + HOUR({TIMEZONE_OFFSET}), {WEEK_START}) = YEARWEEK(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}), {WEEK_START})
        """,
    )

    return WorkerSummary(
        total_accepted_count_this_month=total_accepted_count_this_month[0][0],
        total_accepted_count_this_week=total_accepted_count_this_week[0][0],
        total_rejected_count_this_month=total_rejected_count_this_month[0][0],
        total_rejected_count_this_week=total_rejected_count_this_week[0][0],
    )


async def get_worker_attendances(username: str) -> List[WorkerAttendance]:
    if not await User.objects.filter(username=username).exists():
        return []

    worker_attendances: List[WorkerAttendance] = []

    user_login_days_this_month = await api_db.fetch_all(
        f"""
        SELECT DATE(ADDTIME(loginrecord.created_date, '{TIMEZONE_OFFSET}:00')) `day`, ADDTIME(loginrecord.created_date, '{TIMEZONE_OFFSET}:00') as `time`, loginrecord.description
        FROM auditlogheaders loginrecord,
        (
            SELECT action, MIN(created_date) min_login_date , DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
            FROM auditlogheaders
            WHERE `action` = '{AuditActionEnum.USER_LOGIN.value}' AND user='{username}'
            GROUP BY DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
        ) min_login
        WHERE loginrecord.`action` = '{AuditActionEnum.USER_LOGIN.value}' AND loginrecord.created_date = min_login.min_login_date;
        """,
    )

    user_logout_days_this_month = await api_db.fetch_all(
        f"""
        SELECT DATE(ADDTIME(logoutrecord.created_date, '{TIMEZONE_OFFSET}:00')) `day`, ADDTIME(logoutrecord.created_date, '{TIMEZONE_OFFSET}:00') as `time`, logoutrecord.description
        FROM auditlogheaders logoutrecord,
        (
            SELECT action, MAX(created_date) max_logout_date , DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
            FROM auditlogheaders
            WHERE `action` = '{AuditActionEnum.USER_LOGOUT.value}' AND user='{username}'
            GROUP BY DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
        ) max_logout
        WHERE logoutrecord.`action` = '{AuditActionEnum.USER_LOGOUT.value}' AND logoutrecord.created_date = max_logout.max_logout_date;
        """,
    )

    for login_record in user_login_days_this_month:
        a = WorkerAttendance(
            date=login_record[0], login_datetime=login_record[1])
        for logout_record in user_logout_days_this_month:
            if login_record[0] == logout_record[0]:
                a.logout_datetime = logout_record[1]
                a.logout_reason = logout_record[2]
                break
        worker_attendances.append(a)

    return worker_attendances


async def check_user_connected(username: str) -> Tuple[bool, Optional[str]]:
    """
    Get client connection status from EMQX API.

    Returned:
        - connected: bool - True if connected, False otherwise
        - ip_address: str - if user is connected, this field represents the IP address of the client
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://{MQTT_BROKER}:18083/api/v4/clients/{username}",
            auth=aiohttp.BasicAuth(login=EMQX_USERNAME,
                                   password=EMQX_PASSWORD),
        ) as resp:
            if resp.status != 200:
                return False, None

            try:
                content = await resp.json()

                if len(content["data"]) == 0:
                    return False, None

                return content["data"][0]["connected"], content["data"][0]["ip_address"]
            except:
                return False, None


async def get_user_shift_type(username: str) -> ShiftType:
    """取得員工的班別"""

    user = await get_user_by_username(username)

    if user is None:
        raise HTTPException(404, 'the user is not found')

    if not await UserDeviceLevel.objects.filter(user=user).exists():
        raise HTTPException(404, 'no shift existed for this user')

    if await UserDeviceLevel.objects.filter(user=user, shift=ShiftType.day.value).exists():
        return ShiftType.day
    else:
        return ShiftType.night


async def is_worker_in_whitelist(username: str) -> bool:
    return await WhitelistDevice.objects.select_related(['workers']).filter(workers__username=username).exists()


async def is_worker_in_device_whitelist(username: str, device_id: str) -> bool:
    return await WhitelistDevice.objects.select_related(['workers']).filter(workers__username=username, device=device_id).exists()


async def get_worker_status(username: str) -> Optional[WorkerStatusDto]:
    s = (
        await WorkerStatus.objects.filter(worker=username)
        .select_related(["worker", 'at_device'])
        .get_or_none()
    )

    if s is None:
        return None

    shift_start, shift_end = get_current_shift_time_interval()

    total_start_count = await api_db.fetch_val(
        f"""
        SELECT COUNT(DISTINCT mu.mission) FROM missions_users mu 
        INNER JOIN missions m ON m.id = mu.mission
        INNER JOIN auditlogheaders a ON a.record_pk = m.id 
        WHERE mu.user = :username AND a.action = 'MISSION_STARTED' AND (a.created_date BETWEEN :shift_start AND :shift_end);
        """,
        {'username': username, 'shift_start': shift_start, 'shift_end': shift_end},
    )

    item = WorkerStatusDto(
        worker_id=username,
        worker_name=s.worker.full_name,
        status=s.status,
        last_event_end_date=s.last_event_end_date,
        total_dispatches=total_start_count,
    )

    item.at_device = s.at_device.id if s.at_device is not None else None
    item.at_device_cname = s.at_device.device_cname if s.at_device is not None else None

    mission = await get_user_working_mission(username)
    if s.status in [WorkerStatusEnum.working.value, WorkerStatusEnum.moving.value, WorkerStatusEnum.notice.value] and mission is not None:
        item.mission_duration = mission.mission_duration.total_seconds()  # type: ignore

        if mission.repair_duration is not None and not mission.device.is_rescue:
            item.repair_duration = mission.repair_duration.total_seconds()

        if s.status == WorkerStatusEnum.moving.value:
            item.at_device = mission.device.id
            item.at_device_cname = mission.device.device_cname

    return item
