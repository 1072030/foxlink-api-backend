import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import aiohttp
from fastapi.exceptions import HTTPException
from ormar import NoMatch, or_, and_
from app.env import (
    EMQX_PASSWORD,
    EMQX_USERNAME,
    MQTT_BROKER,
    TIMEZONE_OFFSET,
    WEEK_START,
    PWD_SCHEMA,
    PWD_SALT
)
from app.models.schema import (
    DayAndNightUserOverview,
    DeviceExp,
    UserCreate,
    UserOverviewOut,
    WorkerAttendance,
    WorkerStatusDto,
    WorkerStatus,
    WorkerSummary,
)
from passlib.context import CryptContext
from app.core.database import (
    get_ntz_now,
    AuditActionEnum,
    Device,
    AuditLogHeader,
    FactoryMap,
    Mission,
    ShiftType,
    User,
    UserDeviceLevel,
    UserLevel,
    WhitelistDevice,
    WorkerStatusEnum,
    api_db,
)
from app.models.schema import MissionDto
from app.mqtt import MQTT_Client
from app.services.device import get_device_by_id
from app.utils.utils import get_current_shift_time_interval, get_current_shift_details


pwd_context = CryptContext(schemes=[PWD_SCHEMA], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password, salt=PWD_SALT, rounds=10000)


async def get_users() -> List[User]:
    return await User.objects.all()


# async def create_user(dto: UserCreate) -> User:
#     pw_hash = get_password_hash(dto.password)
#     new_dto = dto.dict()
#     del new_dto["password"]
#     new_dto["password_hash"] = pw_hash

#     user = User(**new_dto)

#     try:
#         return await user.save()
#     except Exception as e:
#         raise HTTPException(
#             status_code=400, detail="cannot add user:" + str(e))


async def get_worker_by_badge(
    badge,
    select_fields: List[str] = [
        "workshop",
        "superior",
        "at_device",
        "start_position"
    ]
) -> Optional[User]:
    worker = (
        await User.objects
        .filter(badge=badge)
        .select_related(
            select_fields
        )
        .exclude_fields(
            FactoryMap.heavy_fields("workshop")
        )
        .get_or_none()
    )

    return worker


async def delete_user_by_badge(badge: str):
    affected_row = await User.objects.delete(badge=badge)

    if affected_row != 1:
        raise HTTPException(
            status_code=404, detail="user by this id is not found")


async def check_user_begin_shift(user: User) -> Optional[bool]:
    """
    Check whether the user belongs to current shift and has not start the shift.
    """
    try:
        shift, start, end = await get_current_shift_details()
        return (user.shift.id == shift.value and not start < user.shift_beg_date < end)
    except Exception as e:
        print(e)
        return None


async def get_worker_mission_history(badge: str) -> List[MissionDto]:
    missions = (
        await Mission.objects.filter(worker__badge=badge)
        .select_related(["device", "device__workshop"])
        .exclude_fields(
            FactoryMap.heavy_fields("device__workshop")
        )
        .order_by("-created_date")
        .limit(10)
        .all()
    )

    return [MissionDto.from_mission(x) for x in missions]


async def get_user_working_mission(worker: User) -> Optional[Mission]:
    try:
        mission = (
            await Mission.objects
            .filter(
                and_(
                    # left: user still working on a mission, right: user is not accept a mission yet.
                    or_(
                        and_(repair_beg_date__isnull=False,
                             repair_end_date__isnull=True),
                        and_(repair_beg_date__isnull=True,
                             repair_end_date__isnull=True),
                    ),
                    worker__badge=worker.badge,
                    is_done=False
                )
            )
            .select_related("device")
            .order_by("-id")
            .first()
        )
        return mission
    except NoMatch:
        return None


async def get_worker_mission_history(username: str) -> List[MissionDto]:
    missions = (
        await Mission.objects.filter(worker__badge=username)
        .select_related(["device", "device__workshop", "events"])
        .exclude_fields(
            FactoryMap.heavy_fields("device__workshop")
        )
        .order_by("-created_date")
        .limit(10)
        .all()
    )
    return [MissionDto.from_mission(x) for x in missions]


