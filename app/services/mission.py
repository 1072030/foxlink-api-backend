import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from ormar import Model
from app.core.database import (
    UserLevel,
    get_ntz_now,
    Mission,
    User,
    Device,
    AuditLogHeader,
    AuditActionEnum,
    UserDeviceLevel,
    WhitelistDevice,
    WorkerStatusEnum,
    api_db,
    transaction
)
from fastapi.background import BackgroundTasks
from fastapi.exceptions import HTTPException
from app.models.schema import MissionEventOut, MissionUpdate
from app.mqtt import mqtt_client
from app.services.user import (
    get_worker_by_badge
)
from app.log import LOGGER_NAME
from app.env import (
    WORKER_REJECT_AMOUNT_NOTIFY,
    MISSION_REJECT_AMOUT_NOTIFY,
)
import logging


logger = logging.getLogger(LOGGER_NAME)


async def get_missions() -> List[Mission]:
    return await Mission.objects.select_all().all()


async def get_mission_by_id(
    id: int,
    select_fields: List[str] = [
        "rejections",
        "worker",
        "device",
        "events",
        "device__workshop",
        "worker__shift"
    ]
) -> Optional[Mission]:
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
        .filter(worker__badge=badge)
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
        raise HTTPException(404, "the mission you click not found.")

    if mission.notify_recv_date is None:
        await mission.update(notify_recv_date=get_ntz_now())


######## REFACTORED BY OD ########
@transaction
async def start_mission(mission, worker):
    if not isinstance(mission, Mission):
        mission = await get_mission_by_id(mission)

    if not isinstance(worker, User):
        worker = await get_worker_by_badge(worker)

    await _start_mission(mission, worker)


async def _start_mission(mission, worker):
    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if worker.badge != mission.worker.badge:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_done:
        raise HTTPException(400, "this mission is already closed.")

    if mission.device.is_rescue:
        await asyncio.gather(
            mission.update(
                repair_end_date=get_ntz_now(),
                is_done=True,
                is_done_finish=True
            ),
            worker.update(
                status=WorkerStatusEnum.idle.value,
                at_device=mission.device.id,
                shift_accept_count=worker.shift_accept_count + (1 if not mission.device.is_rescue else 0),
                finish_event_date=get_ntz_now()
            )
        )
        return

    if mission.worker == worker and mission.is_started:
        raise HTTPException(200, 'you have already started the mission')

    # check if worker has accepted this mission
    if not mission.is_accepted:
        raise HTTPException(400, "the worker hasn't accept the mission yet!")

    await asyncio.gather(
        mission.update(
            repair_beg_date=get_ntz_now()
        ),
        worker.update(
            status=WorkerStatusEnum.working.value,
            at_device=mission.device.id,
            shift_accept_count=worker.shift_accept_count + 1,
        ),
        AuditLogHeader.objects.create(
            action=AuditActionEnum.MISSION_STARTED.value,
            user=worker.badge,
            table_name="missions",
            record_pk=str(mission.id),
        )
    )


@transaction
async def accept_mission(mission, worker):
    if not isinstance(mission, Mission):
        mission = await get_mission_by_id(mission)

    if not isinstance(worker, User):
        worker = await get_worker_by_badge(worker)

    await _accept_mission(mission, worker)


async def _accept_mission(mission, worker):
    if mission is None:
        raise HTTPException(
            404,
            "the mission you request is not found"
        )

    if (
        not worker.badge or
        not worker.badge == mission.worker.badge
    ):
        raise HTTPException(
            400,
            "you are not this mission's assignee"
        )

    if not mission.device.is_rescue:
        if mission.is_accepted or mission.is_started or mission.is_closed:
            raise HTTPException(
                400,
                "this mission is already started or closed"
            )

    await asyncio.gather(
        mission.update(
            accept_recv_date=get_ntz_now(),
            notify_recv_date=get_ntz_now()
        ),
        worker.update(
            status=WorkerStatusEnum.moving.value
        ),
        AuditLogHeader.objects.create(
            action=AuditActionEnum.MISSION_ACCEPTED.value,
            user=worker.badge,
            table_name="missions",
            record_pk=str(mission.id)
        )
    )


@ transaction
async def reject_mission(mission, worker):

    if not isinstance(mission, Mission):
        mission = await get_mission_by_id(mission)

    if not isinstance(worker, User):
        worker = await get_worker_by_badge(worker)

    await _reject_mission(mission, worker)


