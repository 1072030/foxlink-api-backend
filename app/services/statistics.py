import logging
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import Mission, ShiftType, UserLevel, api_db, User
from datetime import datetime, timedelta
from app.env import TIMEZONE_OFFSET
from app.models.schema import MissionDto, WorkerMissionStats, WorkerStatusDto
from app.log import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


class UserInfo(BaseModel):
    badge: str
    username: str


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


UTC_NIGHT_SHIFT_FILTER = "AND (TIME(m.created_date) BETWEEN '12:00' AND '23:40') # 夜班 in UTC"
UTC_DAY_SHIFT_FILTER = "AND ((TIME(m.created_date) BETWEEN '23:40' AND '23:59') OR (TIME(m.created_date) BETWEEN '00:00' AND '12:00')) # 白班 in UTC"

LOCAL_NIGHT_SHIFT_FILTER = "AND ((TIME(event_beg_date) BETWEEN '20:00' AND '23:59') OR (TIME(event_beg_date) BETWEEN '00:00' AND '07:40'))"
LOCAL_DAY_SHIFT_FILTER = "AND (TIME(event_beg_date) BETWEEN '07:40' AND '20:00')"


async def get_top_most_crashed_devices(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType], limit=10):
    """
    取得當月最常故障的設備，不依照 Category 分類，排序則由次數由高排到低。
    """
    query = await api_db.fetch_all(
        f"""
        SELECT m.device as device_id, d.device_cname, count(*) AS count FROM missions m
        INNER JOIN devices d ON d.id = m.device
        WHERE 
            (m.created_date BETWEEN :start_date AND :end_date)
            AND d.workshop = :workshop_id
            AND d.is_rescue = FALSE
            {UTC_NIGHT_SHIFT_FILTER if shift == ShiftType.night else (UTC_DAY_SHIFT_FILTER if shift == ShiftType.day else "" )}
        GROUP BY m.device
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": start_date,
            "end_date": end_date, "limit": limit},
    )

    return query


async def get_top_abnormal_missions(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType], limit=10) -> List[AbnormalMissionInfo]:
    """統計當月異常任務，根據處理時間由高排序到低。"""
    china_tz_start_date = start_date + timedelta(hours=TIMEZONE_OFFSET)
    china_tz_end_date = end_date + timedelta(hours=TIMEZONE_OFFSET)

    params = {
        "created_date__gte": china_tz_start_date,
        "created_date__lte": china_tz_end_date,
        "is_done": True,
        "device__is_rescue": False,
        "device__workshop__id": workshop_id,
    }

    # missions = (
    #     await Mission.objects.select_related(
    #         ["device__workshop","worker__at_device"]
    #     )
    #     .exclude_fields(
    #         [
    #             "device__workshop__map",
    #             "device__workshop__related_devices",
    #             "device__workshop__image",
    #         ]
    #     )
    #     .filter(**params)
    #     .order_by("-repair_end_date__gte")
    #     .all()
    # )

    abnormal_missions = await api_db.fetch_all(
        f"""
        SELECT t1.mission_id, t1.device_id, t1.device_cname, max(t1.category) as category, max(t1.message) as message, max(t1.duration) as duration, t1.created_date FROM (
            SELECT mission as mission_id, m.device as device_id, d.device_cname, category, message, TIMESTAMPDIFF(SECOND, event_beg_date, event_end_date) as duration, m.created_date
            FROM mission_events
            INNER JOIN missions m ON m.id = mission
            INNER JOIN devices d ON d.id = m.device 
            WHERE 
                event_end_date IS NOT NULL
                AND d.is_rescue = FALSE
                AND (event_beg_date BETWEEN :start_date AND :end_date)
                AND d.workshop = :workshop_id
                {LOCAL_NIGHT_SHIFT_FILTER if shift == ShiftType.night else (LOCAL_DAY_SHIFT_FILTER if shift == ShiftType.day else "" )}
        ) t1
        GROUP BY (t1.mission_id)
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": china_tz_start_date,
            "end_date": china_tz_end_date, "limit": limit},
    )

    return abnormal_missions  # type: ignore


