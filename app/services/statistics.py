import logging
import math
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import Mission, ShiftType, UserLevel, api_db, User, FactoryMap, Shift
from datetime import date, datetime, timedelta
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
    category: str
    messages: Optional[str]
    mission_ids: Optional[str]
    event_ids: Optional[str]
    avg_duration: int
    top_great_assignees: Optional[List[UserInfoWithDuration]]


class AbnormalMissionInfo(BaseModel):
    mission_id: str
    device_id: str
    device_cname: Optional[str]
    categories: str
    messages: Optional[str]
    duration: int
    created_date: datetime


UTC_NIGHT_SHIFT_FILTER = "AND (TIME(m.created_date) BETWEEN '12:00' AND '23:40') # 夜班 in UTC"
UTC_DAY_SHIFT_FILTER = "AND ((TIME(m.created_date) BETWEEN '23:40' AND '23:59') OR (TIME(m.created_date) BETWEEN '00:00' AND '12:00')) # 白班 in UTC"

LOCAL_NIGHT_SHIFT_FILTER = "AND ((TIME(event_beg_date) BETWEEN '20:00' AND '23:59') OR (TIME(event_beg_date) BETWEEN '00:00' AND '07:40'))"
LOCAL_DAY_SHIFT_FILTER = "AND (TIME(event_beg_date) BETWEEN '07:40' AND '20:00')"


async def match_time_interval(shift_type: ShiftType, column=None, default="1"):
    if (shift_type):
        shift = await Shift.objects.get_or_none(id=shift_type.value)
        shift.shift_beg_time = (
            datetime.combine(date.today(), shift.shift_beg_time)
            - timedelta(hours=TIMEZONE_OFFSET)
        ).time()

        shift.shift_end_time = (
            datetime.combine(date.today(), shift.shift_end_time)
            - timedelta(hours=TIMEZONE_OFFSET)
        ).time()

        if (shift and column):
            if (shift.shift_beg_time > shift.shift_end_time):
                return f"((TIME({column}) BETWEEN '{shift.shift_beg_time}' AND '23:59') OR (TIME({column}) BETWEEN '00:00' AND '{shift.shift_end_time}'))"
            else:
                return f"(TIME({column}) BETWEEN '{shift.shift_beg_time}' AND '{shift.shift_end_time}')"
    return default


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

    abnormal_missions = await api_db.fetch_all(
        f"""
            SELECT 
            r.mission_id, r.device_id, r.device_cname, 
            GROUP_CONCAT(DISTINCT  r.event_category SEPARATOR ', ') as categories,
            GROUP_CONCAT(DISTINCT  r.event_message SEPARATOR ', ')  as messages,
            r.duration as duration, 
            r.created_date 
            FROM (
                SELECT
                    m.id as mission_id, m.created_date as created_date,
                    d.id as device_id, d.device_cname as device_cname,
                    e.category as event_category, e.message as event_message, 
                    TIMESTAMPDIFF(SECOND, m.repair_beg_date, m.repair_end_date) as duration 
                FROM missions as m
                INNER JOIN devices as d ON d.id = m.device
                INNER JOIN mission_events as e ON e.mission = m.id 
                WHERE 
                    e.event_end_date  IS NULL AND
                    m.repair_end_date IS NOT NULL AND
                    d.is_rescue = FALSE AND 
                    d.workshop = :workshop_id AND
                    (m.repair_end_date BETWEEN :start_date AND :end_date) AND
                    {await match_time_interval(shift,"repair_end_date")}
            ) as r
            GROUP BY (r.mission_id)
            ORDER BY duration DESC
            LIMIT :limit;
        """,
        {
            "workshop_id": workshop_id,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit
        },
    )

    return abnormal_missions  # type: ignore


