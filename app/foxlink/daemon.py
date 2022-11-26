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
    is_mission_in_whitelist,
    reject_mission_by_id
)
from app.services.user import (
    get_user_shift_type,
    get_user_working_mission,
    is_worker_in_whitelist,
)

from app.utils.utils import get_current_shift_type
from app.mqtt import mqtt_client
from app.env import (
    CHECK_MISSION_ASSIGN_DURATION,
    DISABLE_FOXLINK_DISPATCH,
    FOXLINK_EVENT_DB_HOSTS,
    FOXLINK_EVENT_DB_PWD,
    FOXLINK_EVENT_DB_USER,
    FOXLINK_EVENT_DB_NAME,
    MQTT_BROKER,
    MAX_NOT_ALIVE_TIME,
    EMQX_USERNAME,
    EMQX_PASSWORD,
    MOVE_TO_RESCUE_STATION_TIME,
    MQTT_PORT,
    OVERTIME_MISSION_NOTIFY_PERIOD,
    RECENT_EVENT_PAST_DAYS,
)
from app.core.database import (
    get_ntz_now,
    FactoryMap,
    Mission,
    MissionEvent,
    User,
    AuditLogHeader,
    AuditActionEnum,
    WorkerStatusEnum,
    UserLevel,
    Device,
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

logger.setLevel(logging.WARNING)

dispatch = Foxlink_dispatch()

_terminate = None

def show_duration(func):
    async def wrapper():
        start = time.perf_counter()
        await func()
        end = time.perf_counter()
        logger.warning(f'[{func.__name__}] took {end - start:.2f} seconds.')
    return wrapper


def find_idx_in_factory_map(factory_map: FactoryMap, device_id: str) -> int:
    try:
        return factory_map.related_devices.index(device_id)
    except ValueError as e:
        msg = f"{device_id} device is not in the map {factory_map.name}"
        raise ValueError(msg)



@show_duration
async def check_alive_worker_routine():
    """檢查員工是否在線，如果沒有在線，則通知上層"""
    alive_workers = (
        await User.objects
        .filter(
            status__in=[WorkerStatusEnum.working.value,WorkerStatusEnum.idle.value]
        )
        .all()
    )

    async with aiohttp.ClientSession() as session:
        for worker in alive_workers:
            async with session.get(
                f"http://{MQTT_BROKER}:18083/api/v4/clients/{worker.badge}",
                auth=aiohttp.BasicAuth(
                    login=EMQX_USERNAME, password=EMQX_PASSWORD),
            ) as resp:
                if resp.status != 200:
                    logger.warn("Error getting mqtt client status")
                    continue

                try:
                    content = await resp.json()
                    # if the woeker is still not connected to the broker
                    if len(content["data"]) == 0:
                        if get_ntz_now() - worker.check_alive_time > timedelta(
                            minutes=MAX_NOT_ALIVE_TIME
                        ):

                            # await w.update(status=WorkerStatusEnum.leave.value)
                            
                            # device_level = await UserDeviceLevel.objects.filter(
                            #     user=w.worker.badge
                            # ).first()
                            
                            superior = w.worker.superior
                            mqtt_client.publish(
                                f"foxlink/users/{superior.badge}/worker-unusual-offline",
                                {
                                    "worker_id": worker.badge,
                                    "worker_name": worker.username,
                                },
                                qos=2,
                                retain=True,
                            )
                    else:
                        await worker.update(check_alive_time=get_ntz_now())
                except:
                    continue


@api_db.transaction()
async def overtime_workers_routine():
    """檢查是否有員工超時，如果超時則發送通知"""
    working_missions = (await Mission.objects
        .select_related(
            ["worker","events","device"]
        )
        .filter(
            is_cancel=False,
            repair_end_date__isnull=True,
            device__is_rescue=False,
            worker__isnull=False
        )
        .all()
    )


    for mission in working_missions:
        should_cancel = False
        duty_shift = await get_user_shift_type(mission.worker.badge)

        if (await get_current_shift_type()) != duty_shift:
            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_USER_DUTY_SHIFT.value,
                table_name="missions",
                description=f"員工換班，維修時長: {get_ntz_now() - mission.repair_beg_date if mission.repair_beg_date is not None else 0}",
                user=mission.worker.badge,
                record_pk=mission.id,
            )
            mqtt_client.publish(
                f"foxlink/users/{mission.worker.badge}/missions/finish",
                {
                    "mission_id": mission.id,
                    "mission_state": "ovetime-duty"
                },
                qos=2,
            )
            should_cancel = True

        if not should_cancel:
            continue

        await mission.update(is_cancel=True, description='換班任務，自動結案')

        copied_mission = await Mission.objects.create(
            name=mission.name,
            description=f"換班任務，沿用 Mission ID: {mission.id}",
            device=mission.device,
            is_emergency=mission.is_emergency
        )

        mission_events = await MissionEvent.objects.filter(mission=mission.id).all()

        for e in mission_events:
            new_missionevent = MissionEvent(
                event_id=e.event_id,
                table_name=e.table_name,
                category=e.category,
                message=e.message,
                done_verified=e.done_verified,
                event_beg_date=e.event_beg_date,
                event_end_date=e.event_end_date
            )
            await copied_mission.events.add(new_missionevent)


