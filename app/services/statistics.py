import logging
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import Mission, UserLevel, WorkerStatus, WorkerStatusEnum, database, User
from datetime import datetime, timedelta
from ormar import and_, or_
from app.env import TIMEZONE_OFFSET

from app.models.schema import MissionDto, WorkerMissionStats, WorkerStatusDto
from app.my_log_conf import LOGGER_NAME
from app.utils.utils import get_current_shift_time_interval

logger = logging.getLogger(LOGGER_NAME)

class UserInfo(BaseModel):
    username: str
    full_name: str


class UserInfoWithDuration(UserInfo):
    duration: int


class EmergencyMissionInfo(BaseModel):
    mission_id: str
    device_id: str
    device_cname: Optional[str]
    assignees: List[UserInfo]
    description: Optional[str]
    category: str
    created_date: datetime


class AbnormalDeviceInfo(BaseModel):
    device_id: str
    device_cname: Optional[str]
    message: Optional[str]
    category: int
    duration: int
    top_great_assignees: Optional[List[UserInfoWithDuration]]


class AbnormalMissionInfo(BaseModel):
    mission_id: str
    device_id: str
    device_cname: Optional[str]
    category: int
    message: Optional[str]
    duration: int
    created_date: datetime


async def get_top_most_crashed_devices(workshop_id: int, start_date: datetime, end_date: datetime, limit = 10):
    """
    取得當月最常故障的設備，不依照 Category 分類，排序則由次數由高排到低。
    """
    query = await database.fetch_all(
        """
        SELECT m.device as device_id, d.device_cname, count(*) AS count FROM missions m
        INNER JOIN devices d ON d.id = m.device
        WHERE (m.created_date BETWEEN :start_date AND :end_date) AND d.workshop = :workshop_id AND d.is_rescue = FALSE
        GROUP BY m.device
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": start_date, "end_date": end_date, "limit": limit},
    )

    return query


async def get_top_abnormal_missions(workshop_id: int, start_date: datetime, end_date: datetime, limit = 10) -> List[AbnormalMissionInfo]:
    """統計當月異常任務，根據處理時間由高排序到低。"""
    china_tz_start_date = start_date + timedelta(hours=TIMEZONE_OFFSET)
    china_tz_end_date = end_date + timedelta(hours=TIMEZONE_OFFSET)

    abnormal_missions = await database.fetch_all(
        """
        SELECT t1.mission_id, t1.device_id, t1.device_cname, max(t1.category) as category, max(t1.message) as message, max(t1.duration) as duration, t1.created_date FROM (
            SELECT mission as mission_id, m.device as device_id, d.device_cname, category, message, TIMESTAMPDIFF(SECOND, event_start_date, event_end_date) as duration, m.created_date
            FROM missionevents
            INNER JOIN missions m ON m.id = mission
            INNER JOIN devices d ON d.id = m.device 
            WHERE event_end_date IS NOT NULL AND d.is_rescue = FALSE AND (event_start_date BETWEEN :start_date AND :end_date) AND d.workshop = :workshop_id
        ) t1
        GROUP BY (t1.mission_id)
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": china_tz_start_date, "end_date": china_tz_end_date, "limit": limit},
    )

    return abnormal_missions  # type: ignore


async def get_top_abnormal_devices(workshop_id: int, start_date: datetime, end_date: datetime, limit: int = 10):
    """根據歷史並依照設備的 Category 統計設備異常情形，並將員工對此異常情形由處理時間由低排序到高，取前三名。"""
    china_tz_start_date = start_date + timedelta(hours=TIMEZONE_OFFSET)
    china_tz_end_date = end_date + timedelta(hours=TIMEZONE_OFFSET)

    abnormal_devices: List[AbnormalDeviceInfo] = await database.fetch_all(
        """
        SELECT device as device_id, d.device_cname,  max(message) as message, max(category) as category, max(TIMESTAMPDIFF(SECOND, event_start_date, event_end_date)) as duration
        FROM missionevents
        INNER JOIN missions m ON m.id = mission
        INNER JOIN devices d ON d.id = m.device 
        WHERE event_start_date IS NOT NULL AND event_end_date IS NOT NULL AND (event_start_date BETWEEN :start_date AND :end_date) AND d.workshop = :workshop_id
        GROUP BY device
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": china_tz_start_date, "end_date": china_tz_end_date, "limit": limit},
    )  # type: ignore

    abnormal_devices = [AbnormalDeviceInfo(**m) for m in abnormal_devices]  # type: ignore

    for m in abnormal_devices:
        # fetch top 3 assignees that deal with device out-of-order issue most quickly
        top_assignees_in_mission = await database.fetch_all(
            """
            SELECT t1.username, t1.full_name, min(t1.duration) as duration FROM (
                SELECT u.username, u.full_name, TIMESTAMPDIFF(SECOND, me.event_start_date, me.event_end_date) as duration
                FROM missionevents me
                LEFT OUTER JOIN missions_users mu ON mu.mission = me.mission
                INNER JOIN missions m ON m.id = me.mission
                INNER JOIN users u ON u.username = mu.user
                WHERE device = :device_id AND category = :category AND event_end_date IS NOT NULL
                ORDER BY duration ASC
            ) t1
            GROUP BY t1.username
            ORDER BY duration
            LIMIT 3;
            """,
            {"device_id": m.device_id, "category": m.category},
        )

        m.top_great_assignees = [
            UserInfoWithDuration(
                username=x["username"], full_name=x["full_name"], duration=x["duration"]
            )
            for x in top_assignees_in_mission
        ]

    return abnormal_devices


async def get_top_most_accept_mission_employees(workshop_id: int, start_date: datetime, end_date: datetime, limit: int) -> List[WorkerMissionStats]:
    """取得當月最常接受任務的員工"""

    query = await database.fetch_all(
        f"""
        SELECT u.username, u.full_name, count(DISTINCT record_pk) AS count
        FROM `auditlogheaders`
        INNER JOIN users u ON u.username = auditlogheaders.`user`
        WHERE action='MISSION_ACCEPTED' AND (created_date BETWEEN :start_date AND :end_date) AND u.location = :workshop_id
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": start_date, "end_date": end_date, "limit": limit},
    )

    return [WorkerMissionStats(**m) for m in query]


