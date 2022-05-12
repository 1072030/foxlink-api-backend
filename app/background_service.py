import logging, asyncio, aiohttp
import pytz
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.models.schema import MissionDto, MissionEventOut
from foxlink_dispatch.dispatch import Foxlink_dispatch
from app.services.mission import assign_mission
from app.services.user import get_user_first_login_time_today
from app.my_log_conf import LOGGER_NAME
from app.utils.utils import CST_TIMEZONE, get_shift_type_now, get_shift_type_by_datetime
from app.mqtt.main import publish
from app.env import (
    MQTT_BROKER,
    MAX_NOT_ALIVE_TIME,
    EMQX_USERNAME,
    EMQX_PASSWORD,
    MOVE_TO_RESCUE_STATION_TIME,
    OVERTIME_MISSION_NOTIFY_PERIOD,
)
from app.core.database import (
    CategoryPRI,
    FactoryMap,
    Mission,
    MissionEvent,
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
dispatch = Foxlink_dispatch()


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


async def check_alive_worker_routine():
    alive_worker_status = (
        await WorkerStatus.objects.select_related("worker")
        .filter(
            status__in=[WorkerStatusEnum.working.value, WorkerStatusEnum.idle.value]
        )
        .all()
    )

    async with aiohttp.ClientSession() as session:
        for w in alive_worker_status:
            async with session.get(
                f"http://{MQTT_BROKER}:18083/api/v4/clients/{w.worker.username}",
                auth=aiohttp.BasicAuth(login=EMQX_USERNAME, password=EMQX_PASSWORD),
            ) as resp:
                if resp.status != 200:
                    logger.warn("Error getting mqtt client status")
                    continue

                try:
                    content = await resp.json()
                    # if the woeker is still not connected to the broker
                    if len(content["data"]) == 0:
                        if datetime.utcnow() - w.check_alive_time > timedelta(
                            minutes=MAX_NOT_ALIVE_TIME
                        ):

                            # await w.update(status=WorkerStatusEnum.leave.value)
                            device_level = await UserDeviceLevel.objects.filter(
                                user=w.worker.username
                            ).first()
                            if device_level is not None:
                                superior = device_level.superior
                                publish(
                                    f"foxlink/users/{superior.username}/worker-unusual-offline",
                                    {
                                        "worker_id": w.worker.username,
                                        "worker_name": w.worker.full_name,
                                    },
                                    qos=1,
                                    retain=True,
                                )
                    else:
                        await w.update(check_alive_time=datetime.utcnow())
                except:
                    continue


async def notify_overtime_workers():
    working_missions = await Mission.objects.filter(repair_end_date__isnull=True).all()

    overtime_workers: List[OvertimeWorkerInfo] = []

    for m in working_missions:
        for u in m.assignees:
            first_login_timestamp = await get_user_first_login_time_today(u.username)
            if first_login_timestamp is None:
                continue

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

    if len(overtime_workers) > 0:
        publish("foxlink/overtime-workers", overtime_workers, qos=1, retain=True)


async def auto_close_missions():
    working_missions = (
        await Mission.objects.select_related(["assignees", "missionevents"])
        .filter(
            repair_start_date__isnull=True,
            repair_end_date__isnull=True,
            is_cancel=False,
        )
        .all()
    )

    working_missions = [x for x in working_missions if len(x.assignees) == 0]

    for m in working_missions:
        undone_events = [x for x in m.missionevents if x.done_verified == False]

        if len(undone_events) == 0 and len(m.missionevents) != 0:
            await m.update(is_cancel=True)


async def worker_monitor_routine():
    # when a user import device layout to the system, some devices may have been removed.
    # thus there's a chance that at_device could be null, so we need to address that.
    at_device_null_worker_status = await WorkerStatus.objects.filter(
        at_device=None
    ).all()

    for ws in at_device_null_worker_status:
        try:
            rescue_station = await Device.objects.filter(
                workshop=w.location, is_rescue=True
            ).first()
            await ws.update(at_device=rescue_station)
        except Exception:
            continue

    workers = await User.objects.filter(
        level=UserLevel.maintainer.value, is_admin=False
    ).all()

    for w in workers:
        worker_status = (
            await WorkerStatus.objects.select_related(["worker", "at_device"])
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

        if worker_status is None:
            await WorkerStatus.objects.create(
                worker=w,
                status=WorkerStatusEnum.leave.value,
                at_device=rescue_stations[0],
                last_event_end_date=datetime.utcnow(),
            )
        else:
            if worker_status.status == WorkerStatusEnum.leave.value:
                continue

            if worker_status.at_device.is_rescue == True:
                continue

            if datetime.utcnow() - worker_status.last_event_end_date < timedelta(
                minutes=MOVE_TO_RESCUE_STATION_TIME
            ):
                continue

            factory_map = await FactoryMap.objects.filter(id=w.location).get()
            rescue_distances = []

            try:
                worker_device_idx = find_idx_in_factory_map(
                    factory_map, worker_status.at_device.id
                )
            except ValueError:
                logger.error(
                    f"{worker_status.at_device.id} is not in the map {factory_map.name}"
                )

            for r in rescue_stations:
                rescue_idx = find_idx_in_factory_map(factory_map, r.id)
                rescue_distances.append(
                    {
                        "rescueID": r.id,
                        "distance": factory_map.map[worker_device_idx][rescue_idx],
                    }
                )

            # create a go-to-rescue-station mission for those workers who are not at rescue station and idle above threshold duration.
            to_rescue_station = dispatch.move_to_rescue(rescue_distances)

            mission = await Mission.objects.create(
                name="前往救援站",
                required_expertises=[],
                device=to_rescue_station,
                repair_start_date=datetime.utcnow(),
                description=f"請前往救援站 {to_rescue_station}",
            )
            await mission.assignees.add(w)

            publish(
                f"foxlink/users/{w.username}/move-rescue-station",
                {
                    "type": "rescue",
                    "mission_id": mission.id,
                    "name": mission.name,
                    "description": mission.description,
                    "rescue_station": to_rescue_station,
                },
                qos=1,
                retain=True,
            )


# TODO: 通知維修時間太長的任務給上級
async def check_mission_duration_routine():
    working_missions = (
        await Mission.objects.select_related("assignees")
        .filter(
            # repair_start_date__isnull=False,
            repair_end_date__isnull=True,
            is_cancel=False,
        )
        .all()
    )

    standardize_thresholds: List[int] = []
    total_mins = 0
    for t in OVERTIME_MISSION_NOTIFY_PERIOD:
        total_mins += t
        standardize_thresholds += [total_mins]

    working_missions = [m for m in working_missions if len(m.assignees) != 0]

    for m in working_missions:
        for idx in range(len(standardize_thresholds) - 1, -1, -1):
            if m.duration.total_seconds() >= standardize_thresholds[idx]:
                is_sent = await AuditLogHeader.objects.filter(
                    action=AuditActionEnum.MISSION_OVERTIME.value,
                    table_name="missions",
                    description=str(standardize_thresholds[idx]),
                    record_pk=m.id,
                ).exists()

                if is_sent:
                    continue

                base_worker = m.assignees[0].username
                to_notify_superior: Optional[User] = None

                for _ in range(idx + 1):
                    device_level = await UserDeviceLevel.objects.filter(
                        device=m.device.id, user=base_worker
                    ).get_or_none()

                    if device_level is None or device_level.superior is None:
                        break

                    base_worker = device_level.superior.username
                    to_notify_superior = device_level.superior

                if to_notify_superior is None:
                    break

                publish(
                    f"foxlink/users/{to_notify_superior.username}/mission-overtime",
                    {
                        "mission_id": m.id,
                        "mission_name": m.name,
                        "worker_id": m.assignees[0].username,
                        "worker_name": m.assignees[0].full_name,
                        "duration": m.duration.total_seconds(),
                    },
                    qos=1,
                )

                await AuditLogHeader.objects.create(
                    action=AuditActionEnum.MISSION_OVERTIME.value,
                    table_name="missions",
                    description=str(standardize_thresholds[idx]),
                    record_pk=m.id,
                    user=m.assignees[0].username,
                )


@database.transaction()
async def dispatch_routine():
    avaliable_missions = (
        await Mission.objects.select_related(["device", "assignees", "missionevents"])
        .filter(is_cancel=False, repair_start_date__isnull=True)
        .all()
    )

    avaliable_missions = [x for x in avaliable_missions if len(x.assignees) == 0]

    if len(avaliable_missions) == 0:
        return

    m_list = []

    for m in avaliable_missions:
        reject_count = await AuditLogHeader.objects.filter(
            action=AuditActionEnum.MISSION_REJECTED.value, record_pk=m.id
        ).count()

        for event in m.missionevents:
            event_count, pri = await asyncio.gather(
                MissionEvent.objects.select_related("mission")
                .filter(mission__device=m.device.id, category=event.category)
                .count(),
                CategoryPRI.objects.select_all()
                .filter(devices__id=m.device.id, category=event.category)
                .get_or_none(),
            )

            item = {
                "missionID": m.id,
                "event_count": event_count,
                "refuse_count": reject_count,
                "device": m.device.device_name,
                "process": m.device.process,
                "create_date": m.created_date,
            }

            if pri is not None:
                item["category"] = pri.category
                item["priority"] = pri.priority
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
        publish(
            "foxlink/no-available-worker",
            MissionDto.from_mission(mission_1st).dict(),
            qos=1,
            retain=True,
        )
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

        is_idle = (
            await WorkerStatus.objects.filter(
                worker=w.user, status=WorkerStatusEnum.idle.value
            ).count()
        ) == 1

        if not is_idle:
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
            created_date__gte=datetime.now(CST_TIMEZONE)
            .replace(hour=0, minute=0, second=0)
            .astimezone(pytz.utc)
            .date(),
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
            MissionDto.from_mission(mission_1st).dict(),
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


async def main_routine():
    await asyncio.gather(
        auto_close_missions(),
        worker_monitor_routine(),
        notify_overtime_workers(),
        check_mission_duration_routine(),
    )
    await check_alive_worker_routine()
    await dispatch_routine()