@show_duration
async def auto_close_missions():
    """自動結案任務，如果任務的故障已排除則自動結案"""
    non_accepted_missions = (
        await Mission.objects.filter(
            repair_beg_date__isnull=True,
            repair_end_date__isnull=True,
            is_cancel=False
        )
        .select_related(["events","worker"])
        .filter(
            events__done_verified=False
        )
        .all()
    )


    for mission in non_accepted_missions:
        if len(mission.events) == 0:
            await mission.update(
                is_cancel=True,
                is_autocanceled=True
            )
        if mission.worker:
            mqtt_client.publish(
                f"foxlink/users/{mission.worker.badge}/missions/stop-notify",
                {
                    "mission_id": mission.id,
                    "mission_state": "finish"
                },
                qos=2,
            )


@show_duration
async def worker_monitor_routine():
    """監控員工閒置狀態，如果員工閒置在機台超過一定時間，則自動發出返回消防站任務"""
    # when a user import device layout to the system, some devices may have been removed.
    # thus there's a chance that at_device could be null, so we need to address that.
    workshop_cache: Dict[int, FactoryMap] = {}  # ID, info
    rescue_cache: Dict[int, List[Device]] = {}  # ID, List[Device]

    transaction = await api_db.transaction()

    try:
        all_workshop_infos = await FactoryMap.objects.fields(['id', 'name', 'related_devices', 'map']).all()

        for info in all_workshop_infos:
            workshop_cache[info.id] = info
            all_rescue_devices = await Device.objects.filter(workshop=info.id, is_rescue=True).all()
            rescue_cache[info.id] = all_rescue_devices

        workers =(
                await User.objects
                .filter(
                    shift= (await get_current_shift_type()).value,
                    level=UserLevel.maintainer.value,
                    at_device__is_rescue=False,
                    status= WorkerStatusEnum.idle
                )
                .all()
        )

        for worker in workers:
            
            if worker.workshop is None:
                    continue
        
            rescue_stations = rescue_cache[worker.workshop.id]

            if len(rescue_stations) == 0:
                logger.error(
                    f"there's no rescue station in workshop {worker.workshop.id}"
                )
                logger.error(
                    f"you should create a rescue station as soon as possible"
                )
                continue

            if get_ntz_now() - worker.finish_event_date < timedelta(
                minutes=MOVE_TO_RESCUE_STATION_TIME
            ):
                continue

            factory_map = workshop_cache[worker.workshop.id]
            rescue_distances = []

            try:
                worker_device_idx = find_idx_in_factory_map(
                    factory_map, worker.at_device.id
                )
            except ValueError as e:
                logger.error(
                    f"{worker.at_device.id} is not in the map {factory_map.name}"
                )
                continue

            
            # fetch all the rescue stations and the 
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
                device=to_rescue_station,
                repair_beg_date=get_ntz_now(),
                description=f"請前往救援站 {to_rescue_station}",
                worker=worker
            )

            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_ASSIGNED.value,
                user=worker.badge,
                table_name="missions",
                record_pk=str(mission.id),
                description="前往消防站",
            )

            mqtt_client.publish(
                f"foxlink/users/{worker.badge}/move-rescue-station",
                {
                    "type": "rescue",
                    "mission_id": mission.id,
                    "name": mission.name,
                    "description": mission.description,
                    "rescue_station": to_rescue_station,
                },
                qos=2,
                retain=True,
            )

    except Exception as e:
        print(e)
        logger.error(e)
        await transaction.rollback()
    else:
        await transaction.commit()


