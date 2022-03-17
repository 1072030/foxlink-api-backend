from app.services.device import get_device_by_id
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.core.database import (
    Mission,
    User,
    AuditLogHeader,
    AuditActionEnum,
    UserDeviceLevel,
    WorkerStatus,
    WorkerStatusEnum,
    UserLevel,
    Device,
    database,
)
from fastapi.exceptions import HTTPException
from app.models.schema import MissionCancel, MissionCreate, MissionFinish, MissionUpdate
from app.mqtt.main import publish
import logging
from app.services.user import get_user_by_username
from app.my_log_conf import LOGGER_NAME
from app.env import WORKER_REJECT_AMOUNT_NOTIFY, MISSION_REJECT_AMOUT_NOTIFY
from app.utils.utils import get_shift_type_now, CST_TIMEZONE

logger = logging.getLogger(LOGGER_NAME)


async def get_missions() -> List[Mission]:
    return await Mission.objects.select_all().all()


async def get_mission_by_id(id: int) -> Optional[Mission]:
    item = await Mission.objects.select_all().get_or_none(id=id)
    return item


async def get_missions_by_username(username: str):
    missions = (
        await Mission.objects.select_related(["assignees", "device"])
        .filter(assignees__username=username)
        .order_by("created_date")
        .all()
    )
    return missions


async def update_mission_by_id(id: int, dto: MissionUpdate):
    mission = await get_mission_by_id(id)
    if mission is None:
        raise HTTPException(
            status_code=400, detail="cannot get a mission by the id",
        )

    updateDict: Dict[str, Any] = {}
    try:
        if dto.name is not None:
            updateDict["name"] = dto.name

        if dto.device_id is not None:
            device = await get_device_by_id(dto.device_id)
            updateDict["device"] = device

        if dto.description is not None:
            updateDict["description"] = dto.description

        await mission.update(None, **updateDict)
    except:
        raise HTTPException(status_code=400, detail="cannot update mission")

    return True


async def create_mission(dto: MissionCreate):
    try:
        created_mission = await Mission.objects.create(**dto.dict())
    except:
        raise HTTPException(
            status_code=400, detail="raise a error when inserting mission into databse",
        )
    return created_mission


