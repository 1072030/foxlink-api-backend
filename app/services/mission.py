from app.services.device import get_device_by_id
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional
from app.core.database import Mission, User, Log, database, LogCategoryEnum
from fastapi.exceptions import HTTPException
from app.models.schema import MissionCancel, MissionCreate, MissionFinish, MissionUpdate
import sys


async def get_missions() -> List[Mission]:
    return await Mission.objects.values()


async def get_mission_by_id(id: int) -> Optional[Mission]:
    item = await Mission.objects.get_or_none(id=id)
    return item


async def get_missions_by_user_id(user_id: str):
    missions = (
        await Mission.objects.filter(assignee__id=user_id)
        .order_by("created_date")
        .exclude_fields(["assignee"])
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

    await Log.objects.create(
        category=LogCategoryEnum.MISSION_REJECTED.value,
        affected_object_key=str(mission.id),
        related_object_key=user.id,
    )

    await mission.assignees.remove(user)  # type: ignore

    related_logs_amount = await Log.objects.filter(
        category=LogCategoryEnum.MISSION_REJECTED.value,
        affected_object_key=str(mission.id),
    ).count()

    if related_logs_amount >= 2:
        logging.warn(f"Mission {mission.id} is rejected more than 2 times")


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

