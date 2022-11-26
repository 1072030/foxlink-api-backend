from datetime import datetime, timedelta
import time
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


async def get_mission_by_id(id: int, select_fields: List[str] = ["worker", "device", "events", "device__workshop"]) -> Optional[Mission]:
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
            

async def start_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found")

    if worker.badge != mission.worker.badge:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.device.is_rescue:
        await mission.update(repair_end_date=get_ntz_now())
        await move_user_to_position(worker.badge, mission.device.id)
        mqtt_client.publish(
            f"foxlink/users/{worker.badge}/missions/finish",
            {
                "mission_id": mission.id,
                "mission_state": "finish"
            },
            qos=2,
        )
        return

    if mission.is_closed or mission.is_cancel:
        raise HTTPException(400, "this mission is already closed or canceled")

    if mission.worker == worker and mission.is_started:
        raise HTTPException(200, 'you have already started the mission')

    # check if worker has accepted this mission
    if not mission.is_accepted:
        raise HTTPException(
            400, "one of the assignees hasn't accepted the mission yet!"
        )

    # if mission is already started,
    # for example there is previous worker who has started the mission, then we shouldn't update repair start date.
    await mission.update(repair_beg_date=get_ntz_now())

    worker.dispatch_count += 1
    worker.status = WorkerStatusEnum.working.value

    await worker.update()

    await move_user_to_position(worker.badge, mission.device.id)
    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_STARTED.value,
        user=worker.badge,
        table_name="missions",
        record_pk=str(mission.id),
    )


async def accept_mission(mission_id: int, worker: User):
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
        accept_recv_date=get_ntz_now(),
        notify_recv_date=get_ntz_now()
    )

    await worker.update(
        status=WorkerStatusEnum.moving.value,
    )
    
    await AuditLogHeader.objects.create(
        action=AuditActionEnum.MISSION_ACCEPTED.value,
        user=worker.badge,
        table_name="missions",
        record_pk=str(mission_id),
    )


async def reject_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found")

    if not worker.badge == mission.worker.badge:
        raise HTTPException(400, "the mission haven't assigned to you")

    if mission.is_started or mission.is_closed:
        raise HTTPException(200, "this mission is already started or closed")

    await mission.update(worker=None)  # type: ignore

    await AuditLogHeader.objects.create(
        table_name="missions",
        action=AuditActionEnum.MISSION_REJECTED.value,
        record_pk=str(mission.id),
        user=worker,
    )

    mission_reject_amount = await (Mission.objects
        .select_related('users')
        .filter(
            mission=mission,
            user=worker
        )
        .count()
    )

    if mission_reject_amount >= MISSION_REJECT_AMOUT_NOTIFY:  # type: ignore
        mqtt_client.publish(
            f"foxlink/{mission.device.workshop.name}/mission/rejected",
            {
                "id": mission.id,
                "worker": worker.username,
                "rejected_count": mission_reject_amount,
            },
            qos=2,
            retain=True,
        )

    worker_reject_amount_today = await (User.objects
        .select_related("missions")
        .filter(
            user=worker,
            created_date__gte=get_ntz_now(),
        )
        .count()
    )

    if worker_reject_amount_today >= WORKER_REJECT_AMOUNT_NOTIFY:  # type: ignore
        
        mqtt_client.publish(
            f"foxlink/users/{worker.superior.badge}/subordinate-rejected",
            {
                "subordinate_id": worker.badge,
                "subordinate_name": worker.username,
                "total_rejected_count": worker_reject_amount_today,
            },
            qos=2,
            retain=True,
        )


async def finish_mission_by_id(mission_id: int, worker: User):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, "the mission you request to start is not found"
        )

    if mission.worker != worker:
        raise HTTPException(400, "you are not this mission's assignee")

    if mission.is_shifted:
        raise HTTPException(200, "you're no longer this missions assignee due to shifting.")

    now_time = get_ntz_now()

    async with api_db.transaction():
        await mission.update(
            repair_end_date=now_time, is_cancel=False,
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
         

async def delete_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404, 
            "the mission you request to delete is not found"
        )

    await mission.delete()


async def cancel_mission_by_id(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(
            404,
            "the mission you request to cancel is not found"
        )

    if mission.is_cancel:
        raise HTTPException(
            400,
            "this mission is already canceled"
        )

    if mission.is_closed:
        raise HTTPException(
            400,
            "this mission is already finished"
        )

    await mission.update(is_cancel=True)

    await mission.worker.update(
        finish_event_date=get_ntz_now()
    )


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
                status_code=400, detail="the mission is already assigned")

    the_user = await get_user_by_badge(badge)

    if the_user is None:
        raise HTTPException(
            status_code=404, detail="the user you requested is not found"
        )

    await mission.update(
        worker=the_user,
        notify_send_date = get_ntz_now()
    )
    
    await the_user.update(
        status=WorkerStatusEnum.notice.value,
    )



    mqtt_client.publish(
        f"foxlink/users/{the_user.badge}/missions",
        {
            "type": "new",
            "mission_id": mission.id,
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
            "assingees": [{
                "badge": the_user.badge,
                "username":the_user.username
            }],
            "events": [
                MissionEventOut.from_missionevent(e).dict()
                for e in mission.events
            ],
            "is_started": mission.is_started,
            "is_closed": mission.is_closed,
            "is_cancel": mission.is_cancel,
            "created_date": mission.created_date,
            "updated_date": mission.updated_date,
        },
        qos=2,
        retain=True,
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
                f"foxlink/users/{worker.superior.badge}/missions",
                {
                    "type": "emergency",
                    "mission_id": mission.id,
                    "name": mission.name,
                    "description": mission.description,
                    "worker": {
                        "badge": worker.badge,
                        "username": worker.username,
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
                qos=2,
            )
        except Exception as e:
            logger.error(
                f"failed to send emergency message to {worker.superior.badge}, Exception: {repr(e)}")


async def is_mission_in_whitelist(mission_id: int):
    m = await get_mission_by_id(mission_id, select_fields=["device"])

    if m is None:
        raise HTTPException(404, "the mission you request is not found")

    whitelist_device = await WhitelistDevice.objects.select_related(['workers']).filter(device=m.device).get_or_none()

    if whitelist_device is None:
        return False

    if len(whitelist_device.workers) == 0:
        return False

    return True
