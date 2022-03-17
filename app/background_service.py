import logging, asyncio
from typing import List
from datetime import datetime, timedelta

from pydantic import BaseModel
from app.dispatch import FoxlinkDispatch
from app.services.mission import assign_mission
from app.services.user import get_employee_work_timestamp_today
from app.my_log_conf import LOGGER_NAME
from app.utils.utils import get_shift_type_now, get_shift_type_by_datetime
from app.mqtt.main import publish
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


logger = logging.getLogger(LOGGER_NAME)
dispatch = FoxlinkDispatch()


class MissionInfo(BaseModel):
    mission_id: str
    mission_name: str
    device_id: str
    mission_start_date: datetime


class OvertimeWorkerInfo(BaseModel):
    worker_id: str
    worker_name: str
    working_on_mission: MissionInfo


def find_idx_in_factory_map(factory_map: FactoryMap, device_id: str) -> int:
    try:
        return factory_map.related_devices.index(device_id)
    except ValueError as e:
        msg = f"{device_id} device is not in the map {factory_map.name}"
        raise ValueError(msg)


async def notify_overtime_workers():
    working_missions = await Mission.objects.filter(repair_end_date__isnull=True).all()

    overtime_workers: List[OvertimeWorkerInfo] = []

    for m in working_missions:
        for u in m.assignees:
            first_login_timestamp = await get_employee_work_timestamp_today(u.username)
            if get_shift_type_now() != get_shift_type_by_datetime(
                first_login_timestamp
            ):

                overtime_workers.append(
                    {
                        "worker_id": u.username,
                        "worker_name": u.full_name,
                        "working_on_mission": {
                            "mission_id": m.id,
                            "mission_name": m.name,
                            "device_id": m.device.id,
                            "mission_start_date": m.created_date,
                        },
                    }
                )
    publish("foxlink/overtime-workers", overtime_workers, qos=1, retain=True)


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
            .filter(repair_end_date__isnull=True, assignees__username=w.username)
            .count()
        )

        if working_mission_count > 0:
            continue

        rescue_stations = await Device.objects.filter(
            workshop=w.location, is_rescue=True
        ).all()

        if len(rescue_stations) == 0:
            logger.error(f"there's no rescue station in workshop {w.location.id}")
            logger.error(f"you should create a rescue station as soon as possible")
            return

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
    await asyncio.gather(worker_monitor_routine(), notify_overtime_workers())

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
            .filter(devices__id=m.device.id, category=m.category)
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
        logger.warn(f"No workers available to dispatch for mission {mission_1st.id}")
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

        user_login_logs = await AuditLogHeader.objects.filter(
            user=w.user.username,
            action=AuditActionEnum.USER_LOGIN.value,
            created_date__gte=datetime.utcnow() - timedelta(hours=12),
        ).count()

        if user_login_logs == 0:
            continue

        # if worker has already working on other mission, skip
        if (
            await Mission.objects.filter(
                assignees__username=w.user.username, repair_start_date__isnull=True
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

    if len(w_list) == 0:
        logger.error("no worker available to fix devices")
        publish(
            "foxlink/no-available-worker",
            {
                "mission_id": mission_1st.id,
                "device_id": mission_1st.device.id,
                "description": mission_1st.description,
            },
            qos=1,
            retain=True,
        )
        return

    dispatch.get_dispatch_info(w_list)
    worker_1st = dispatch.worker_dispatch()

    logger.info(
        "dispatching mission {} to worker {}".format(mission_1st.id, worker_1st)
    )

    try:
        await assign_mission(mission_1st.id, worker_1st)

        # status = (
        #     await WorkerStatus.objects.select_related("worker")
        #     .filter(worker__username=worker_1st)
        #     .get_or_none()
        # )

        # w = await User.objects.filter(username=worker_1st).get()

        # if status is None:
        #     status = await WorkerStatus.objects.create(
        #         worker=w,
        #         status=WorkerStatusEnum.working.value,
        #         at_device=mission_1st.device.id,
        #     )
        # else:
        #     await status.update(
        #         status=WorkerStatusEnum.working.value, at_device=mission_1st.device.id
        #     )

        await AuditLogHeader.objects.create(
            table_name="missions",
            record_pk=mission_1st.id,
            action=AuditActionEnum.MISSION_ASSIGNED.value,
            user=w.user.username,
        )
    except Exception as e:
        logger.error("cannot assign to worker {}".format(worker_1st))
        raise e