async def _reject_mission(mission, worker):
    if mission is None:
        raise HTTPException(200, "the mission you request to start is not found")

    if mission.worker is None:
        raise HTTPException(200, "the mission haven't assigned to you")

    if not worker.badge == mission.worker.badge:
        raise HTTPException(200, "the mission haven't assigned to you")

    if mission.worker == None and worker in mission.rejections:
        raise HTTPException(200, "this mission is already rejected.")

    if mission.is_started or mission.is_closed:
        raise HTTPException(200, "this mission is already started or closed")

    mission_reject_count = len(mission.rejections) + 1

    shift_reject_count = worker.shift_reject_count + 1

    await asyncio.gather(
        mission.update(
            notify_send_date=None,
            notify_recv_date=None,
            accept_recv_date=None,
            repair_beg_date=None,
            repair_end_date=None
        ),
        worker.rejected_missions.add(
            mission
        ),
        worker.accepted_missions.remove(
            mission
        ),
    )

    await asyncio.gather(
        worker.update(
            status=WorkerStatusEnum.idle.value,
            finish_event_date=get_ntz_now(),
            shift_reject_count=shift_reject_count
        ),
        AuditLogHeader.objects.create(
            table_name="missions",
            action=AuditActionEnum.MISSION_REJECTED.value,
            record_pk=str(mission.id),
            user=worker,
        )
    )

    if mission_reject_count >= MISSION_REJECT_AMOUT_NOTIFY:  # type: ignore
        await mqtt_client.publish(
            f"foxlink/{mission.device.workshop.name}/mission/rejected",
            {
                "id": mission.id,
                "worker": worker.username,
                "rejected_count": mission_reject_count,
                "timestamp": get_ntz_now()
            },
            qos=2,
            retain=True,
        )

    if shift_reject_count >= WORKER_REJECT_AMOUNT_NOTIFY:  # type: ignore

        await mqtt_client.publish(
            f"foxlink/users/{worker.superior.badge}/subordinate-rejected",
            {
                "subordinate_id": worker.badge,
                "subordinate_name": worker.username,
                "total_rejected_count": worker.shift_reject_count,
                "timestamp": get_ntz_now()
            },
            qos=2,
            retain=True,
        )


@ transaction
async def finish_mission(mission, worker):

    if not isinstance(mission, Mission):
        mission = await get_mission_by_id(mission)

    if not isinstance(worker, User):
        worker = await get_worker_by_badge(worker)

    await _finish_mission(mission, worker)


async def _finish_mission(mission, worker):
    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if mission.worker != worker:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_done_shift:
        raise HTTPException(200, "you're no longer this missions assignee due to shifting.")

    if mission.is_done:
        raise HTTPException(200, "the mission has closed.")

    if mission.repair_beg_date is None:
        raise HTTPException(400, "You need to start mission first")

    await asyncio.gather(
        mission.update(
            is_done=True,
            is_done_finish=True,
            repair_end_date=get_ntz_now()
        ),

        # set each assignee's finish_event_date
        worker.update(
            status=WorkerStatusEnum.idle.value,
            finish_event_date=get_ntz_now()
        ),

        AuditLogHeader.objects.create(
            table_name="missions",
            action=AuditActionEnum.MISSION_FINISHED.value,
            record_pk=str(mission.id),
            user=worker.badge,
        )
    )


@ transaction
async def delete_mission_by_id(mission, worker):
    if not isinstance(mission, Mission):
        mission = await get_mission_by_id(mission)

    if not isinstance(worker, User):
        worker = await get_worker_by_badge(worker)

    if mission is None:
        raise HTTPException(
            404,
            "the mission you request to delete is not found"
        )

    await _delete_mission(mission, worker)


async def _delete_mission(mission, worker):
    await asyncio.gather(
        mission.delete(),

        AuditLogHeader.objects.create(
            table_name="missions",
            action=AuditActionEnum.MISSION_DELETED.value,
            record_pk=str(mission.id),
            user=worker.badge,
        )
    )


@ transaction
async def cancel_mission(mission, worker):
    if not isinstance(mission, Mission):
        mission = await get_mission_by_id(mission)

    if not isinstance(worker, User):
        worker = await get_worker_by_badge(worker)

    await _cancel_mission(mission, worker)


async def _cancel_mission(mission, worker):
    _jobs = []

    if mission is None:
        raise HTTPException(404, "the mission you request to cancel is not found")

    if mission.is_done_cancel:
        raise HTTPException(400, "this mission is already canceled")

    if mission.is_done:
        raise HTTPException(400, "this mission is already closed")

    if mission.worker:
        _jobs.append(
            mission.worker.update(
                finish_event_date=get_ntz_now(),
                status=WorkerStatusEnum.idle.value,
            )
        )

    _jobs.append(
        mission.update(
            is_done=True,
            is_done_cancel=True
        )
    )

    _jobs.append(
        AuditLogHeader.objects.create(
            table_name="missions",
            action=AuditActionEnum.MISSION_CANCELED.value,
            record_pk=str(mission.id),
            user=worker.badge,
        )
    )

    await asyncio.gather(
        *_jobs
    )


@ transaction
async def assign_mission(mission, worker):
    if (not isinstance(mission, Mission)):
        mission = await get_mission_by_id(mission)

    if (not isinstance(worker, Model)):
        worker = await get_worker_by_badge(worker)

    await _assign_mission(mission, worker)