async def get_subordinates_users_by_badge(current_badge: str):
    the_user = await User.objects.filter(badge=current_badge).get_or_none()

    if the_user is None:
        raise HTTPException(404, "the user with this id is not found")

    async def get_subsordinates_list(current_badge: str) -> List[str]:
        result = await api_db.fetch_all("""
        SELECT DISTINCT badge FROM users u 
        WHERE u.superior = :superior
        """, {'superior': current_badge})

        return [row[0] for row in result]

    all_subsordinates = await get_subsordinates_list(current_badge)

    while True:
        temp = []
        for subsordinates_badge in all_subsordinates:
            t2 = await get_subsordinates_list(subsordinates_badge)

            for x in t2:
                if x not in temp and x not in all_subsordinates:
                    temp.append(x)
        if len(temp) == 0:
            break
        all_subsordinates.extend(temp)

    workers = (
        await User.objects
        .select_related(["at_device", "workshop"])
        .exclude_fields(FactoryMap.heavy_fields("workshop"))
        .filter(badge__in=all_subsordinates)
        .all()
    )
    return workers


async def get_user_all_level_subordinates_by_badge(badge: str):
    subsordinates = await get_subordinates_users_by_badge(badge)
    promises = [get_worker_status(name) for name in subsordinates]
    resp: List[WorkerStatusDto] = []
    resp = await asyncio.gather(*promises)

    return resp


async def get_users_overview(workshop_name: str) -> DayAndNightUserOverview:

    workshop_entity = (
        await FactoryMap.objects
        .fields(["id", "name"])
        .filter(name=workshop_name)
        .get_or_none()
    )

    if (not workshop_entity):
        raise HTTPException(404, f"unknown workshop: {workshop_name}")

    device_entities = {
        device.id: device
        for device in (
            await Device.objects
            .filter(workshop=workshop_entity.id)
            .all()
        )
    }

    day_overview: List[UserOverviewOut] = []
    night_overview: List[UserOverviewOut] = []
    shift_types = [1, 2]

    for s in shift_types:
        _shift_type = ShiftType(s)
        users = (
            await User.objects
            .select_related(["superior"])
            .filter(
                workshop=workshop_entity.id,
                shift=s
            )
            .all()
        )
        for u in users:
            overview = UserOverviewOut(
                badge=u.badge,
                username=u.username,
                level=u.level,
                shift=_shift_type,
                experiences=[],
                workshop=workshop_entity.name
            )

            if u.superior is not None:
                overview.superior = u.superior.username
            else:
                overview.superior = u.username

            device_levels = (
                await UserDeviceLevel.objects
                .filter(user=u)
                .all()
            )

            if len(device_levels) == 0:
                continue

            for dl in device_levels:
                overview.experiences.append(
                    DeviceExp(
                        project=device_entities[dl.device.id].project,
                        process=device_entities[dl.device.id].process,
                        device_name=device_entities[dl.device.id].device_name,
                        line=device_entities[dl.device.id].line,
                        exp=dl.level,
                    )
                )

            if s == 1:
                day_overview.append(overview)
            else:
                night_overview.append(overview)

    return DayAndNightUserOverview(day_shift=day_overview, night_shift=night_overview)


async def get_user_summary(badge: str) -> Optional[WorkerSummary]:
    worker = await User.objects.filter(badge=badge).get_or_none()

    if worker is None:
        raise HTTPException(
            status_code=404, detail="the user with this id is not found"
        )

    total_accepted_count_this_month = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk)
        FROM audit_log_headers
        WHERE `action` = '{AuditActionEnum.MISSION_ACCEPTED.value}'
        AND user='{badge}'
        AND MONTH(`created_date` + HOUR({TIMEZONE_OFFSET})) = MONTH(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}))
        """,
    )

    total_accepted_count_this_week = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk) FROM audit_log_headers
        WHERE `action` = '{AuditActionEnum.MISSION_ACCEPTED.value}'
        AND user='{badge}'
        AND YEARWEEK(`created_date` + HOUR({TIMEZONE_OFFSET}), {WEEK_START}) = YEARWEEK(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}), {WEEK_START})
        """,
    )

    total_rejected_count_this_month = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk)
        FROM audit_log_headers
        WHERE `action` = '{AuditActionEnum.MISSION_REJECTED.value}'
        AND user='{badge}'
        AND MONTH(`created_date` + HOUR({TIMEZONE_OFFSET})) = MONTH(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}))
        """,
    )

    total_rejected_count_this_week = await api_db.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk) FROM audit_log_headers
        WHERE `action` = '{AuditActionEnum.MISSION_REJECTED.value}'
        AND user='{badge}'
        AND YEARWEEK(`created_date` + HOUR({TIMEZONE_OFFSET}), {WEEK_START}) = YEARWEEK(UTC_TIMESTAMP() + HOUR({TIMEZONE_OFFSET}), {WEEK_START})
        """,
    )

    return WorkerSummary(
        total_accepted_count_this_month=total_accepted_count_this_month[0][0],
        total_accepted_count_this_week=total_accepted_count_this_week[0][0],
        total_rejected_count_this_month=total_rejected_count_this_month[0][0],
        total_rejected_count_this_week=total_rejected_count_this_week[0][0],
    )


