import logging
import asyncio
import aiohttp
import uuid
import signal
import time
import argparse
import functools
from databases import Database
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.models.schema import MissionDto
from app.routes import user
from app.services.device import get_workers_from_whitelist_devices
from app.utils.timer import Ticker
from foxlink_dispatch.dispatch import Foxlink_dispatch
from app.foxlink.model import FoxlinkEvent
from app.foxlink.utils import assemble_device_id
from app.foxlink.db import foxlink_dbs
from app.services.mission import (
    assign_mission,
    get_mission_by_id,
    reject_mission_by_id,
    set_mission_by_rescue_position
)
from app.services.user import (

    get_user_working_mission,
    is_worker_in_whitelist,
)

from app.utils.utils import get_current_shift_type
from app.mqtt import mqtt_client
from app.env import (
    MISSION_ASSIGN_OT_MINUTES,
    DISABLE_FOXLINK_DISPATCH,
    FOXLINK_EVENT_DB_HOSTS,
    FOXLINK_EVENT_DB_PWD,
    FOXLINK_EVENT_DB_USER,
    FOXLINK_EVENT_DB_NAME,
    MQTT_BROKER,
    MAX_NOT_ALIVE_TIME,
    EMQX_USERNAME,
    EMQX_PASSWORD,
    WORKER_IDLE_OT_RESCUE_MINUTES,
    MQTT_PORT,
    MISSION_WORK_OT_NOTIFY_PYRAMID_MINUTES,
    RECENT_EVENT_PAST_DAYS,
)
from app.core.database import (
    transaction,
    get_ntz_now,
    ShiftType,
    FactoryMap,
    Mission,
    MissionEvent,
    User,
    AuditLogHeader,
    AuditActionEnum,
    WorkerStatusEnum,
    UserLevel,
    Device,
    WhitelistDevice,
    api_db,
)

from pymysql.err import (
    Warning, Error,
    InterfaceError, DataError, DatabaseError,
    OperationalError,
    IntegrityError, InternalError, NotSupportedError,
    ProgrammingError
)

import traceback

logger = logging.getLogger(f"foxlink(daemon)")

logger.setLevel(logging.INFO)

dispatch = Foxlink_dispatch()

_terminate = None


def show_duration(func):
    async def wrapper(*args, **_args):
        start = time.perf_counter()
        result = await func(*args, **_args)
        end = time.perf_counter()
        logger.warning(f'[{func.__name__}] took {end - start:.2f} seconds.')
        return result
    return wrapper


def find_idx_in_factory_map(factory_map: FactoryMap, device_id: str) -> int:
    try:
        return factory_map.related_devices.index(device_id)
    except ValueError as e:
        msg = f"{device_id} device is not in the map {factory_map.name}"
        raise ValueError(msg)


# @show_duration
# async def check_alive_worker_routine():
#     """檢查員工是否在線，如果沒有在線，則通知上層"""
#     alive_workers = (
#         await User.objects
#         .filter(
#             status__in=[WorkerStatusEnum.working.value, WorkerStatusEnum.idle.value]
#         )
#         .all()
#     )

#     async with aiohttp.ClientSession() as session:
#         for worker in alive_workers:
#             async with session.get(
#                 f"http://{MQTT_BROKER}:18083/api/v4/clients/{worker.badge}",
#                 auth=aiohttp.BasicAuth(
#                     login=EMQX_USERNAME,
#                     password=EMQX_PASSWORD
#                 ),
#             ) as resp:
#                 if resp.status != 200:
#                     logger.warn("Error getting mqtt client status")
#                     continue

#                 try:
#                     content = await resp.json()
#                     # if the woeker is still not connected to the broker
#                     if len(content["data"]) == 0:
#                         if get_ntz_now() - worker.check_alive_time > timedelta(
#                             minutes=MAX_NOT_ALIVE_TIME
#                         ):
#                             (
#                                 f"foxlink/users/{worker.superior.badge}/worker-unusual-offline",
#                                 {
#                                     "worker_id": worker.badge,
#                                     "worker_name": worker.username,
#                                 },
#                                 qos=2,
#                                 retain=True,
#                             )
#                     else:
#                         await worker.update(check_alive_time=get_ntz_now())
#                 except:
#                     continue