async def _assign_mission(mission: Mission, worker: User):
    if mission is None:
        raise HTTPException(status_code=404, detail="the mission you requested is not found")

    if worker is None:
        raise HTTPException(status_code=404, detail="the user you requested is not found")

    if not worker.status == WorkerStatusEnum.idle.value:
        raise HTTPException(status_code=400, detail="the worker you requested is not idle")

    if mission.is_closed:
        raise HTTPException(status_code=400, detail="the mission you requested is closed")

    if worker.level is not UserLevel.maintainer.value:
        raise HTTPException(
            status_code=400, detail="the worker you requested cant not assign."
        )

    if mission.worker:
        if worker.badge == mission.worker.badge:
            raise HTTPException(status_code=400, detail="this mission is already assigned to this user")
        else:
            raise HTTPException(status_code=400, detail="the mission is already assigned")

    await asyncio.gather(
        mission.update(
            worker=worker,
            is_lonely=False,
            notify_send_date=get_ntz_now()
        ),
        worker.update(
            status=WorkerStatusEnum.notice.value,
        )
    )

    if not mission.device.is_rescue:
        await mqtt_client.publish(
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
                    "workshop": mission.device.workshop.name,
                    "project": mission.device.project,
                    "process": mission.device.process,
                    "line": mission.device.line,
                },
                "name": mission.name,
                "description": mission.description,
                "events": [
                    MissionEventOut.from_missionevent(e).dict()
                    for e in mission.events
                ],
                "notify_receive_date": mission.notify_recv_date,
                "notify_send_date": mission.notify_send_date,
                "timestamp": get_ntz_now()

            },
            qos=2,
            retain=True
        )


@ transaction
async def request_assistance(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    if mission.device.is_rescue == True:
        raise HTTPException(400, "you can't mark to-rescue-station mission as emergency")

    if not worker.badge == mission.worker.badge:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_emergency:
        raise HTTPException(400, "this mission is already in emergency")

    if mission.is_closed:
        raise HTTPException(400, "this mission is already closed")

    await asyncio.gather(
        mission.update(is_emergency=True),
        AuditLogHeader.objects.create(
            action=AuditActionEnum.MISSION_EMERGENCY.value,
            table_name='missions',
            user=worker,
            record_pk=str(mission.id)
        )
    )

    try:
        await mqtt_client.publish(
            f"foxlink/users/{worker.superior.badge}/missions",
            {
                "type": "new",
                "mission_id": mission.id,
                "worker_now_position": worker.at_device,
                "create_date": mission.created_date,
                "device": {
                    "device_id": mission.device.id,
                    "device_name": mission.device.device_name,
                    "device_cname": mission.device.device_cname,
                    "workshop": mission.device.workshop.name,
                    "project": mission.device.project,
                    "process": mission.device.process,
                    "line": mission.device.line,
                },
                "name": mission.name,
                "description": mission.description,
                "events": [
                    MissionEventOut.from_missionevent(e).dict()
                    for e in mission.events
                ],
                "notify_receive_date": mission.notify_recv_date,
                "notify_send_date": mission.notify_send_date,
                "timestamp": get_ntz_now()

            },
            qos=2,
            retain=True
        )

    except Exception as e:
        logger.error(
            f"failed to send emergency message to {worker.superior.badge}, Exception: {repr(e)}"
        )


@ transaction
async def set_mission_by_rescue_position(worker: User, rescue_position: str):

    # fetch position
    rescue_position = await(
        Device.objects
        .filter(
            id=rescue_position
        ).select_related("workshop")
        .get_or_none()
    )

    # create mission
    mission = await (
        Mission.objects
        .create(
            name="前往救援站",
            worker=worker.badge,
            notify_send_date=get_ntz_now(),
            accept_recv_date=get_ntz_now(),
            repair_beg_date=get_ntz_now(),
            device=rescue_position,
            is_lonely=False,
            description=f"請前往救援站"
        )
    )

    await asyncio.gather(
        worker.update(
            status=WorkerStatusEnum.notice.value
        ),
        AuditLogHeader.objects.create(
            action=AuditActionEnum.MISSION_ASSIGNED.value,
            user=worker.badge,
            table_name="missions",
            record_pk=str(mission.id),
            description="前往消防站",
        )
    )

    await mqtt_client.publish(
        f"foxlink/users/{worker.current_UUID}/move-rescue-station",
        {
            "type": "rescue",
            "mission_id": mission.id,
            "worker_now_position": worker.at_device,
            "create_date": mission.created_date,
            "device": {
                "device_id": rescue_position.id,
                "device_name": rescue_position.device_name,
                "device_cname": rescue_position.device_cname,
                "workshop": rescue_position.workshop.name,
                "project": rescue_position.project,
                "process": rescue_position.process,
                "line": rescue_position.line,
            },
            "name": mission.name,
            "description": mission.description,
            "events": [],
            "notify_receive_date": mission.notify_recv_date,
            "notify_send_date": mission.notify_send_date,
            "timestamp": get_ntz_now()
        },
        qos=2,
        retain=True
    )
