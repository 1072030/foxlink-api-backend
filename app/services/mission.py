import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from app.core.database import (
    get_ntz_now,
    Mission,
    User,
    AuditLogHeader,
    AuditActionEnum,
    UserDeviceLevel,
    WhitelistDevice,
    WorkerStatusEnum,
    api_db,
    transaction
)
from fastapi.exceptions import HTTPException
from app.models.schema import MissionEventOut, MissionUpdate
from app.mqtt import mqtt_client
from app.services.user import get_user_by_badge, is_user_working_on_mission, move_user_to_position
from app.log import LOGGER_NAME
from app.env import (
    WORKER_REJECT_AMOUNT_NOTIFY,
    MISSION_REJECT_AMOUT_NOTIFY,
)
import logging


logger = logging.getLogger(LOGGER_NAME)


async def get_missions() -> List[Mission]:
    return await Mission.objects.select_all().all()


async def get_mission_by_id(id: int, select_fields: List[str] = ["rejections", "worker", "device", "events", "device__workshop"]) -> Optional[Mission]:
    mission = (
        await Mission.objects.select_related(
            select_fields
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


async def get_missions_by_badge(badge: str):
    missions = (
        await Mission.objects.select_related(
            ["events", "device__workshop"]
        )
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .filter(assignees__badge=badge)
        .order_by("-created_date")
        .all()
    )
    return missions


async def update_mission_by_id(id: int, dto: MissionUpdate):
    mission = await get_mission_by_id(id)
    if mission is None:
        raise HTTPException(
            status_code=404, detail="cannot get a mission by the id",
        )

    if dto.name is not None:
        mission.name = dto.name

    if dto.description is not None:
        mission.description = dto.description
    await mission.update()

    if dto.worker is not None:
        await mission.update(worker=None)  # type: ignore
        await assign_mission(id, dto.worker)


async def click_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found")
    await mission.update(notify_recv_date=get_ntz_now())


@transaction
async def start_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found")

    if worker.badge != mission.worker.badge:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_done:
        raise HTTPException(400, "this mission is already closed.")

    # if mission.is_closed or mission.is_done_cancel:
    #     raise HTTPException(400, "this mission is already closed or canceled")

    if mission.device.is_rescue:
        await mission.update(repair_end_date=get_ntz_now())
        await move_user_to_position(worker.badge, mission.device.id)
        await worker.update(status=WorkerStatusEnum.idle.value)
        return

    if mission.worker == worker and mission.is_started:
        raise HTTPException(200, 'you have already started the mission')

    # check if worker has accepted this mission
    if not mission.is_accepted:
        raise HTTPException(
            400, "one of the worker hasn't accepted the mission yet!"
        )

    await mission.update(repair_beg_date=get_ntz_now())

    worker.status = WorkerStatusEnum.working.value

    await worker.update()

    await move_user_to_position(worker.badge, mission.device.id)

    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_STARTED.value,
        user=worker.badge,
        table_name="missions",
        record_pk=str(mission.id),
    )


@transaction
async def accept_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404,
            "the mission you request is not found"
        )

    if not worker.badge == mission.worker.badge:
        raise HTTPException(
            400,
            "you are not this mission's assignee"
        )

    if not mission.device.is_rescue:
        if mission.is_started or mission.is_closed:
            raise HTTPException(
                400,
                "this mission is already started or closed"
            )

    await mission.update(
        accept_recv_date=get_ntz_now()
    )

    await worker.update(
        status=WorkerStatusEnum.moving.value,
        shift_accept_count=worker.shift_accept_count + 1
    )

    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_ACCEPTED.value,
        user=worker.badge,
        table_name="missions",
        record_pk=str(mission_id),
    )


@transaction
async def reject_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found")

    if not worker.badge == mission.worker.badge:
        raise HTTPException(400, "the mission haven't assigned to you")

    if mission.is_started or mission.is_closed:
        raise HTTPException(200, "this mission is already started or closed")

    mission_reject_count = len(mission.rejections) + 1
    mission.notify_send_date = None
    mission.notify_recv_date = None
    mission.accept_recv_date = None
    mission.repair_beg_date = None
    mission.repair_end_date = None
    if mission_reject_count >= MISSION_REJECT_AMOUT_NOTIFY:  # type: ignore
        mqtt_client.publish(
            f"foxlink/{mission.device.workshop.name}/mission/rejected",
            {
                "id": mission.id,
                "worker": worker.username,
                "rejected_count": mission_reject_count,
            },
            qos=2,
            retain=True,
        )

    worker.shift_reject_count += 1
    worker.status = WorkerStatusEnum.idle.value

    if worker.shift_reject_count >= WORKER_REJECT_AMOUNT_NOTIFY:  # type: ignore

        mqtt_client.publish(
            f"foxlink/users/{worker.superior.badge}/subordinate-rejected",
            {
                "subordinate_id": worker.badge,
                "subordinate_name": worker.username,
                "total_rejected_count": worker.shift_reject_count,
            },
            qos=2,
            retain=True,
        )

    await mission.update()
    await worker.update()

    await worker.accepted_missions.remove(mission)
    await mission.rejections.add(worker)

    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_REJECTED.value,
        record_pk=str(mission.id),
        user=worker,
    )