async def get_top_abnormal_devices(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType], limit=10):
    """根據歷史並依照設備的 Category 統計設備異常情形，並將員工對此異常情形由處理時間由低排序到高，取前三名。"""
    china_tz_start_date = start_date + timedelta(hours=TIMEZONE_OFFSET)
    china_tz_end_date = end_date + timedelta(hours=TIMEZONE_OFFSET)

    abnormal_devices: List[AbnormalDeviceInfo] = await api_db.fetch_all(
        f"""
        SELECT device as device_id, d.device_cname,  max(message) as message, max(category) as category, max(TIMESTAMPDIFF(SECOND, event_beg_date, event_end_date)) as duration
        FROM mission_events
        INNER JOIN missions m ON m.id = mission
        INNER JOIN devices d ON d.id = m.device 
        WHERE 
            event_beg_date IS NOT NULL
            AND event_end_date IS NOT NULL
            AND (event_beg_date BETWEEN :start_date AND :end_date)
            AND d.workshop = :workshop_id
            {LOCAL_NIGHT_SHIFT_FILTER if shift == ShiftType.night else (LOCAL_DAY_SHIFT_FILTER if shift == ShiftType.day else "" )}
        GROUP BY device
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": china_tz_start_date,
            "end_date": china_tz_end_date, "limit": limit},
    )  # type: ignore

    abnormal_devices = [AbnormalDeviceInfo(
        **m) for m in abnormal_devices]  # type: ignore

    for m in abnormal_devices:
        # fetch top 3 assignees that deal with device out-of-order issue most quickly
        top_assignees_in_mission = await api_db.fetch_all(
            """
            SELECT t1.badge, t1.username, min(t1.duration) as duration FROM (
                SELECT u.badge, u.username, TIMESTAMPDIFF(SECOND, me.event_beg_date, me.event_end_date) as duration
                FROM mission_events me
                LEFT OUTER JOIN missions_users mu ON mu.mission = me.mission
                INNER JOIN missions m ON m.id = me.mission
                INNER JOIN users u ON u.badge = mu.user
                WHERE device = :device_id AND category = :category AND event_end_date IS NOT NULL
                ORDER BY duration ASC
            ) t1
            GROUP BY t1.badge
            ORDER BY duration
            LIMIT 3;
            """,
            {"device_id": m.device_id, "category": m.category},
        )

        m.top_great_assignees = [
            UserInfoWithDuration(
                badge=x["badge"], username=x["username"], duration=x["duration"]
            )
            for x in top_assignees_in_mission
        ]

    return abnormal_devices


async def get_top_most_accept_mission_employees(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType], limit: int) -> List[WorkerMissionStats]:
    """取得當月最常接受任務的員工"""

    utc_night_filter = UTC_NIGHT_SHIFT_FILTER.replace(
        "m.created_date", "audit_log_headers.created_date")
    utc_day_filter = UTC_DAY_SHIFT_FILTER.replace(
        "m.created_date", "audit_log_headers.created_date")

    query = await api_db.fetch_all(
        f"""
        SELECT u.badge, u.username, count(DISTINCT record_pk) AS count
        FROM `audit_log_headers`
        INNER JOIN users u ON u.badge = audit_log_headers.`user`
        WHERE 
            action='MISSION_ACCEPTED'
            AND (audit_log_headers.created_date BETWEEN :start_date AND :end_date)
            AND u.workshop = :workshop_id
            {utc_night_filter if shift == ShiftType.night else (utc_day_filter if shift == ShiftType.day else "" )}
        GROUP BY u.badge
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": start_date,
            "end_date": end_date, "limit": limit},
    )

    return [WorkerMissionStats(**m) for m in query]


async def get_top_most_reject_mission_employees(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType], limit: int) -> List[WorkerMissionStats]:
    """取得當月最常拒絕任務的員工"""
    utc_night_filter = UTC_NIGHT_SHIFT_FILTER.replace(
        "m.created_date", "audit_log_headers.created_date")
    utc_day_filter = UTC_DAY_SHIFT_FILTER.replace(
        "m.created_date", "audit_log_headers.created_date")

    query = await api_db.fetch_all(
        f"""
        SELECT u.badge, u.username, count(DISTINCT record_pk) AS count
        FROM `audit_log_headers`
        INNER JOIN users u ON u.badge = audit_log_headers.`user`
        WHERE 
            action='MISSION_REJECTED'
            AND (audit_log_headers.created_date BETWEEN :start_date AND :end_date)
            AND u.workshop = :workshop_id
            {utc_night_filter if shift == ShiftType.night else (utc_day_filter if shift == ShiftType.day else "" )}
        GROUP BY u.badge
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"workshop_id": workshop_id, "start_date": start_date,
            "end_date": end_date, "limit": limit},
    )

    return [WorkerMissionStats(**m) for m in query]


async def get_login_users_percentage_by_recent_24_hours(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType]) -> float:
    """取得最近 24 小時登入系統員工的百分比"""
    total_user_count = await User.objects.filter(
        level=UserLevel.maintainer.value
    ).count()

    if total_user_count == 0:
        return 0.0

    utc_night_filter = UTC_NIGHT_SHIFT_FILTER.replace(
        "m.created_date", "a.created_date")
    utc_day_filter = UTC_DAY_SHIFT_FILTER.replace(
        "m.created_date", "a.created_date")

    result = await api_db.fetch_all(
        f"""
        SELECT count(DISTINCT user) FROM `audit_log_headers` a
        INNER JOIN users u ON a.user = u.badge
        WHERE 
            action='USER_LOGIN'
            AND u.level = 1
            AND (a.created_date BETWEEN :start_date AND :end_date)
            {utc_night_filter if shift == ShiftType.night else (utc_day_filter if shift == ShiftType.day else "" )}
            AND u.workshop = :workshop_id;
        """,
        {"workshop_id": workshop_id, "start_date": start_date, "end_date": end_date},
    )

    return round(result[0][0] / total_user_count, 3)


async def get_emergency_missions(workshop_id: int) -> List[MissionDto]:
    """取得當下緊急任務列表"""
    missions = (
        await Mission.objects
        .select_related(["worker", "device", "device__workshop"])
        .exclude_fields(["device__workshop__map", "device__workshop__related_devices", "device__workshop__image"])
        .filter(
            is_done=False,
            is_emergency=True,
            repair_end_date__isnull=True,
            device__workshop__id=workshop_id
        )
        .order_by(["created_date"])
        .all()
    )

    return [MissionDto.from_mission(m) for m in missions]
