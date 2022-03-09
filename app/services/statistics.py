from app.core.database import Mission, database, User


async def get_top_most_crashed_devices(limit: int):
    query = await database.fetch_all(
        f"SELECT device, count(*) AS count FROM missions GROUP BY device ORDER BY count DESC LIMIT :limit;",
        {"limit": limit},
    )

    return query


async def get_top_abnormal_missions(limit: int):
    query = await database.fetch_all(
        "SELECT id, device, description, category, TIMESTAMPDIFF(SECOND, event_start_date, event_end_date) as duration FROM missions WHERE event_start_date IS NOT NULL AND event_end_date IS NOT NULL ORDER BY duration DESC LIMIT :limit;",
        {"limit": limit},
    )

    return query


async def get_top_most_reject_mission_employee(limit: int):
    query = await database.fetch_all(
        f"SELECT u.username , count(*) AS count FROM `auditlogheaders` INNER JOIN users u ON u.id = auditlogheaders.`user` WHERE action='MISSION_REJECTED' AND MONTH(created_date) = MONTH(CURRENT_DATE()) GROUP BY u.username ORDER BY count DESC LIMIT :limit;",
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


async def get_emergency_missions():
    return await Mission.objects.filter(
        is_emergency=True, repair_end_date__isnull=True
    ).all()