@ transaction
async def finish_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found"
        )

    if mission.worker != worker:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_done_shift:
        raise HTTPException(
            200, "you're no longer this missions assignee due to shifting.")

    if mission.is_done:
        raise HTTPException(200, "the mission has closed.")

    if mission.repair_beg_date is None:
        raise HTTPException(400, "You need to start mission first")

    now_time = get_ntz_now()

    await mission.update(
        is_done=True,
        is_done_finish=True,
        repair_end_date=now_time,
    )

    # set each assignee's finish_event_date
    await worker.update(
        status=WorkerStatusEnum.idle.value,
        finish_event_date=now_time
    )

    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_FINISHED.value,
        record_pk=str(mission.id),
        user=worker.badge,
    )


@ transaction
async def delete_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404,
            "the mission you request to delete is not found"
        )

    await mission.delete()


@ transaction
async def cancel_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404,
            "the mission you request to cancel is not found"
        )

    if mission.is_done_cancel:
        raise HTTPException(
            400,
            "this mission is already canceled"
        )

    if mission.is_done:
        raise HTTPException(
            400,
            "this mission is already closed"
        )

    await mission.update(
        is_done=True,
        is_done_cancel=True
    )

    await mission.worker.update(
        finish_event_date=get_ntz_now()
    )


@ transaction
async def assign_mission(mission_id: int, badge: str):
    user = await User.objects.get_or_none(badge=badge)

    mission = await Mission.objects.select_related(["events"]).get_or_none(id=mission_id)

    is_idle = (user.status == WorkerStatusEnum.idle.value)

    if mission is None:
        raise HTTPException(
            status_code=404, detail="the mission you requested is not found"
        )

    if mission.is_closed:
        raise HTTPException(
            status_code=400, detail="the mission you requested is closed"
        )

    if not is_idle:
        raise HTTPException(
            status_code=400, detail="the worker you requested is not idle"
        )

    # if worker has already working on other mission, skip
    if (await is_user_working_on_mission(badge)) == True:
        raise HTTPException(
            status_code=400, detail="the worker you requested is working on other mission"
        )

    if mission.worker:
        if badge == mission.worker.badge:
            raise HTTPException(
                status_code=400, detail="this mission is already assigned to this user"
            )
        else:
            raise HTTPException(
                status_code=400, detail="the mission is already assigned"
            )

    worker = await get_user_by_badge(badge)

    if worker is None:
        raise HTTPException(
            status_code=404, detail="the user you requested is not found"
        )

    await mission.update(
        worker=worker,
        is_lonely=False,
        notify_send_date=get_ntz_now()
    )

    await worker.update(
        status=WorkerStatusEnum.notice.value,
    )

    if mission.device.is_rescue == False:
        mqtt_client.publish(
            f"foxlink/users/{worker.current_UUID}/missions",
            {
                "type": "new",
                "mission_id": mission.id,
                "worker_now_position": worker.at_device,
                "create_date": mission.created_date,
                "device": {
                    "device_id": mission.device.id,
                    "device_name": mission.device.device_name,
                    "device_cname": mission.device.device_cname,
                    "workshop": mission.device.workshop,
                    "project": mission.device.project,
                    "process": mission.device.process,
                    "line": mission.device.line,
                },
                "name": mission.name,
                "description": mission.description,
                "events": [
                    MissionEventOut.from_missionevent(e).dict()
                    for e in mission.events
                ]
            },
            qos=2
        )


async def request_assistance(mission_id: int, validate_user: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    if mission.device.is_rescue == True:
        raise HTTPException(
            400, "you can't mark to-rescue-station mission as emergency"
        )

    if not validate_user.badge == mission.worker.badge:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_emergency:
        raise HTTPException(400, "this mission is already in emergency")

    if mission.is_closed:
        raise HTTPException(400, "this mission is already closed")

    await mission.update(is_emergency=True)

    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_EMERGENCY.value,
        table_name='missions',
        user=validate_user,
        record_pk=str(mission.id)
    )

    for worker in mission.assignees:
        try:
            mqtt_client.publish(
                f"foxlink/users/{worker.current_UUID}/missions",
                {
                    "type": "new",
                    "mission_id": mission.id,
                    "worker_now_position": worker.at_device,
                    "create_date": mission.created_date,
                    "device": {
                        "device_id": mission.device.id,
                        "device_name": mission.device.device_name,
                        "device_cname": mission.device.device_cname,
                        "workshop": mission.device.workshop,
                        "project": mission.device.project,
                        "process": mission.device.process,
                        "line": mission.device.line,
                    },
                    "name": mission.name,
                    "description": mission.description,
                    "events": [
                        MissionEventOut.from_missionevent(e).dict()
                        for e in mission.events
                    ]
                },
                qos=2
            )
        except Exception as e:
            logger.error(
                f"failed to send emergency message to {worker.superior.badge}, Exception: {repr(e)}")


async def set_mission_by_rescue_position(worker: User, rescue_position: str):
    mission = await Mission.objects.create(
        name="前往救援站",
        worker=worker.badge,
        notify_send_date=get_ntz_now(),
        notify_recv_date=get_ntz_now(),
        accept_recv_date=get_ntz_now(),
        repair_beg_date=get_ntz_now(),
        device=rescue_position,
        is_lonely=False,
        description=f"請前往救援站 {rescue_position}"
    )
    
    await worker.update(status=WorkerStatusEnum.notice.value)
    mqtt_client.publish(
        f"foxlink/users/{worker.current_UUID}/move-rescue-station",
        {
            "type": "rescue",
            "mission_id": mission.id,
            "name": mission.name,
            "description": mission.description,
            "worker_now_position": worker.at_device,
            "rescue_station": rescue_position,
        },
        qos=2,
    )

    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_ASSIGNED.value,
        user=worker.badge,
        table_name="missions",
        record_pk=str(mission.id),
        description="前往消防站",
    )