# done
@transaction
@show_duration
async def mission_shift_routine():
    # filter out non-rescue missions that're in process but hasn't completed
    working_missions = (
        await Mission.objects
        .filter(
            is_done=False,
            repair_end_date__isnull=True,
            worker__isnull=False
        )
        .select_related(
            ["worker", "events", "device"]
        )
        .filter(
            device__is_rescue=False,
        )
        .all()
    )

    # prefetch current_shift
    current_shift = await get_current_shift_type()

    for mission in working_missions:
        worker_shift = ShiftType(mission.worker.shift.id)

        # shift swap required
        if current_shift != worker_shift:

            # send mission finish message
            await mqtt_client.publish(
                f"foxlink/users/{mission.worker.badge}/missions/finish",
                {
                    "mission_id": mission.id,
                    "mission_state": "ovetime-duty"
                },
                qos=2,
            )

            # cancel mission
            await mission.update(
                is_done=True,
                is_done_shift=True,
                description='換班任務，自動結案'
            )

            # replicate mission of the new shift
            replicate_mission = await Mission.objects.create(
                name=mission.name,
                description=f"換班任務，沿用 Mission ID: {mission.id}",
                device=mission.device,
                is_emergency=mission.is_emergency
            )

            # replicate mission events for the new mission
            for e in mission.events:
                replicate_event = MissionEvent(
                    event_id=e.event_id,
                    host=e.host,
                    table_name=e.table_name,
                    category=e.category,
                    message=e.message,
                    event_beg_date=e.event_beg_date,
                    event_end_date=e.event_end_date
                )
                await replicate_mission.events.add(replicate_event)

            # update worker status
            await mission.worker.update(
                status=WorkerStatusEnum.idle.value,
                finish_event_date=get_ntz_now()
            )

            # create audit log
            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_USER_DUTY_SHIFT.value,
                table_name="missions",
                description=f"員工換班，維修時長: {get_ntz_now() - mission.repair_beg_date if mission.repair_beg_date is not None else 0}",
                user=mission.worker.badge,
                record_pk=mission.id,
            )


# done
@transaction
@show_duration
async def auto_close_missions():
    # auto complete non-started missions if all the mission events are cured.
    pending_start_missions = (
        await Mission.objects
        .select_related(
            ["events", "worker"]
        )
        .filter(
            is_done=False,
            repair_beg_date__isnull=True
        )
        .all()
    )

    for mission in pending_start_missions:
        for event in mission.events:
            if (event.event_end_date):
                continue
            else:
                break
        else:
            await mission.update(
                is_done=True,
                is_done_cure=True
            )
            if mission.worker:
                await mqtt_client.publish(
                    f"foxlink/users/{mission.worker.current_UUID}/missions/stop-notify",
                    {
                        "mission_id": mission.id,
                        "mission_state": "stop-notify" if not mission.notify_recv_date else "return-home-page",
                        "description": "finish"
                    },
                    qos=2,
                )