@database.transaction()
async def start_mission_by_id(mission_id: int, validate_user: User):
    mission = await Mission.objects.select_related("assignees").get_or_none(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if len([x for x in mission.assignees if x.username == validate_user.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.repair_end_date is not None:
        raise HTTPException(400, "this mission is already closed!")

    if mission.repair_start_date is not None:
        raise HTTPException(400, "this mission is starting currently")

    await mission.update(repair_start_date=datetime.utcnow())

    for worker in mission.assignees:
        worker_status = await WorkerStatus.objects.filter(worker=worker).get()
        worker_status.dispatch_count += 1
        worker_status.status = WorkerStatusEnum.working.value
        await worker_status.update()
        await AuditLogHeader.objects.create(
            action=AuditActionEnum.MISSION_ACCEPTED.value,
            user=worker.username,
            table_name="missions",
            record_pk=mission.id,
        )


async def reject_mission_by_id(mission_id: int, user: User):
    mission = await Mission.objects.select_related("assignees").get_or_none(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    filter = [u for u in mission.assignees if u.username == user.username]

    if len(filter) == 0:
        raise HTTPException(400, "the mission haven't assigned to you")

    if mission.repair_start_date is not None:
        raise HTTPException(400, "this mission is starting currently")

    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_REJECTED.value,
        record_pk=str(mission.id),
        user=user,
    )

    await mission.assignees.remove(user)  # type: ignore

    mission_reject_amount = await AuditLogHeader.objects.filter(
        record_pk=str(mission.id),
        action=AuditActionEnum.MISSION_REJECTED.value,
        user=user,
    ).count()

    if mission_reject_amount >= MISSION_REJECT_AMOUT_NOTIFY:  # type: ignore
        publish(
            "foxlink/mission/rejected",
            {
                "id": mission.id,
                "worker": user.full_name,
                "rejected_count": mission_reject_amount,
            },
            qos=1,
            retain=True,
        )

    worker_reject_amount_today = await AuditLogHeader.objects.filter(
        user=user,
        action=AuditActionEnum.MISSION_REJECTED.value,
        created_date__gte=datetime.now(CST_TIMEZONE).date(),
    ).count()

    if worker_reject_amount_today >= WORKER_REJECT_AMOUNT_NOTIFY:  # type: ignore
        worker_device_info = await UserDeviceLevel.objects.filter(
            user=user, device=mission.device.id, shift=get_shift_type_now().value,
        ).get()

        if worker_device_info.superior is not None:
            publish(
                f"foxlink/users/{worker_device_info.superior.username}/subordinate-rejected",
                {
                    "subordinate_id": user.username,
                    "subordinate_name": user.full_name,
                    "total_rejected_count": worker_reject_amount_today,
                },
                qos=1,
                retain=True,
            )


@database.transaction()
async def finish_mission_by_id(
    mission_id: int, dto: MissionFinish, validate_user: User
):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if len([x for x in mission.assignees if x.username == validate_user.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.repair_start_date is None:
        raise HTTPException(400, "this mission hasn't started yet")

    if mission.repair_end_date is not None:
        raise HTTPException(400, "this mission is already closed!")

    if not mission.done_verified:
        raise HTTPException(400, "this mission is not verified as done")

    await mission.update(
        repair_end_date=datetime.utcnow(),
        machine_status=dto.devcie_status,
        cause_of_issue=dto.cause_of_issue,
        issue_solution=dto.issue_solution,
        image=dto.image,
        signature=dto.signature,
        is_cancel=False,
    )

    # set each assignee's last_event_end_date
    for w in mission.assignees:
        await WorkerStatus.objects.filter(worker=w.id).update(
            last_event_end_date=mission.event_end_date
        )

    # record this operation
    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_FINISHED.value,
        record_pk=str(mission.id),
        user=validate_user,
    )


async def delete_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to delete is not found")

    await mission.delete()


async def assign_mission(mission_id: int, username: str):
    mission = await Mission.objects.select_related(["assignees", "device"]).get(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(
            status_code=404, detail="the mission you requested is not found"
        )

    if mission.is_closed:
        raise HTTPException(
            status_code=400, detail="the mission you requested is closed"
        )

    the_user = await get_user_by_username(username)

    if the_user is None:
        raise HTTPException(
            status_code=404, detail="the user you requested is not found"
        )

    for e in mission.required_expertises:
        if e not in the_user.expertises:
            raise HTTPException(
                status_code=400,
                detail="the user does not have the expertise this mission requires.",
            )

    filter = [u for u in mission.assignees if u.username == the_user.username]

    if len(filter) == 0:
        await mission.assignees.add(the_user)  # type: ignore
        publish(
            f"foxlink/users/{the_user.username}/missions",
            {
                "type": "new",
                "mission_id": mission.id,
                "device": {
                    "project": mission.device.project,
                    "process": mission.device.process,
                    "line": mission.device.line,
                    "name": mission.device.device_name,
                },
                "name": mission.name,
                "description": mission.description,
            },
            qos=1,
            retain=True,
        )
    else:
        raise HTTPException(400, detail="the user is already assigned to this mission")


async def cancel_mission_by_id(dto: MissionCancel, validate_user: User):
    mission = await get_mission_by_id(dto.mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if len([x for x in mission.assignees if x.username == validate_user.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.repair_end_date is not None:
        raise HTTPException(400, "this mission is already closed!")

    if mission.repair_start_date is not None:
        raise HTTPException(400, "this mission is currently starting")

    await mission.update(repair_end_date=datetime.utcnow(), canceled_reason=dto.reason)


async def request_assistance(mission_id: int, validate_user: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    if len([x for x in mission.assignees if x.username == validate_user.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_emergency:
        raise HTTPException(400, "this mission is already in emergency")

    if not mission.is_started() or mission.is_closed():
        raise HTTPException(400, "this mission is not started or closed")

    await mission.update(is_emergency=True)

    publish(
        "foxlink/mission/emergency",
        {"id": mission.id, "worker": validate_user.full_name,},
        qos=1,
        retain=True,
    )

