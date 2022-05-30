import asyncio
from app.services.device import get_device_by_id
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.core.database import (
    Mission,
    User,
    AuditLogHeader,
    AuditActionEnum,
    UserDeviceLevel,
    WorkerStatus,
    WorkerStatusEnum,
    database,
)
from fastapi.exceptions import HTTPException
from app.models.schema import MissionEventOut, MissionUpdate
from app.mqtt.main import publish
import logging
from app.services.user import get_user_by_username, move_user_to_position
from app.my_log_conf import LOGGER_NAME
from app.env import WORKER_REJECT_AMOUNT_NOTIFY, MISSION_REJECT_AMOUT_NOTIFY
from app.utils.utils import get_shift_type_now, CST_TIMEZONE

logger = logging.getLogger(LOGGER_NAME)


async def get_missions() -> List[Mission]:
    return await Mission.objects.select_all().all()


async def get_mission_by_id(id: int) -> Optional[Mission]:
    mission = (
        await Mission.objects.select_related(
            ["assignees", "device", "missionevents", "device__workshop"]
        )
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .filter(id=id)
        .get_or_none()
    )

    return mission


async def get_missions_by_username(username: str):
    missions = (
        await Mission.objects.select_related(
            ["assignees", "device", "missionevents", "device__workshop"]
        )
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .filter(assignees__username=username)
        .order_by("-created_date")
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

        if dto.is_cancel is not None:
            updateDict["is_cancel"] = dto.is_cancel

        await mission.update(None, **updateDict)
    except:
        raise HTTPException(status_code=400, detail="cannot update mission")

    return True


@database.transaction()
async def start_mission_by_id(mission_id: int, worker: User):
    mission = await Mission.objects.select_related(["assignees", "device"]).get_or_none(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if len([x for x in mission.assignees if x.username == worker.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.device.is_rescue:
        await asyncio.gather(
            mission.update(repair_end_date=datetime.utcnow()),
            move_user_to_position(worker.username, mission.device.id),
        )
        return

    if mission.is_started or mission.is_closed:
        raise HTTPException(400, "this mission is already started or closed")

    for worker in mission.assignees:
        # Check worker has accepted the mission or not.
        accept_count = await AuditLogHeader.objects.filter(
            action=AuditActionEnum.MISSION_ACCEPTED.value,
            user=worker.username,
            record_pk=str(mission_id),
        ).count()

        if accept_count == 0:
            raise HTTPException(
                400, "one of the assignees hasn't accepted the mission yet!"
            )

    await mission.update(repair_start_date=datetime.utcnow())

    for worker in mission.assignees:
        worker_status = await WorkerStatus.objects.filter(worker=worker).get()
        worker_status.dispatch_count += 1
        worker_status.status = WorkerStatusEnum.working.value
        await worker_status.update()
        await asyncio.gather(
            move_user_to_position(worker.username, mission.device.id),
            AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_STARTED.value,
                user=worker.username,
                table_name="missions",
                record_pk=str(mission.id),
            ),
        )


async def accept_mission(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    if len([x for x in mission.assignees if x.username == worker.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_started or mission.is_closed:
        raise HTTPException(400, "this mission is already started or closed")

    if mission.device.is_rescue:
        raise HTTPException(
            400,
            "to-rescue-station mission cannot be accepted, use start_mission api instead",
        )

    # Check worker has accepted the mission or not.
    # accept_count = await AuditLogHeader.objects.filter(
    #     action=AuditActionEnum.MISSION_ACCEPTED.value,
    #     user=worker.username,
    #     record_pk=mission_id,
    # ).count()

    # if accept_count > 0:
    #     raise HTTPException(400, "you have already accepted the mission")

    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_ACCEPTED.value,
        user=worker.username,
        table_name="missions",
        record_pk=str(mission_id),
    )


async def reject_mission_by_id(mission_id: int, user: User):
    mission = await Mission.objects.select_related("assignees").get_or_none(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if len([u for u in mission.assignees if u.username == user.username]) == 0:
        raise HTTPException(400, "the mission haven't assigned to you")

    if mission.is_started or mission.is_closed:
        raise HTTPException(400, "this mission is already started or closed")

    # accept_count = await AuditLogHeader.objects.filter(
    #     action=AuditActionEnum.MISSION_ACCEPTED.value,
    #     user=user.username,
    #     record_pk=str(mission_id),
    # ).count()

    # if accept_count > 0:
    #     raise HTTPException(400, "you have already accepted the mission")

    await mission.assignees.remove(user)  # type: ignore

    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_REJECTED.value,
        record_pk=str(mission.id),
        user=user,
    )

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
        created_date__gte=datetime.now(CST_TIMEZONE),
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
async def finish_mission_by_id(mission_id: int, validate_user: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if len([x for x in mission.assignees if x.username == validate_user.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if not mission.is_started:
        raise HTTPException(400, "this mission hasn't started yet")

    if mission.is_closed:
        raise HTTPException(400, "this mission is already closed!")

    # a hack for async property_field
    is_done = await mission.is_done_events  # type: ignore

    if not is_done:
        raise HTTPException(400, "this mission is not verified as done")

    await mission.update(
        repair_end_date=datetime.utcnow(), is_cancel=False,
    )

    event_end_dates: List[datetime] = [
        e.event_end_date - timedelta(hours=8) for e in mission.missionevents
    ]
    event_end_dates.sort(reverse=True)

    # set each assignee's last_event_end_date
    for w in mission.assignees:
        await WorkerStatus.objects.filter(worker=w).update(
            status=WorkerStatusEnum.idle.value, last_event_end_date=event_end_dates[0]
        )

    # record this operation
    for w in mission.assignees:
        await AuditLogHeader.objects.create(
            table_name="missions",
            action=AuditActionEnum.MISSION_FINISHED.value,
            record_pk=str(mission.id),
            user=w.username,
        )


async def delete_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to delete is not found")

    await mission.delete()


async def cancel_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to delete is not found")

    if mission.is_cancel:
        raise HTTPException(400, "this mission is already canceled")

    if mission.is_closed:
        raise HTTPException(400, "this mission is already finished")

    await mission.update(is_cancel=True)


async def assign_mission(mission_id: int, username: str):
    mission = await Mission.objects.select_related(
        ["assignees", "device", "missionevents"]
    ).get_or_none(id=mission_id)

    if mission is None:
        raise HTTPException(
            status_code=404, detail="the mission you requested is not found"
        )

    if mission.is_closed:
        raise HTTPException(
            status_code=400, detail="the mission you requested is closed"
        )

    if len(mission.assignees) > 0:
        raise HTTPException(status_code=400, detail="the mission is already assigned")

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
                "events": [
                    MissionEventOut.from_missionevent(e).dict()
                    for e in mission.missionevents
                ],
            },
            qos=1,
        )
    else:
        raise HTTPException(400, detail="the user is already assigned to this mission")


@database.transaction()
async def request_assistance(mission_id: int, validate_user: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    if mission.device.is_rescue == True:
        raise HTTPException(
            400, "you can't mark to-rescue-station mission as emergency"
        )

    if len([x for x in mission.assignees if x.username == validate_user.username]) == 0:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_emergency:
        raise HTTPException(400, "this mission is already in emergency")

    if mission.is_closed:
        raise HTTPException(400, "this mission is already closed")

    await mission.update(is_emergency=True)

    for worker in mission.assignees:
        try:
            worker_device_level = await UserDeviceLevel.objects.filter(
                user=worker, device=mission.device
            ).first()

            if worker_device_level.superior is None:
                continue

            publish(
                f"foxlink/users/{worker_device_level.superior.username}/missions",
                {
                    "type": "emergency",
                    "mission_id": mission.id,
                    "name": mission.name,
                    "description": mission.description,
                    "worker": {
                        "username": worker.username,
                        "full_name": worker.full_name,
                    },
                    "device": {
                        "project": mission.device.project,
                        "process": mission.device.process,
                        "line": mission.device.line,
                        "name": mission.device.device_name,
                    },
                    "events": [
                        MissionEventOut.from_missionevent(e).dict()
                        for e in mission.missionevents
                    ],
                },
                qos=1,
            )
        except:
            continue