# done
@transaction
@show_duration
async def move_idle_workers_to_rescue_device():
    # find idle workers that're not at rescue devices and request them to return.
    workshop_rescue_entity_dict: Dict[
        int, Tuple[FactoryMap, List[Device]]
    ] = {}  # ID, info

    workshops = (
        await FactoryMap.objects
        .fields(['id', 'name', 'related_devices', 'map'])
        .all()
    )

    current_shift = await get_current_shift_type()

    workers = (
        await User.objects
        .select_related(["at_device"])
        .filter(
            shift=current_shift.value,
            level=UserLevel.maintainer.value,
            at_device__is_rescue=False,
            status=WorkerStatusEnum.idle.value
        )
        .all()
    )

    # prefetch required rescue device and workshop entity
    for workshop in workshops:
        workshop_rescue_devices = (
            await Device.objects
            .filter(workshop=workshop.id, is_rescue=True)
            .all()
        )
        workshop_rescue_entity_dict[workshop.id] = (
            workshop, workshop_rescue_devices)

    # request return to specific rescue device of the workshop
    for worker in workers:

        current_date = get_ntz_now()
        rescue_distances = []
        rescue_stations = workshop_rescue_entity_dict[worker.workshop.id][1]
        workshop_entity = workshop_rescue_entity_dict[worker.workshop.id][0]

        if worker.workshop is None:
            continue

        # check if worker took a long time to move to the rescue station.
        if current_date - worker.finish_event_date < timedelta(minutes=WORKER_IDLE_OT_RESCUE_MINUTES):
            continue

        if len(rescue_stations) == 0:
            logger.error(
                f"there's no rescue station in workshop {worker.workshop.id}, you should create a rescue station as soon as possible."
            )
            continue

        try:
            worker_device_idx = find_idx_in_factory_map(
                workshop_entity,
                worker.at_device.id
            )
        except ValueError as e:
            logger.error(
                f"{worker.at_device.id} is not in the map {workshop_entity.name}"
            )
            continue

        # collect the distances of all the rescue stations of the workshop to the user's current device location.
        for r in rescue_stations:
            rescue_idx = find_idx_in_factory_map(
                workshop_entity,
                r.id
            )
            rescue_distances.append(
                {
                    "rescueID": r.id,
                    "distance": workshop_entity.map[worker_device_idx][rescue_idx],
                }
            )

        # select the best rescue station based on the the user's current device location
        selected_rescue_station = dispatch.move_to_rescue(rescue_distances)
        await set_mission_by_rescue_position(worker, selected_rescue_station)


