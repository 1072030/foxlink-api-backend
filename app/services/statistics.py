from typing import List, Optional
from pydantic import BaseModel
from app.core.database import Mission, UserLevel, WorkerStatus, database, User
from datetime import datetime

from app.models.schema import MissionDto, WorkerMissionStats, WorkerStatusDto


class UserInfo(BaseModel):
    username: str
    full_name: str


class UserInfoWithDuration(UserInfo):
    duration: int


class EmergencyMissionInfo(BaseModel):
    mission_id: str
    device_id: str
    assignees: List[UserInfo]
    description: Optional[str]
    category: str
    created_date: datetime


class AbnormalDeviceInfo(BaseModel):
    device_id: str
    message: Optional[str]
    category: int
    duration: int
    top_great_assignees: Optional[List[UserInfoWithDuration]]


class AbnormalMissionInfo(BaseModel):
    mission_id: str
    device_id: str
    category: int
    message: Optional[str]
    duration: int
    created_date: datetime


async def get_top_most_crashed_devices(limit: int):
    """
    取得當月最常故障的設備，不依照 Category 分類，排序則由次數由高排到低。
    """
    query = await database.fetch_all(
        """
        SELECT device, count(*) AS count FROM missions
        WHERE MONTH(created_date) = MONTH(CURRENT_DATE())
        GROUP BY device
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )

    return query


async def get_top_abnormal_missions(limit: int = 10) -> List[AbnormalMissionInfo]:
    """統計當月異常任務，根據處理時間由高排序到低。"""
    abnormal_missions = await database.fetch_all(
        """
        SELECT mission as mission_id, m.device as device_id, message, category, TIMESTAMPDIFF(SECOND, event_start_date, event_end_date) as duration, created_date
        FROM missionevents
        INNER JOIN missions m ON m.id = mission
        WHERE event_end_date IS NOT NULL AND MONTH(event_start_date) = MONTH(CURRENT_DATE())
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )

    return abnormal_missions  # type: ignore


async def get_top_abnormal_devices(limit: int = 10):
    """根據歷史並依照設備的 Category 統計設備異常情形，並將員工對此異常情形由處理時間由低排序到高，取前三名。"""
    abnormal_devices: List[AbnormalDeviceInfo] = await database.fetch_all(
        """
        SELECT device as device_id, max(message) as message, max(category) as category, max(TIMESTAMPDIFF(SECOND, event_start_date, event_end_date)) as duration
        FROM missionevents
        INNER JOIN missions m ON m.id = mission
        WHERE event_start_date IS NOT NULL AND event_end_date IS NOT NULL
        GROUP BY device
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )  # type: ignore

    abnormal_devices = [AbnormalDeviceInfo(**m) for m in abnormal_devices]  # type: ignore

    for m in abnormal_devices:
        # fetch top 3 assignees that deal with device out-of-order issue most quickly
        top_assignees_in_mission = await database.fetch_all(
            """
            SELECT DISTINCT u.username, u.full_name, TIMESTAMPDIFF(SECOND, me.event_start_date, me.event_end_date) as duration
            FROM missionevents me
            LEFT OUTER JOIN missions_users mu ON mu.mission = me.mission
            INNER JOIN missions m ON m.id = me.mission
            INNER JOIN users u ON u.username = mu.user
            WHERE device = :device_id AND category = :category AND event_end_date IS NOT NULL
            ORDER BY duration ASC
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


async def get_top_most_accept_mission_employees(limit: int) -> List[WorkerMissionStats]:
    """取得當月最常接受任務的員工"""

    query = await database.fetch_all(
        """
        SELECT u.username, u.full_name, count(*) AS count
        FROM `auditlogheaders`
        INNER JOIN users u ON u.username = auditlogheaders.`user`
        WHERE action='MISSION_ACCEPTED' AND MONTH(created_date) = MONTH(CURRENT_DATE())
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )

    return [WorkerMissionStats(**m) for m in query]


async def get_top_most_reject_mission_employees(limit: int) -> List[WorkerMissionStats]:
    """取得當月最常拒絕任務的員工"""

    query = await database.fetch_all(
        """
        SELECT u.username, u.full_name, count(*) AS count
        FROM `auditlogheaders`
        INNER JOIN users u ON u.username = auditlogheaders.`user`
        WHERE action='MISSION_REJECTED' AND MONTH(created_date) = MONTH(CURRENT_DATE())
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )

    return [WorkerMissionStats(**m) for m in query]


async def get_login_users_percentage_by_recent_24_hours() -> float:
    """取得最近 24 小時登入系統員工的百分比"""
    total_user_count = await User.objects.filter(
        is_active=True, level=UserLevel.maintainer.value
    ).count()

    if total_user_count == 0:
        return 0.0

    result = await database.fetch_all(
        f"SELECT count(DISTINCT user) FROM `auditlogheaders` WHERE action='USER_LOGIN' AND created_date >= CURRENT_TIMESTAMP() - INTERVAL 1 DAY;"
    )

    return round(result[0][0] / total_user_count, 3)


async def get_emergency_missions() -> List[MissionDto]:
    """取得當下緊急任務列表"""
    missions = (
        await Mission.objects.filter(
            is_emergency=True, repair_end_date__isnull=True, is_cancel=False
        )
        .select_related(["assignees", "missionevents", "device", "workshop"])
        .exclude_fields(["workshop__map", "workshop__related_devices", "workshop__image"])
        .order_by(["created_date"])
        .all()
    )

    return [MissionDto.from_mission(m) for m in missions]


async def get_worker_status(username: str) -> Optional[WorkerStatusDto]:
    s = (
        await WorkerStatus.objects.filter(worker=username)
        .select_related(["worker"])
        .get_or_none()
    )

    if s is None:
        return None

    item = WorkerStatusDto(
        worker_id=s.username,
        worker_name=s.full_name,
        status=s.status,
        last_event_end_date=s.last_event_end_date,
        total_dispatches=s.dispatch_count,
    )

    item.at_device = s.at_device.id if s.at_device is not None else None

    try:
        mission = (
            await Mission.objects.filter(
                assignees__username=username,
                repair_start_date__isnull=False,
                repair_end_date__isnull=True,
            )
            .order_by("repair_start_date")
            .first()
        )

        if mission.repair_start_date is not None:
            duration = datetime.utcnow() - mission.repair_start_date
            item.mission_duration = duration.total_seconds()
    finally:
        return item
