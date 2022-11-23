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

from app.services.mission import assign_mission, get_mission_by_id, is_mission_in_whitelist, reject_mission_by_id
from app.services.user import (
    get_user_shift_type,
    get_user_working_mission,
    is_user_working_on_mission,
    is_worker_in_whitelist,
)

from app.utils.utils import get_shift_type_now
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
async def check_if_mission_finish():
    working_missions = await Mission.objects.select_related(['assignees']).filter(
        device__is_rescue=False, repair_start_date__isnull=False, repair_end_date__isnull=True, is_cancel=False
    ).all()

    working_missions = [
        x for x in working_missions if len(x.assignees) > 0]

    for m in working_missions:
        is_done = await m.is_done_events
        if not is_done:
            return
        for a in m.assignees:
            mqtt_client.publish(
                f"foxlink/users/{a.username}/missions/finish",
                {
                    "mission_id": m.id,
                    "mission_state": "finish"
                },
                qos=2,
            )

        is_worker_actually_repair = False
        now_time = datetime.utcnow()
        for e in m.missionevents:
            if e.event_end_date - timedelta(hours=8) > m.repair_start_date:
                is_worker_actually_repair = True
                break

        async with api_db.transaction():
            if is_worker_actually_repair:
                await m.update(
                    repair_end_date=now_time, is_cancel=False,
                )
            else:
                await m.update(
                    repair_end_date=m.repair_start_date, is_cancel=False,
                )

            # set each assignee's last_event_end_date
            for w in m.assignees:
                await WorkerStatus.objects.filter(worker=w).update(
                    # 改補員工按下任務結束的時間點，而不是 Mission events 中最晚的。
                    status=WorkerStatusEnum.idle.value,
                    last_event_end_date=now_time
                )

            # record this operation
            for w in m.assignees:
                await AuditLogHeader.objects.create(
                    table_name="missions",
                    action=AuditActionEnum.MISSION_FINISHED.value,
                    record_pk=str(m.id),
                    user=w.username,
                )