async def get_top_abnormal_devices(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType], limit=10):
    """根據歷史並依照設備的 Category 統計設備異常情形，並將員工對此異常情形由處理時間由低排序到高，取前三名。"""
    abnormal_devices: List[AbnormalDeviceInfo] = await api_db.fetch_all(
        f"""
            SELECT 
                d.id as device_id, 
                d.device_cname as device_cname,
                e.category as category,
                GROUP_CONCAT(DISTINCT e.message) as messages,
                GROUP_CONCAT(DISTINCT m.id) as mission_ids,
                GROUP_CONCAT(DISTINCT e.id) as event_ids,
                AVG(TIMESTAMPDIFF(SECOND, DATE_SUB(e.event_beg_date , INTERVAL {TIMEZONE_OFFSET} hour), m.repair_end_date)) as avg_duration
            FROM mission_events as e 
            INNER JOIN missions as m ON m.id = mission
            INNER JOIN devices as d ON d.id = m.device 
            WHERE 
                e.event_beg_date IS NOT NULL AND 
                m.repair_end_date IS NOT NULL AND
                d.workshop = :workshop_id AND
                (event_beg_date BETWEEN :event_start_date AND :event_end_date) AND
                {await match_time_interval(shift,"repair_end_date")}
            GROUP BY d.id, e.category 
            ORDER BY avg_duration DESC
            LIMIT :limit;
        """,
        {
            "workshop_id": workshop_id,
            "event_start_date": start_date + timedelta(hours=8),
            "event_end_date": end_date+ timedelta(hours=8),
            "limit": limit
        },
    )  # type: ignore

    abnormal_devices = [
        AbnormalDeviceInfo(**m)
        for m in abnormal_devices
    ]  # type: ignore

    for device in abnormal_devices:
        # fetch top 3 assignees that deal with device out-of-order issue most quickly
        top_assignees_in_mission = await api_db.fetch_all(
            """
                SELECT r.badge, r.username, min(r.duration) as duration FROM (
                    SELECT 
                        u.badge,
                        u.username,
                        TIMESTAMPDIFF(SECOND, m.repair_beg_date, m.repair_end_date) as duration
                    FROM mission_events as e
                    INNER JOIN missions as m ON m.id = e.mission
                    INNER JOIN users as u ON u.badge = m.worker
                    WHERE
                        m.id IN :missions
                    ORDER BY duration ASC
                ) r
                GROUP BY r.badge
                ORDER BY duration
                LIMIT 3;
            """,
            {
                "missions": device.mission_ids.split(',')
            },
        )

        device.top_great_assignees = [
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
            action='MISSION_STARTED'
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


async def get_login_users_percentage(workshop_id: int, start_date: datetime, end_date: datetime, shift: Optional[ShiftType]) -> float:
    """取得最近 24 小時登入系統員工的百分比"""
    query = {
        "level":UserLevel.maintainer.value,
    }
    if shift:
        query["shift"]= shift.value

    full_days = math.floor((end_date - start_date).total_seconds()/(60*60*24))

    total_user_count = await User.objects.filter(**query).count() * full_days

    if total_user_count == 0:
        return 0.0

    result = await api_db.fetch_all(
        f"""
        SELECT count(DISTINCT user) FROM `audit_log_headers` a
        INNER JOIN users u ON a.user = u.badge
        WHERE 
            action='USER_LOGIN' AND
            u.level = {UserLevel.maintainer.value} AND 
            (a.created_date BETWEEN :start_date AND :end_date) AND
            {await match_time_interval(shift,"a.created_date")} AND
            u.workshop = :workshop_id;
        """,
        {"workshop_id": workshop_id, "start_date": start_date, "end_date": end_date},
    )

    return round(result[0][0] / total_user_count, 3)


async def get_emergency_missions(workshop_id: int) -> List[MissionDto]:
    """取得當下緊急任務列表"""
    missions = (
        await Mission.objects
        .select_related(["worker", "device", "device__workshop"])
        .exclude_fields(FactoryMap.heavy_fields("device__workshop"))
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
