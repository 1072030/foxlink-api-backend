import json
import random
from app.services.device import get_device_by_id
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.core.database import (
    CategoryPRI,
    FactoryMap,
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
from app.dispatch import FoxlinkDispatch
import sys, logging
from app.services.user import get_user_by_username


dispatch = FoxlinkDispatch()


def find_idx_in_factory_map(factory_map: FactoryMap, device_id: str) -> int:
    try:
        return factory_map.related_devices.index(device_id)
    except ValueError as e:
        msg = f"{device_id} device is not in the map {factory_map.name}"
        raise ValueError(msg)


async def worker_monitor_routine():
    workers = await User.objects.filter(
        level=UserLevel.maintainer.value, is_admin=False
    ).all()

    for w in workers:
        status = (
            await WorkerStatus.objects.select_related("worker")
            .filter(worker=w)
            .get_or_none()
        )

        # if worker is still working on mission, then we should not modify its state
        working_mission_count = (
            await Mission.objects.select_related("assignees")
            .filter(repair_end_date__isnull=True, assignees__id=w.id)
            .count()
        )

        if working_mission_count > 0:
            continue

        rescue_stations = await Device.objects.filter(
            workshop=w.location, is_rescue=True
        ).all()

        if status is None:
            await WorkerStatus.objects.create(
                worker=w,
                status=WorkerStatusEnum.idle.value,
                at_device=rescue_stations[0],
                last_event_end_date=datetime.utcnow(),
            )
        else:
            factory_map = await FactoryMap.objects.filter(id=w.location).get()
            rescue_distances = []

            worker_device_idx = find_idx_in_factory_map(
                factory_map, status.at_device.id
            )

            for r in rescue_stations:
                rescue_idx = find_idx_in_factory_map(factory_map, r.id)
                rescue_distances.append(
                    {
                        "rescueID": r.id,
                        "distance": factory_map.map[worker_device_idx][rescue_idx],
                    }
                )

            await status.update(
                status=WorkerStatusEnum.idle.value,
                at_device=dispatch.move_to_rescue(rescue_distances),
            )


@database.transaction()
async def dispatch_routine():
    await worker_monitor_routine()

    avaliable_missions = (
        await Mission.objects.select_related(["device", "assignees"])
        .filter(is_cancel=False, repair_start_date__isnull=True)
        .all()
    )

    avaliable_missions = [x for x in avaliable_missions if len(x.assignees) == 0]

    if len(avaliable_missions) == 0:
        return

    m_list = []

    for m in avaliable_missions:
        p = (
            await CategoryPRI.objects.select_all()
            .filter(devices__id=m.device.id)
            .get_or_none()
        )

        reject_count = await AuditLogHeader.objects.filter(
            action=AuditActionEnum.MISSION_REJECTED.value, record_pk=m.id
        ).count()

        item = {
            "missionID": m.id,
            "event_count": 1,  # TODO
            "refuse_count": reject_count,
            "device": m.device.device_name,
            "process": m.device.process,
            "create_date": m.created_date,
        }

        if p is not None:
            item["category"] = p.category
            item["priority"] = p.priority
        else:
            item["category"] = 0
            item["priority"] = 0
        m_list.append(item)

    dispatch.get_missions(m_list)
    mission_1st_id = dispatch.mission_priority().item()
    mission_1st = await Mission.objects.filter(id=mission_1st_id).select_all().get()

    can_dispatch_workers = (
        await UserDeviceLevel.objects.select_related("user")
        .filter(
            device__id=mission_1st.device.id,
            level__gt=0,
            user__location=mission_1st.device.workshop.id,
        )
        .all()
    )

    if len(can_dispatch_workers) == 0:
        logging.warn(f"No workers available to dispatch for mission {mission_1st}")
        return

    factory_map = await FactoryMap.objects.filter(
        id=mission_1st.device.workshop.id
    ).get()

    distance_matrix: List[List[float]] = factory_map.map
    mission_device_idx = find_idx_in_factory_map(factory_map, mission_1st.device.id)

    w_list = []
    for w in can_dispatch_workers:
        if w.user.level != UserLevel.maintainer.value:
            continue

        # if worker has already working on other mission, skip
        if (
            await Mission.objects.filter(
                assignees__id=w.user.id, repair_start_date__isnull=True
            ).count()
            > 0
        ):
            continue

        worker_status = await WorkerStatus.objects.filter(worker=w.user).get()

        if worker_status.status != WorkerStatusEnum.idle.value:
            continue

        daily_count = await AuditLogHeader.objects.filter(
            action=AuditActionEnum.MISSION_ASSIGNED.value,
            user=w.user,
            created_date__gte=datetime.utcnow().date(),
        ).count()

        worker_device_idx = find_idx_in_factory_map(
            factory_map, worker_status.at_device.id
        )

        item = {
            "workerID": w.user.username,
            "distance": distance_matrix[mission_device_idx][worker_device_idx],
            "idle_time": (
                datetime.utcnow() - worker_status.last_event_end_date
            ).total_seconds(),
            "daily_count": daily_count,
            "level": w.level,
        }
        w_list.append(item)
    dispatch.get_dispatch_info(w_list)
    worker_1st = dispatch.worker_dispatch()

    logging.info(
        "dispatching mission {} to worker {}".format(mission_1st.id, worker_1st)
    )

    try:
        await assign_mission(mission_1st.id, worker_1st)

        status = (
            await WorkerStatus.objects.select_related("worker")
            .filter(worker__username=worker_1st)
            .get_or_none()
        )

        w = await User.objects.filter(username=worker_1st).get()

        if status is None:
            status = await WorkerStatus.objects.create(
                worker=w,
                status=WorkerStatusEnum.working.value,
                at_device=mission_1st.device.id,
            )
        else:
            await status.update(
                status=WorkerStatusEnum.working.value, at_device=mission_1st.device.id
            )

        await AuditLogHeader.objects.create(
            table_name="missions",
            record_pk=mission_1st.id,
            action=AuditActionEnum.MISSION_ASSIGNED.value,
            user=w,
        )
    except Exception as e:
        logging.error("cannot assign to worker {}".format(worker_1st))


async def get_missions() -> List[Mission]:
    return await Mission.objects.values()


async def get_mission_by_id(id: int) -> Optional[Mission]:
    item = await Mission.objects.select_all().get_or_none(id=id)
    return item


async def get_missions_by_user_id(user_id: str):
    missions = (
        await Mission.objects.select_related(["assignees", "device"])
        .filter(assignees__id=user_id)
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
        logging.error(sys.exc_info())
        raise HTTPException(
            status_code=400, detail="raise a error when inserting mission into databse",
        )

    await dispatch_routine()
    return created_mission


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


async def reject_mission_by_id(mission_id: int, user: User):
    mission = await Mission.objects.select_related("assignees").get_or_none(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    filter = [u for u in mission.assignees if u.id == user.id]

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

    related_logs_amount = await AuditLogHeader.objects.filter(
        record_pk=str(mission.id),
        action=AuditActionEnum.MISSION_REJECTED.value,
        user=user,
    ).count()

    if related_logs_amount >= 2:
        publish(
            "foxlink/mission/rejected",
            {
                "id": mission.id,
                "worker": user.full_name,
                "rejected_count": related_logs_amount,
            },
            1,
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

    filter = [u for u in mission.assignees if u.id == the_user.id]

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
            },
            1,
        )
    else:
        raise HTTPException(400, detail="the user is already assigned to this mission")


async def cancel_mission_by_id(dto: MissionCancel, validate_user: Optional[User]):
    mission = await get_mission_by_id(dto.mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if mission.assignee is None:
        raise HTTPException(
            400, "this mission hasn't assigned to anyone yet",
        )

    if validate_user is not None:
        if mission.assignee.id != validate_user.id:
            raise HTTPException(
                400, "you are not this mission's assignee",
            )

    if mission.repair_end_date is not None:
        raise HTTPException(400, "this mission is already closed!")

    if mission.repair_start_date is not None:
        raise HTTPException(400, "this mission is currently starting")

    await mission.update(repair_end_date=datetime.utcnow(), canceled_reason=dto.reason)


# TODO: to be implemented
async def request_assistance(mission_id: int):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request is not found")

    if not mission.is_started() or mission.is_closed():
        raise HTTPException(400, "this mission is not started or closed")

    # TODO: complete assistant work flow