# done
@transaction
@show_duration
async def mission_dispatch():
    """處理任務派工給員工的過程"""

    # 取得所有未指派的任務
    pending_missions = (
        await Mission.objects
        .filter(
            is_done=False,
            worker__isnull=True
        )
        .select_related(
            [
                "device",
                "device__workshop",
                "rejections",
            ]
        )
        .exclude_fields(
            [
                "device__workshop__map",
                "device__workshop__related_devices",
                "device__workshop__image",
            ]
        )
        .all()
    )

    # no pending mission exit
    if len(pending_missions) == 0:
        return

    # prefetch required entities and datas
    workshop_entity_dict: Dict[int, FactoryMap] = {
        workshop.id: workshop
        for workshop in (
            await FactoryMap.objects
            .fields(
                ['id', 'name', 'related_devices', 'map']
            )
            .all()
        )
    }

    current_shift = await get_current_shift_type()

    mission_entity_dict: Dict[int, Mission] = {
        mission.id: mission
        for mission in pending_missions
    }

    whitelist_device_entity_dict: Dict[str, WhitelistDevice] = {
        device.id: device
        for device in (
            await WhitelistDevice.objects
            .select_related("workers")
            .all()
        )
    }

    whitelist_users_entity_dict: Dict[str, WhitelistDevice] = {
        worker.badge: worker
        for worker in (
            await User.objects.select_related("whitelist_devices").all()
        )
        if len(worker.whitelist_devices) > 0
    }

    # 取得優先處理的任務，並按照優先級排序
    dispatch.get_missions(
        [
            {
                "missionID": mission.id,
                "event_count": 0,
                "refuse_count": len(mission.rejections),
                "device": mission.device.device_name,
                "process": mission.device.process,
                "create_date": mission.created_date,
                "category": 0,
            }
            for mission in pending_missions
        ]
    )

    ranked_missions = dispatch.mission_priority()

    for mission_id in ranked_missions:

        mission = mission_entity_dict[mission_id]

        if mission is None:
            continue

        # 取得該裝置隸屬的車間資訊
        workshop = workshop_entity_dict[mission.device.workshop.id]

        distance_matrix: List[List[float]] = workshop.map  # 距離矩陣

        mission_device_idx = find_idx_in_factory_map(
            workshop, mission.device.id)  # 該任務的裝置在矩陣中的位置

        valid_workers: List[User] = None

        # fetch valid workers, also consider whitelist device scenarios.
        if mission.device.id in whitelist_device_entity_dict:
            valid_workers = (
                await User.objects
                .filter(
                    level=UserLevel.maintainer.value,
                    shift=current_shift.value,
                    workshop=mission.device.workshop.id,
                    status=WorkerStatusEnum.idle.value,
                    badge__in=whitelist_users_entity_dict
                )
                .select_related(["device_levels"])
                .filter(
                    device_levels__device=mission.device.id,
                    device_levels__level__gt=0
                )
                .all()
            )
        else:
            valid_workers = (
                await User.objects
                .exclude(
                    badge__in=whitelist_users_entity_dict
                )
                .filter(
                    level=UserLevel.maintainer.value,
                    shift=current_shift.value,
                    workshop=mission.device.workshop.id,
                    status=WorkerStatusEnum.idle.value,
                )
                .select_related(["device_levels"])
                .filter(
                    device_levels__device=mission.device.id,
                    device_levels__level__gt=0
                )
                .all()
            )

        # create worker infos for the mission
        cand_workers = []
        for worker in valid_workers:
            # if worker rejects this mission before.
            if worker in mission.rejections:
                continue

            worker_device_idx = find_idx_in_factory_map(
                workshop, worker.at_device.id
            )

            worker_info = {
                "workerID": worker.badge,
                "distance": distance_matrix[mission_device_idx][worker_device_idx],
                "idle_time": (
                    get_ntz_now() - worker.finish_event_date
                ).total_seconds(),
                "daily_count": worker.shift_accept_count,
                "level": worker.level,
            }

            cand_workers.append(worker_info)

        # without worker candidates, notify the supervisor.
        if len(cand_workers) == 0:

            logger.info(
                f"no worker available to dispatch for mission: (mission_id: {mission_id}, device_id: {mission.device.id})"
            )

            if not mission.is_lonely:
                await mission.update(is_lonely=True)

                await mqtt_client.publish(
                    f"foxlink/{workshop.name}/no-available-worker",
                    MissionDto.from_mission(mission).dict(),
                    qos=2,
                )
        else:
            # select best worker candidate
            dispatch.get_dispatch_info(cand_workers)

            selected_worker = dispatch.worker_dispatch()

            logger.info(
                "dispatching mission {} to worker {}".format(
                    mission.id,
                    selected_worker
                )
            )

            await assign_mission(mission_id, selected_worker)

            await AuditLogHeader.objects.create(
                table_name="missions",
                record_pk=mission_id,
                action=AuditActionEnum.MISSION_ASSIGNED.value,
                user=selected_worker,
            )


######### mission overtime  ########
# half-done
@transaction
@show_duration
async def check_mission_working_duration_overtime():
    """檢查任務持續時間，如果超過一定時間，則發出通知給員工上級但是不取消任務"""
    working_missions = (
        await Mission.objects
        .select_related(['worker'])
        .filter(
            is_done=False,
            is_overtime=False,
            worker__isnull=False,
            repair_beg_date__isnull=False,
            repair_end_date__isnull=True,
        )
        .all()
    )

    thresholds: List[int] = [0]
    for minutes in MISSION_WORK_OT_NOTIFY_PYRAMID_MINUTES:
        thresholds.append(thresholds[-1] + minutes)
    thresholds.pop(0)

    for mission in working_missions:
        for thresh in thresholds[::-1]:
            mission_duration_seconds = mission.mission_duration.total_seconds()

            if mission_duration_seconds >= thresh * 60:

                await mission.update(is_overtime=True)

                if mission.worker.superior is None:
                    break

                await mqtt_client.publish(
                    f"foxlink/users/{mission.worker.superior.badge}/mission-overtime",
                    {
                        "mission_id": mission.id,
                        "mission_name": mission.name,
                        "worker_id": mission.worker.badge,
                        "worker_name": mission.worker.username,
                        "duration": mission_duration_seconds,
                    },
                    qos=2,
                )

                await AuditLogHeader.objects.create(
                    action=AuditActionEnum.MISSION_OVERTIME.value,
                    table_name="missions",
                    description=str(min),
                    record_pk=str(mission.id),
                    user=mission.worker.badge,
                )

                break