@show_duration
async def check_alive_worker_routine():
    """檢查員工是否在線，如果沒有在線，則通知上層"""
    alive_worker_status = (
        await WorkerStatus.objects.select_related("worker")
        .filter(
            status__in=[WorkerStatusEnum.working.value,
                        WorkerStatusEnum.idle.value]
        )
        .all()
    )

    async with aiohttp.ClientSession() as session:
        for w in alive_worker_status:
            async with session.get(
                f"http://{MQTT_BROKER}:18083/api/v4/clients/{w.worker.username}",
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
                        if datetime.utcnow() - w.check_alive_time > timedelta(
                            minutes=MAX_NOT_ALIVE_TIME
                        ):

                            # await w.update(status=WorkerStatusEnum.leave.value)
                            
                            # device_level = await UserDeviceLevel.objects.filter(
                            #     user=w.worker.username
                            # ).first()
                            
                            superior =w.worker.superior
                            mqtt_client.publish(
                                f"foxlink/users/{superior.username}/worker-unusual-offline",
                                {
                                    "worker_id": w.worker.username,
                                    "worker_name": w.worker.full_name,
                                },
                                qos=2,
                                retain=True,
                            )
                    else:
                        await w.update(check_alive_time=datetime.utcnow())
                except:
                    continue


@api_db.transaction()
async def overtime_workers_routine():
    """檢查是否有員工超時，如果超時則發送通知"""
    working_missions = await Mission.objects.select_related(['assignees', 'device']).filter(
        repair_end_date__isnull=True, is_cancel=False, device__is_rescue=False,
    ).all()

    working_missions = [x for x in working_missions if len(x.assignees) > 0]

    for m in working_missions:
        should_cancel = False
        for u in m.assignees:
            duty_shift = await get_user_shift_type(u.username)

            if get_shift_type_now() != duty_shift:
                await AuditLogHeader.objects.create(
                    action=AuditActionEnum.MISSION_USER_DUTY_SHIFT.value,
                    table_name="missions",
                    description=f"員工換班，維修時長: {datetime.utcnow() - m.repair_start_date if m.repair_start_date is not None else 0}",
                    user=u.username,
                    record_pk=m.id,
                )
                mqtt_client.publish(
                    f"foxlink/users/{u.username}/missions/finish",
                    {
                        "mission_id": m.id,
                        "mission_state": "ovetime-duty"
                    },
                    qos=2,
                )
                should_cancel = True

        if not should_cancel:
            continue

        await m.update(is_cancel=True, description='換班任務，自動結案')

        copied_mission = await Mission.objects.create(
            name=m.name,
            description=f"換班任務，沿用 Mission ID: {m.id}",
            device=m.device,
            is_emergency=m.is_emergency
        )

        mission_events = await MissionEvent.objects.filter(mission=m.id).all()

        for e in mission_events:
            new_missionevent = MissionEvent(
                event_id=e.event_id,
                table_name=e.table_name,
                category=e.category,
                message=e.message,
                done_verified=e.done_verified,
                event_start_date=e.event_start_date,
                event_end_date=e.event_end_date
            )
            await copied_mission.missionevents.add(new_missionevent)


@show_duration
async def auto_close_missions():
    """自動結案任務，如果任務的故障已排除則自動結案"""
    working_missions = (
        await Mission.objects.select_related(
            ["assignees"]
        ).filter(
            repair_start_date__isnull=True,
            repair_end_date__isnull=True,
            is_cancel=False,
            created_date__lt=datetime.utcnow() - timedelta(minutes=1),
        )
        .all()
    )

    # working_missions = [x for x in working_missions if len(x.assignees) == 0]

    for m in working_missions:
        undone_count = await api_db.fetch_val("SELECT COUNT(*) FROM missionevents m WHERE m.mission = :mission_id AND m.done_verified = 0", {"mission_id": m.id})
        if undone_count == 0:
            await m.update(is_cancel=True, is_autocanceled=True)
        if len(m.assignees) > 0:
            mqtt_client.publish(
                f"foxlink/users/{m.assignees[0].username}/missions/stop-notify",
                {
                    "mission_id": m.id,
                    "mission_state": "finish"
                },
                qos=2,
            )


@show_duration
async def track_worker_status_routine():
    """追蹤員工狀態，視任務狀態而定"""
    async def check_routine(s: WorkerStatus):
        working_mission = await get_user_working_mission(s.worker.username)

        if working_mission is None and s.status == WorkerStatusEnum.idle.value:
            return

        if working_mission is None and s.status != WorkerStatusEnum.idle.value:
            await s.update(status=WorkerStatusEnum.idle.value)
            return

        # 任務是否曾被接受過
        is_accepted = await AuditLogHeader.objects.filter(action=AuditActionEnum.MISSION_ACCEPTED.value, table_name="missions", record_pk=str(working_mission.id), user=s.worker.username).exists()

        # 返回消防站任務提示
        if working_mission.device.is_rescue:
            if not is_accepted:
                await s.update(status=WorkerStatusEnum.notice.value)
            else:
                await s.update(status=WorkerStatusEnum.moving.value)
            return

    worker_status = (
        await WorkerStatus.objects.select_related(["worker"])
        .filter(
            status__in=[
                WorkerStatusEnum.idle.value,
                WorkerStatusEnum.moving.value,
                WorkerStatusEnum.notice.value,
                WorkerStatusEnum.working.value,
            ]
        )
        .all()
    )

    promises = [check_routine(s) for s in worker_status]
    await asyncio.gather(*promises)


@show_duration
async def worker_monitor_routine():
    """監控員工閒置狀態，如果員工閒置在機台超過一定時間，則自動發出返回消防站任務"""
    # when a user import device layout to the system, some devices may have been removed.
    # thus there's a chance that at_device could be null, so we need to address that.
    at_device_null_worker_status = (
        await WorkerStatus.objects.filter(at_device=None)
        .select_related(["worker"])
        .all()
    )

    for ws in at_device_null_worker_status:
        try:
            rescue_station = await Device.objects.filter(
                workshop=ws.worker.location, is_rescue=True
            ).first()
            await ws.update(at_device=rescue_station)
        except Exception:
            continue

    workshop_cache: Dict[int, FactoryMap] = {}  # ID, info
    rescue_cache: Dict[int, List[Device]] = {}  # ID, List[Device]

    all_workshop_infos = await FactoryMap.objects.fields(['id', 'name', 'related_devices', 'map']).all()

    for info in all_workshop_infos:
        workshop_cache[info.id] = info
        all_rescue_devices = await Device.objects.filter(workshop=info.id, is_rescue=True).all()
        rescue_cache[info.id] = all_rescue_devices

    workers = await User.objects.filter(
        level=UserLevel.maintainer.value
    ).all()

    for w in workers:
        async with api_db.transaction():
            worker_status = (
                await WorkerStatus.objects.select_related(["worker", "at_device"])
                .filter(worker=w)
                .get_or_none()
            )

            if w.location is None:
                continue

            rescue_stations = rescue_cache[w.location.id]

            if len(rescue_stations) == 0:
                logger.error(
                    f"there's no rescue station in workshop {w.location.id}")
                logger.error(
                    f"you should create a rescue station as soon as possible")
                return

            if worker_status is None:
                await WorkerStatus.objects.create(
                    worker=w,
                    status=WorkerStatusEnum.leave.value,
                    at_device=rescue_stations[0],
                    last_event_end_date=datetime.utcnow(),
                )
                continue

            if worker_status.status != WorkerStatusEnum.idle.value:
                continue

            if get_shift_type_now() != (await get_user_shift_type(w.username)):
                continue

            if worker_status.at_device.is_rescue == True:
                continue

            if datetime.utcnow() - worker_status.last_event_end_date < timedelta(
                minutes=MOVE_TO_RESCUE_STATION_TIME
            ):
                continue

            if await is_user_working_on_mission(w.username):
                continue

            factory_map = workshop_cache[w.location.id]
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
                device=to_rescue_station,
                repair_start_date=datetime.utcnow(),
                description=f"請前往救援站 {to_rescue_station}",
            )
            await mission.assignees.add(w)

            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_ASSIGNED.value,
                user=w.username,
                table_name="missions",
                record_pk=str(mission.id),
                description="前往消防站",
            )

            mqtt_client.publish(
                f"foxlink/users/{w.username}/move-rescue-station",
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


@show_duration
async def check_mission_accept_duration_routine():
    """檢查任務assign給worker後到他真正接受任務時間，如果超過一定時間，則發出通知給員工上級"""
    assign_mission_check = await AuditLogHeader.objects.filter(
        action=AuditActionEnum.MISSION_ASSIGNED.value).all()

    for m in assign_mission_check:
        assign_mission = (
            await Mission.objects.select_related("assignees")
            .filter(
                id=m.record_pk,
                repair_start_date__isnull=True,
                is_cancel=False,
            ).get_or_none())
        if assign_mission is None:
            continue
        if len(assign_mission.assignees) == 0:
            continue
        if assign_mission.assignees[0].username != m.user.username:
            continue
        if m.accept_duration is None:
            continue
        if m.accept_duration.total_seconds() >= CHECK_MISSION_ASSIGN_DURATION:
            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_ACCEPTED_OVERTIME.value,
                table_name="missions",
                record_pk=str(m.record_pk),
                user=m.user,
            )
            await reject_mission_by_id(m.record_pk,  m.user)


