import random
from app.services.device import get_device_by_id
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.core.database import (
    CategoryPRI,
    Mission,
    User,
    AuditLogHeader,
    AuditActionEnum,
    UserDeviceLevel,
    database,
)
from fastapi.exceptions import HTTPException
from app.models.schema import MissionCancel, MissionCreate, MissionFinish, MissionUpdate
from app.mqtt.main import publish
from app.dispatch import FoxlinkDispatch
import sys, logging
from app.services.user import get_user_by_username


dispatch = FoxlinkDispatch()


async def dispatch_routine():
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

        item = {
            "missionID": m.id,
            "event_count": 1,  # TODO
            "refuse_count": 1,  # TODO
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
    mission_1st = (
        await Mission.objects.filter(id=mission_1st_id).select_related("device").get()
    )

    can_dispatch_workers = (
        await UserDeviceLevel.objects.filter(
            device__id=mission_1st.device.id, level__gt=0
        )
        .select_related("user")
        .all()
    )

    if len(can_dispatch_workers) == 0:
        logging.warn(f"No workers available to dispatch for mission {mission_1st}")
        return

    w_list = []

    for w in can_dispatch_workers:
        item = {
            "workerID": w.user.username,
            "distance": random.randint(1, 22),  # TODO
            "idle_time": 0,  # TODO
            "daily_count": 0,  # TODO
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


async def start_mission_by_id(mission_id: int, validate_user: Optional[User]):
    mission = await Mission.objects.select_related("assignees").get_or_none(
        id=mission_id
    )

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if mission.assignee is None:
        raise HTTPException(
            404, "the assignee of this mission is missing. cannot start this mission"
        )

    if validate_user is not None:
        filter = [u for u in mission.assignees if u.id == validate_user.id]
        if len(filter) == 0:
            raise HTTPException(
                400, "you are not this mission's assignee",
            )

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


async def finish_mission_by_id(
    mission_id: int, dto: MissionFinish, validate_user: Optional[User]
):
    mission = await get_mission_by_id(mission_id)

    if mission is None:
        raise HTTPException(404, "the mission you request to start is not found")

    if mission.assignee is None:
        raise HTTPException(
            404, "the assignee of this mission is missing. cannot finish this mission"
        )

    if validate_user is not None:
        if mission.assignee.id != validate_user.id:
            raise HTTPException(
                400, "you are not this mission's assignee",
            )

    if mission.repair_start_date is None:
        raise HTTPException(400, "this mission hasn't started yet")

    if mission.repair_end_date is not None:
        raise HTTPException(400, "this mission is already closed!")

    if not mission.done_verified:
        raise HTTPException(400, "this mission is not verified as done")

    tx = await database.transaction()
    try:
        await tx.start()
        await mission.update(
            repair_end_date=datetime.utcnow(),
            machine_status=dto.devcie_status,
            cause_of_issue=dto.cause_of_issue,
            issue_solution=dto.issue_solution,
            image=dto.image,
            signature=dto.signature,
            is_cancel=False,
        )
    except Exception as e:
        logging.error("cannot mark a mission as done: ", e)
        await tx.rollback()
    else:
        await tx.commit()


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