# done
@transaction
@show_duration
async def check_mission_assign_duration_overtime():
    """檢查任務assign給worker後到他真正接受任務時間，如果超過一定時間，則發出通知給員工上級並且取消任務"""

    assign_mission_check = (
        await Mission.objects
        .select_related("worker")
        .filter(
            is_done=False,
            worker__isnull=False,
            notify_send_date__isnull=False,
            repair_beg_date__isnull=True
        )
        .all()
    )

    for mission in assign_mission_check:
        if mission.assign_duration.total_seconds() / 60 >= MISSION_ASSIGN_OT_MINUTES:
            # TODO: missing notify supervisor

            await mqtt_client.publish(
                f"foxlink/users/{mission.worker.current_UUID}/missions/stop-notify",
                {
                    "mission_id": mission.id,
                    "mission_state": "stop-notify" if not mission.notify_recv_date else "return-home-page",
                    "description": "over-time-no-action"
                },
                qos=2,
            )

            await reject_mission_by_id(mission.id, mission.worker)

            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_ACCEPT_OVERTIME.value,
                table_name="missions",
                record_pk=str(mission.id),
                user=mission.worker,
            )


######### events completed  ########

async def update_complete_events(event: MissionEvent):
    e = await get_incomplete_event_from_table(
        event.host,
        event.table_name,
        event.event_id
    )
    if e is None:
        return False
    if e.end_time is not None:
        await event.update(event_end_date=e.end_time)
        return True
    return False


@transaction
@show_duration
async def update_complete_events_handler():
    """檢查目前尚未完成的任務，同時向正崴資料庫抓取最新的故障狀況，如完成則更新狀態"""
    incomplete_mission_events = await MissionEvent.objects.filter(
        event_end_date__isnull=True
    ).all()

    await asyncio.gather(*[
        update_complete_events(event)
        for event in incomplete_mission_events
    ])


######### sync event ########
async def sync_events_from_foxlink(host: str, table_name: str, since: str = ""):
    events = await get_recent_events_from_foxlink(host, table_name, since)

    for e in events:
        if await (
            MissionEvent.objects
            .filter(
                event_id=e.id, host=host, table_name=table_name
            )
            .exists()
        ):
            continue

        logger.info(f"recent event from foxlink newly added: {e}")

        # avaliable category range: 1~199, 300~699
        if not (1 <= e.category <= 199 or 300 <= e.category <= 699):
            continue

        device_id = assemble_device_id(e.project, e.line, e.device_name)

        device = await Device.objects.filter(
            id__iexact=device_id
        ).get_or_none()

        # logger.warning(device)

        if device is None:
            continue

        # find if this device is already in a mission
        mission = (
            await Mission.objects
            .filter(
                is_done=False,
                device=device.id,
                repair_end_date__isnull=True,
            )
            .get_or_none()
        )

        if mission is None:
            mission = Mission(
                device=device,
                name=f"{device.id} 故障",
                description="",
            )
            await mission.save()

        await mission.events.add(
            MissionEvent(
                mission=mission.id,
                event_id=e.id,
                host=host,
                table_name=table_name,
                category=e.category,
                message=e.message,
                event_beg_date=e.start_time,
            )
        )


@transaction
@show_duration
async def sync_events_from_foxlink_handler():
    db_table_pairs = await foxlink_dbs.get_all_db_tables()
    proximity_mission = await MissionEvent.objects.order_by(MissionEvent.event_beg_date.desc()).get_or_none()
    since = proximity_mission.event_beg_date if type(
        proximity_mission) != type(None) else ""

    await asyncio.gather(*[
        sync_events_from_foxlink(
            host,
            table,
            since
        )
        for host, tables in db_table_pairs
        for table in tables
    ])