@show_duration
async def check_mission_duration_routine():
    """檢查任務持續時間，如果超過一定時間，則發出通知給員工上級"""
    working_missions = (
        await Mission.objects
        .select_related(['worker'])
        .filter(
            # repair_beg_date__isnull=False,
            repair_end_date__isnull=True,
            is_overtime=False,
            is_cancel=False,
            worker__isnull=False
        )
        .all()
    )

    standardize_thresholds: List[int] = []
    total_mins = 0
    for t in OVERTIME_MISSION_NOTIFY_PERIOD:
        total_mins += t
        standardize_thresholds += [total_mins]


    for mission in working_missions:
        for idx, min in enumerate(standardize_thresholds):
            if mission.repair_duration.total_seconds() >= min * 60:

                await mission.update(is_overtime=True)

                superior: Optional[User] = mission.worker.superior
                    
                if superior is None:
                    break

                mqtt_client.publish(
                    f"foxlink/users/{superior.badge}/mission-overtime",
                    {
                        "mission_id": mission.id,
                        "mission_name": mission.name,
                        "worker_id": mission.worker.badge,
                        "worker_name": mission.worker.username,
                        "duration": mission.mission_duration.total_seconds(),
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


@show_duration
async def dispatch_routine():
    """處理任務派工給員工的過程"""

    # 取得所有未完成的任務
    pending_missions = (
        await Mission.objects
        .filter(
            is_cancel=False,
            repair_end_date__isnull=True,
            worker__isnull=True
        )
        .all()
    )


    if len(pending_missions) == 0:
        return

    mission_item_list = []

    for mission in pending_missions:
        item = {
            "missionID": mission.id,
            "event_count": 0,
            "refuse_count": len(mission.rejections),
            "device": mission.device.device_name,
            "process": mission.device.process,
            "create_date": mission.created_date,
            "category": 0,
        }

        mission_item_list.append(item)

    workshop_cache: Dict[int, FactoryMap] = {}  # ID, info
    all_workshop_infos = await FactoryMap.objects.fields(['id', 'name', 'related_devices', 'map']).all()

    for info in all_workshop_infos:
        workshop_cache[info.id] = info

    # 取得優先處理的任務，並按照優先級排序
    dispatch.get_missions(mission_item_list)
    mission_rank_list = dispatch.mission_priority()

    for idx, mission_id in enumerate(mission_rank_list):
        mission_1st = (await Mission.objects
            .select_related(
                ["device__workshop"]
            )
            .exclude_fields(
                [
                    "device__workshop__map",
                    "device__workshop__related_devices",
                    "device__workshop__image",
                ]
            )
            .filter(id=mission_id)
            .get_or_none()
        )

        if mission_1st is None:
            continue

        # 抓取可維修此機台的員工列表
        can_dispatch_workers = (await User.objects
            .exclude(
                level=UserLevel.admin.value
            )
            .filter(
                shift = (await get_current_shift_type()).value,
                workshop = mission_1st.device.workshop.id,
                status = WorkerStatusEnum.idle.value
            )
            .select_related(["device_levels"])
            .filter(
                device_levels__device = mission_1st.device.id,   
                
            )
            .all()
        )
        
        # 檢查機台是否被列入白名單，並抓取可能的白名單員工列表
        is_in_whitelist = await is_mission_in_whitelist(mission_1st.id)
        whitelist_workers = await get_workers_from_whitelist_devices(mission_1st.device.id)

        remove_indice = []
        for worker in can_dispatch_workers:
            # 如果該機台不列入白名單，但是員工是白名單員工，則移除
            if not is_in_whitelist and await is_worker_in_whitelist(worker.badge):
                remove_indice.append(worker.badge)
            # 如果該機台是列入白名單，但是員工不是白名單員工，則移除
            if is_in_whitelist and worker.badge not in whitelist_workers:
                remove_indice.append(worker.badge)

        # 取得該裝置隸屬的車間資訊
        factory_map = workshop_cache[mission_1st.device.workshop.id]
        distance_matrix: List[List[float]] = factory_map.map  # 距離矩陣
        mission_device_idx = find_idx_in_factory_map(factory_map, mission_1st.device.id) # 該任務的裝置在矩陣中的位置
        
        # 移除不符合條件的員工
        can_dispatch_workers = [
            x for x in can_dispatch_workers if x.badge not in remove_indice
        ]
        worker_list = []

        for worker in can_dispatch_workers:

            if worker.level != UserLevel.maintainer.value:
                continue

            # if worker rejects this mission once.
            if worker in mission_1st.rejections:
                continue
            

            worker_device_idx = find_idx_in_factory_map(
                factory_map, worker.at_device.id
            )

            item = {
                "workerID": worker.badge,
                "distance": distance_matrix[mission_device_idx][worker_device_idx],
                "idle_time": (
                    get_ntz_now() - worker.finish_event_date
                ).total_seconds(),
                "daily_count": worker.dispatch_count,
                "level": worker.level,
            }

            worker_list.append(item)
        

        if len(worker_list) == 0:
            logger.info(
                f"no worker available to dispatch for mission: (mission_id: {mission_id}, device_id: {mission_1st.device.id})"
            )

            if not mission_1st.is_lonely:

                await mission_1st.update(is_lonely=True)

                mqtt_client.publish(
                    f"foxlink/{factory_map.name}/no-available-worker",
                    MissionDto.from_mission(mission_1st).dict(),
                    qos=2,
                )
            continue

        dispatch.get_dispatch_info(worker_list)
        worker_1st = dispatch.worker_dispatch()

        transaction = await api_db.transaction()

        try:
            await assign_mission(mission_id, worker_1st)
            await AuditLogHeader.objects.create(
                table_name="missions",
                record_pk=mission_id,
                action=AuditActionEnum.MISSION_ASSIGNED.value,
                user=worker_1st,
            )
            logger.info(
                "dispatching mission {} to worker {}".format(
                    mission_1st.id, worker_1st
                )
            )
        except Exception as e:
            traceback.print_exc()
            logger.error(
                f"cannot assign to worker {worker_1st}\nReason: {repr(e)}"
            )
            await transaction.rollback()
        else:
            await transaction.commit()


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
        await event.update(event_end_date=e.end_time, done_verified=True)
        return True
    return False

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

async def sync_events_from_foxlink(host: str, table_name: str, since:str = ""):
    events = await get_recent_events_from_foxlink(host, table_name, since)

    for e in events:
        logger.info("recent event from foxlink: {e}")

        if await MissionEvent.objects.filter(
            event_id=e.id, host=host, table_name=table_name
        ).exists():
            continue

        # avaliable category range: 1~199, 300~699
        if not (
            (e.category >= 1 and e.category <= 199)
            or (e.category >= 300 and e.category <= 699)
        ):
            continue

        device_id = assemble_device_id(e.project,e.line,e.device_name)

        # if this device's priority is not existed in `CategoryPRI` table, which means it's not an out-of-order event.
        # Thus, we should skip it.
        # priority = await CategoryPRI.objects.filter(
        #     devices__id__iexact=device_id, category=e.category
        # ).get_or_none()

        # if priority is None:
        #     continue
        # logger.warning(device_id)

        device = await Device.objects.filter(
            id__iexact=device_id
        ).get_or_none()

        # logger.warning(device)

        if device is None:
            continue

        # find if this device is already in a mission
        mission = await Mission.objects.filter(
            device=device.id, repair_end_date__isnull=True, is_cancel=False
        ).get_or_none()

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

@show_duration
async def sync_events_from_foxlink_handler():
        db_table_pairs = await foxlink_dbs.get_all_db_tables()
        proximity_mission =  await MissionEvent.objects.order_by(MissionEvent.event_beg_date.desc()).get_or_none()
        since = proximity_mission.event_beg_date if type(proximity_mission) != type(None) else ""
        
        await asyncio.gather(*[
            sync_events_from_foxlink(host,table,since) 
            for host,tables in db_table_pairs for table in tables
        ])

async def get_recent_events_from_foxlink(host: str, table_name: str, since: str = "") -> List[FoxlinkEvent]:
    if(since == ""):
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

async def shutdown_callback_handler():
    global _terminate
    _terminate=True

async def main(interval:int):
    global _terminate
    _terminate = False

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT,functools.partial(asyncio.create_task,shutdown_callback_handler()))
    loop.add_signal_handler(signal.SIGTERM,functools.partial(asyncio.create_task,shutdown_callback_handler()))

    # connect to service
    await asyncio.gather(*[
        api_db.connect(),
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, str(uuid.uuid4())),
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
            await sync_events_from_foxlink_handler()

            # await auto_close_missions()
            # await worker_monitor_routine()
            # await overtime_workers_routine()
            # await check_mission_duration_routine()

            if not DISABLE_FOXLINK_DISPATCH:
                await dispatch_routine()

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
        

    # shutdown
    logger.info("Termiante Databases/Connections...")
    await asyncio.gather(*[
        api_db.disconnect(),
        mqtt_client.disconnect(),
        foxlink_dbs.disconnect()
    ])
    logger.info("Daemon Terminated.")

parser = argparse.ArgumentParser()
parser.add_argument('-i',dest='interval',type=int,default=10)

def create(**p):
    args = []
    for k,_v in p.items():
        args.append('-'+k)
        args.append(str(_v))
    parser.parse_args(args)
    return [__name__] + args

if __name__=="__main__":    
    args = parser.parse_args()
    asyncio.run(main(interval=args.interval))

    