async def get_worker_attendances(badge: str) -> List[WorkerAttendance]:
    if not await User.objects.filter(badge=badge).exists():
        return []

    worker_attendances: List[WorkerAttendance] = []

    user_login_days_this_month = await api_db.fetch_all(
        f"""
        SELECT DATE(ADDTIME(loginrecord.created_date, '{TIMEZONE_OFFSET}:00')) `day`, ADDTIME(loginrecord.created_date, '{TIMEZONE_OFFSET}:00') as `time`, loginrecord.description
        FROM audit_log_headers loginrecord,
        (
            SELECT action, MIN(created_date) min_login_date , DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
            FROM audit_log_headers
            WHERE `action` = '{AuditActionEnum.USER_LOGIN.value}' AND user='{badge}'
            GROUP BY DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
        ) min_login
        WHERE loginrecord.`action` = '{AuditActionEnum.USER_LOGIN.value}' AND loginrecord.created_date = min_login.min_login_date;
        """,
    )

    user_logout_days_this_month = await api_db.fetch_all(
        f"""
        SELECT DATE(ADDTIME(logoutrecord.created_date, '{TIMEZONE_OFFSET}:00')) `day`, ADDTIME(logoutrecord.created_date, '{TIMEZONE_OFFSET}:00') as `time`, logoutrecord.description
        FROM audit_log_headers logoutrecord,
        (
            SELECT action, MAX(created_date) max_logout_date , DAY(ADDTIME(created_date, '{TIMEZONE_OFFSET}:00'))
            FROM audit_log_headers
            WHERE `action` = '{AuditActionEnum.USER_LOGOUT.value}' AND user='{badge}'
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


async def check_user_connected(badge: str) -> Tuple[bool, Optional[str]]:
    """
    Get client connection status from EMQX API.

    Returned:
        - connected: bool - True if connected, False otherwise
        - ip_address: str - if user is connected, this field represents the IP address of the client
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://{MQTT_BROKER}:18083/api/v4/clients/{badge}",
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


async def is_worker_in_whitelist(badge: str) -> bool:
    return await WhitelistDevice.objects.select_related(['workers']).filter(workers__badge=badge).exists()


async def is_worker_in_device_whitelist(badge: str, device_id: str) -> bool:
    return await WhitelistDevice.objects.select_related(['workers']).filter(workers__badge=badge, device=device_id).exists()


async def get_worker_status(worker: User) -> Optional[WorkerStatusDto]:
    if worker is None:
        return None

    item = WorkerStatusDto(
        worker_id=worker.badge,
        worker_name=worker.username,
        status=worker.status,
        finish_event_date=worker.finish_event_date,
        total_dispatches=worker.shift_start_count,
    )

    item.at_device = worker.at_device.id if worker.at_device is not None else None
    item.at_device_cname = worker.at_device.device_cname if worker.at_device is not None else None

    mission = await get_user_working_mission(worker)

    if worker.status in [WorkerStatusEnum.working.value, WorkerStatusEnum.moving.value, WorkerStatusEnum.notice.value] and mission is not None:
        item.mission_duration = mission.mission_duration.total_seconds()  # type: ignore

        if mission.repair_duration is not None and not mission.device.is_rescue:
            item.repair_duration = mission.repair_duration.total_seconds()

        if worker.status == WorkerStatusEnum.moving.value:
            item.at_device = mission.device.id
            item.at_device_cname = mission.device.device_cname

    return item