async def get_top_most_reject_mission_employees(workshop_id: int, start_date: datetime, end_date: datetime, limit: int) -> List[WorkerMissionStats]:
    """取得當月最常拒絕任務的員工"""

    query = await database.fetch_all(
        f"""
        SELECT u.username, u.full_name, count(DISTINCT record_pk) AS count
        FROM `auditlogheaders`
        INNER JOIN users u ON u.username = auditlogheaders.`user`
        WHERE action='MISSION_REJECTED' AND (created_date BETWEEN :start_date AND :end_date) AND u.location = :workshop_id
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": start_date, "end_date": end_date, "limit": limit},
    )

    return [WorkerMissionStats(**m) for m in query]


async def get_login_users_percentage_by_recent_24_hours(workshop_id: int, start_date: datetime, end_date: datetime) -> float:
    """取得最近 24 小時登入系統員工的百分比"""
    total_user_count = await User.objects.filter(
        is_active=True, level=UserLevel.maintainer.value
    ).count()

    if total_user_count == 0:
        return 0.0

    result = await database.fetch_all(
        f"""
        SELECT count(DISTINCT user) FROM `auditlogheaders` a
        INNER JOIN users u ON a.user = u.username
        WHERE action='USER_LOGIN' AND u.level = 1 AND (created_date BETWEEN :start_date AND :end_date) AND u.location = :workshop_id;
        """,
        {"workshop_id": workshop_id, "start_date": start_date, "end_date": end_date},
    )

    return round(result[0][0] / total_user_count, 3)


async def get_emergency_missions(workshop_id: int) -> List[MissionDto]:
    """取得當下緊急任務列表"""
    missions = (
        await Mission.objects.filter(
            is_emergency=True, repair_end_date__isnull=True, is_cancel=False, device__workshop__id=workshop_id
        )
        .select_related(["assignees", "missionevents", "device", "device__workshop"])
        .exclude_fields(["device__workshop__map", "device__workshop__related_devices", "device__workshop__image"])
        .order_by(["created_date"])
        .all()
    )

    return [MissionDto.from_mission(m) for m in missions]


async def get_worker_status(username: str) -> Optional[WorkerStatusDto]:
    s = (
        await WorkerStatus.objects.filter(worker=username)
        .select_related(["worker", 'at_device'])
        .get_or_none()
    )

    if s is None:
        return None

    shift_start, shift_end = get_current_shift_time_interval()

    total_accept_count = await database.fetch_all(
        f"""
        SELECT COUNT(DISTINCT record_pk)
        FROM auditlogheaders
        WHERE `action` = 'MISSION_ACCEPTED'
        AND user=:username AND (created_date BETWEEN :shift_start AND :shift_end);
        """,
        {'username': username, 'shift_start': shift_start, 'shift_end': shift_end},
    )

    item = WorkerStatusDto(
        worker_id=username,
        worker_name=s.worker.full_name,
        status=s.status,
        last_event_end_date=s.last_event_end_date,
        total_dispatches=total_accept_count[0][0],
    )

    item.at_device = s.at_device.id if s.at_device is not None else None
    item.at_device_cname = s.at_device.device_cname if s.at_device is not None else None

    if s.status == WorkerStatusEnum.working.value:
        try:
            mission = (
                await Mission.objects.select_related(['assignees']).filter(
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
                )
                .order_by("-id")
                .first()
            )

            item.mission_duration = mission.mission_duration.total_seconds() # type: ignore
            item.repair_duration = mission.repair_duration.total_seconds() # type: ignore
        except:
            ...
    return item