@show_duration
async def check_mission_duration_routine():
    """檢查任務持續時間，如果超過一定時間，則發出通知給員工上級"""
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
        if m.repair_duration is None:
            continue

        for idx, min in enumerate(standardize_thresholds):
            if m.repair_duration.total_seconds() >= min * 60:
                is_sent = await AuditLogHeader.objects.filter(
                    action=AuditActionEnum.MISSION_OVERTIME.value,
                    table_name="missions",
                    description=str(min),
                    record_pk=str(m.id),
                ).exists()

                if is_sent:
                    continue

                superior: Optional[User] = m.worker.superior
                    
                if superior is None:
                    break

                mqtt_client.publish(
                    f"foxlink/users/{superior.username}/mission-overtime",
                    {
                        "mission_id": m.id,
                        "mission_name": m.name,
                        "worker_id": m.assignees[0].username,
                        "worker_name": m.assignees[0].full_name,
                        "duration": m.mission_duration.total_seconds(),
                    },
                    qos=2,
                )

                await AuditLogHeader.objects.create(
                    action=AuditActionEnum.MISSION_OVERTIME.value,
                    table_name="missions",
                    description=str(min),
                    record_pk=str(m.id),
                    user=m.assignees[0].username,
                )



@show_duration
async def dispatch_routine():
    """處理任務派工給員工的過程"""

    # 取得所有未完成的任務
    avaliable_missions = (
        await Mission.objects.select_related(["device", "assignees"])
        .filter(is_cancel=False, repair_end_date__isnull=True)
        .all()
    )

    # 過濾員工數為零的任務
    avaliable_missions = [
        x for x in avaliable_missions if len(x.assignees) == 0]

    if len(avaliable_missions) == 0:
        return
    m_list = []

    for m in avaliable_missions:
        reject_count = await AuditLogHeader.objects.filter(
            action=AuditActionEnum.MISSION_REJECTED.value, record_pk=m.id
        ).count()

        item = {
            "missionID": m.id,
            "event_count": 0,
            "refuse_count": reject_count,
            "device": m.device.device_name,
            "process": m.device.process,
            "create_date": m.created_date,
            "category": 0,
        }

        m_list.append(item)

    workshop_cache: Dict[int, FactoryMap] = {}  # ID, info
    all_workshop_infos = await FactoryMap.objects.fields(['id', 'name', 'related_devices', 'map']).all()

    for info in all_workshop_infos:
        workshop_cache[info.id] = info

    # 取得優先處理的任務，並按照優先級排序
    dispatch.get_missions(m_list)
    mission_rank_list = dispatch.mission_priority()

    for idx, mission_id in enumerate(mission_rank_list):
        mission_1st = (await Mission.objects.select_related(
            ["assignees", "device", "device__workshop"]
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
        can_dispatch_workers = await api_db.fetch_all(
            """
            SELECT udl.*, u.full_name, u.level as userlevel FROM userdevicelevels udl
            INNER JOIN users u ON u.username = udl.`user`
            WHERE udl.device = :device_id AND udl.shift=:shift AND udl.level > 0 AND u.location = :location
            """,
            {'device_id': mission_1st.device.id, 'shift': get_shift_type_now(
            ).value, 'location': mission_1st.device.workshop.id}
        )

        # 檢查機台是否被列入白名單，並抓取可能的白名單員工列表
        is_in_whitelist = await is_mission_in_whitelist(mission_1st.id)
        whitelist_workers = await get_workers_from_whitelist_devices(mission_1st.device.id)

        remove_indice = []
        for w in can_dispatch_workers:
            # 如果該機台不列入白名單，但是員工是白名單員工，則移除
            if not is_in_whitelist and await is_worker_in_whitelist(w['user']):
                remove_indice.append(w['user'])
            # 如果該機台是列入白名單，但是員工不是白名單員工，則移除
            if is_in_whitelist and w['user'] not in whitelist_workers:
                remove_indice.append(w['user'])

        # 取得該裝置隸屬的車間資訊
        factory_map = workshop_cache[mission_1st.device.workshop.id]
        distance_matrix: List[List[float]] = factory_map.map  # 距離矩陣
        mission_device_idx = find_idx_in_factory_map(
            factory_map, mission_1st.device.id)  # 該任務的裝置在矩陣中的位置
        # 移除不符合條件的員工
        can_dispatch_workers = [
            x for x in can_dispatch_workers if x['user'] not in remove_indice]

        # 如果沒有可派工的員工，則通知管理層並跳過
        if len(can_dispatch_workers) == 0:
            logger.warning(
                f"No workers available to dispatch for mission {mission_1st.id}"
            )

            if not await AuditLogHeader.objects.filter(action=AuditActionEnum.NOTIFY_MISSION_NO_WORKER.value, record_pk=mission_1st.id).exists():
                await AuditLogHeader.objects.create(action=AuditActionEnum.NOTIFY_MISSION_NO_WORKER.value, table_name="missions", record_pk=mission_1st.id)
                mqtt_client.publish(
                    f"foxlink/{factory_map.name}/no-available-worker",
                    MissionDto.from_mission(mission_1st).dict(),
                    qos=2,
                )
            continue

        w_list = []
        for w in can_dispatch_workers:
            if w['userlevel'] != UserLevel.maintainer.value:
                continue

            is_idle = await WorkerStatus.objects.filter(
                worker=w['user'], status=WorkerStatusEnum.idle.value
            ).exists()

            # 如果員工非閒置狀態則略過
            if not is_idle:
                continue

            # if worker has already working on other mission, skip
            if (await is_user_working_on_mission(w['user'])) == True:
                continue

            # if worker rejects this mission once.
            if await AuditLogHeader.objects.filter(
                action=AuditActionEnum.MISSION_REJECTED.value,
                user=w['user'],
                record_pk=mission_1st.id,
            ).exists():
                continue

            worker_status = await WorkerStatus.objects.filter(worker=w['user']).get()

            daily_count = await AuditLogHeader.objects.filter(
                action=AuditActionEnum.MISSION_ASSIGNED.value,
                user=w['user'],
                created_date__gte=(datetime.utcnow() - timedelta(hours=12)),
            ).count()

            worker_device_idx = find_idx_in_factory_map(
                factory_map, worker_status.at_device.id
            )

            item = {
                "workerID": w['user'],
                "distance": distance_matrix[mission_device_idx][worker_device_idx],
                "idle_time": (
                    datetime.utcnow() - worker_status.last_event_end_date
                ).total_seconds(),
                "daily_count": daily_count,
                "level": w['level'],
            }
            w_list.append(item)

        if len(w_list) == 0:
            logger.warning(
                f"no worker available to dispatch for mission: (mission_id: {mission_id}, device_id: {mission_1st.device.id})"
            )

            if not await AuditLogHeader.objects.filter(action=AuditActionEnum.NOTIFY_MISSION_NO_WORKER.value, record_pk=mission_1st.id).exists():
                await AuditLogHeader.objects.create(action=AuditActionEnum.NOTIFY_MISSION_NO_WORKER.value, table_name="missions", record_pk=mission_1st.id)
                mqtt_client.publish(
                    f"foxlink/{factory_map.name}/no-available-worker",
                    MissionDto.from_mission(mission_1st).dict(),
                    qos=2,
                )
            continue

        dispatch.get_dispatch_info(w_list)
        worker_1st = dispatch.worker_dispatch()

        async with api_db.transaction():
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
                        mission_1st.id, worker_1st)
                )
            except Exception as e:
                logger.error(
                    f"cannot assign to worker {worker_1st}\nReason: {repr(e)}")


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
        logger.info(e)
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

        device_id = generate_device_id(e)

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

        await mission.missionevents.add(
            MissionEvent(
                mission=mission.id,
                event_id=e.id,
                host=host,
                table_name=table_name,
                category=e.category,
                message=e.message,
                event_start_date=e.start_time,
            )
        )

@show_duration
async def sync_events_from_foxlink_handler():
        db_table_pairs = await foxlink_dbs.get_all_db_tables()
        proximity_mission =  await MissionEvent.objects.order_by(MissionEvent.event_start_date.desc()).get_or_none()
        since = proximity_mission.event_start_date if type(proximity_mission) != type(None) else ""
        
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
            await auto_close_missions()
            await worker_monitor_routine()
            await overtime_workers_routine()
            await track_worker_status_routine()
            await check_mission_duration_routine()
            # await check_if_mission_cancel_or_close()
            # await check_mission_accept_duration_routine()
            # await check_alive_worker_routine()
            # await check_if_mission_finish()

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

    
