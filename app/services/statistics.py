from typing import List, Optional
from pydantic import BaseModel
from app.core.database import Mission, database, User
import datetime


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
    event_start_date: datetime.datetime


class AbnormalMissionInfo(BaseModel):
    device_id: str
    description: Optional[str]
    category: int
    duration: int
    top_assignees: Optional[List[UserInfoWithDuration]]


async def get_top_most_crashed_devices(limit: int):
    query = await database.fetch_all(
        f"SELECT device, count(*) AS count FROM missions GROUP BY device ORDER BY count DESC LIMIT :limit;",
        {"limit": limit},
    )

    return query


async def get_top_abnormal_missions(limit: int):
    abnormal_missions: List[AbnormalMissionInfo] = await database.fetch_all(
        """
        SELECT DISTINCT device as device_id, description, category, TIMESTAMPDIFF(SECOND, event_start_date, event_end_date) as duration
        FROM missions
        WHERE event_start_date IS NOT NULL AND event_end_date IS NOT NULL
        ORDER BY duration DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )  # type: ignore

    abnormal_missions = [AbnormalMissionInfo(**m) for m in abnormal_missions]  # type: ignore

    for m in abnormal_missions:
        # fetch top 3 assignees that deal with device out-of-order issue most quickly
        top_assignees_in_mission = await database.fetch_all(
            """
            SELECT DISTINCT u.username, u.full_name, TIMESTAMPDIFF(SECOND, event_start_date, event_end_date) as duration
            FROM missions
            LEFT OUTER JOIN missions_users mu ON missions.id=mu.mission
            INNER JOIN users u ON u.id = mu.user 
            WHERE device = :device_id AND category = :category AND event_end_date IS NOT NULL
            ORDER BY duration ASC
            LIMIT 3;
            """,
            {"device_id": m.device_id, "category": m.category},
        )

        m.top_assignees = [
            UserInfoWithDuration(
                username=x["username"], full_name=x["full_name"], duration=x["duration"]
            )
            for x in top_assignees_in_mission
        ]

    return abnormal_missions


async def get_top_most_accept_mission_employees(limit: int):
    query = await database.fetch_all(
        """
        SELECT u.username, u.full_name, count(*) AS count
        FROM `auditlogheaders`
        INNER JOIN users u ON u.id = auditlogheaders.`user`
        WHERE action='MISSION_ACCEPTED' AND MONTH(created_date) = MONTH(CURRENT_DATE())
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )

    return query


async def get_top_most_reject_mission_employees(limit: int):
    query = await database.fetch_all(
        """
        SELECT u.username, u.full_name, count(*) AS count
        FROM `auditlogheaders`
        INNER JOIN users u ON u.id = auditlogheaders.`user`
        WHERE action='MISSION_REJECTED' AND MONTH(created_date) = MONTH(CURRENT_DATE())
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT :limit;
        """,
        {"limit": limit},
    )

    return query


async def get_login_users_percentage_by_week() -> float:
    total_user_count = await User.objects.filter(is_active=True, is_admin=False).count()

    if total_user_count == 0:
        return 0.0

    result = await database.fetch_all(
        f"SELECT count(DISTINCT user) FROM `auditlogheaders` WHERE action='USER_LOGIN' AND created_date >= DATE(NOW()) - INTERVAL 6 DAY AND created_date <= DATE(NOW()) + INTERVAL 1 DAY;"
    )

    return round(result[0][0] / total_user_count, 3)


async def get_emergency_missions() -> List[EmergencyMissionInfo]:
    missions = (
        await Mission.objects.filter(is_emergency=True, repair_end_date__isnull=True)
        .select_related("assignees")
        .all()
    )

    return [
        EmergencyMissionInfo(
            mission_id=m.id,
            device_id=m.device.id,
            assignees=[
                UserInfo(username=a.username, full_name=a.full_name)
                for a in m.assignees
            ],
            category=m.category,
            description=m.description,
            event_start_date=m.event_start_date,
        )
        for m in missions
    ]