async def get_recent_events_from_foxlink(host: str, table_name: str, since: str = "") -> List[FoxlinkEvent]:
    if (since == ""):
        since = f"CURRENT_TIMESTAMP() - INTERVAL {RECENT_EVENT_PAST_DAYS} DAY"
    else:
        since = f"'{since}'"

    stmt = (
        f"SELECT * FROM `{FOXLINK_EVENT_DB_NAME}`.`{table_name}` WHERE "
        "((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND "
        "End_Time is NULL AND "
        f"Start_Time >= {since} "
        "ORDER BY Start_Time DESC;"
    )
    rows = await foxlink_dbs[host].fetch_all(
        query=stmt
    )
    return [
        FoxlinkEvent(
            id=x[0],
            project=x[9],
            line=x[1],
            device_name=x[2],
            category=x[3],
            start_time=x[4],
            end_time=x[5],
            message=x[6],
            start_file_name=x[7],
            end_file_name=x[8],
        )
        for x in rows
    ]


async def get_incomplete_event_from_table(host: str, table_name: str, id: int) -> Optional[FoxlinkEvent]:
    """
    從正崴資料庫中取得一筆事件資料

    Args:
    - db: 正崴資料庫
    - table_name: 資料表名稱
    - id: 事件資料的 id
    """

    stmt = f"SELECT * FROM `{FOXLINK_EVENT_DB_NAME}`.`{table_name}` WHERE ID = :id;"

    try:
        # type: ignore
        row: list = await foxlink_dbs[host].fetch_one(query=stmt, values={"id": id})

        return FoxlinkEvent(
            id=row[0],
            project=row[9],
            line=row[1],
            device_name=row[2],
            category=row[3],
            start_time=row[4],
            end_time=row[5],
            message=row[6],
            start_file_name=row[7],
            end_file_name=row[8],
        )
    except:
        return None


######### main #########
async def shutdown_callback():
    pass


def shutdown_callback_handler():
    global _terminate
    _terminate = True


async def main(interval: int):
    global _terminate
    _terminate = False

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown_callback_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_callback_handler)

    # connect to service
    await asyncio.gather(*[
        api_db.connect(),
        mqtt_client.connect(),
        foxlink_dbs.connect()
    ])
    logger.info("Connections Created.")

    # main loop
    while not _terminate:
        await asyncio.sleep(interval)
        try:
            logger.warning('[main_routine] Foxlink daemon is running...')
            start = time.perf_counter()
            await update_complete_events_handler()

            await auto_close_missions()

            await mission_shift_routine()

            await move_idle_workers_to_rescue_device()

            await check_mission_working_duration_overtime()

            await check_mission_assign_duration_overtime()

            await sync_events_from_foxlink_handler()

            if not DISABLE_FOXLINK_DISPATCH:
                await mission_dispatch()

            end = time.perf_counter()
            logger.warning("[main_routine] took %.2f seconds", end - start)

        except InterfaceError as e:
            # weird condition. met once, never met twice.
            logger.error(f'API Database connection failure.')
            await api_db.disconnect()
            await api_db.connect()

        except Exception as e:
            logger.error(f'Unknown excpetion in main_routine: {repr(e)}')
            traceback.print_exc()

    await asyncio.sleep(2)
    # shutdown
    logger.info("Termiante Databases/Connections...")
    await asyncio.gather(*[
        api_db.disconnect(),
        mqtt_client.disconnect(),
        foxlink_dbs.disconnect()
    ])
    logger.info("Daemon Terminated.")

parser = argparse.ArgumentParser()
parser.add_argument('-i', dest='interval', type=int, default=10)


def create(**p):
    args = []
    for k, _v in p.items():
        args.append('-' + k)
        args.append(str(_v))
    parser.parse_args(args)
    return [__name__] + args


if __name__ == "__main__":
    args = parser.parse_args()
    asyncio.run(main(interval=args.interval))
