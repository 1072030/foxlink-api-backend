import logging, asyncio, aiohttp
import uuid
import signal
import time
from databases import Database
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.models.schema import MissionDto
from app.services.device import get_workers_from_whitelist_devices
from app.utils.timer import Ticker
from foxlink_dispatch.dispatch import Foxlink_dispatch
from app.services.mission import assign_mission, get_mission_by_id, is_mission_in_whitelist
from app.services.user import (
    get_user_shift_type,
    get_user_working_mission,
    is_user_working_on_mission,
    is_worker_in_whitelist,
)
from app.my_log_conf import LOGGER_NAME
from app.utils.utils import get_shift_type_now
from app.mqtt.main import connect_mqtt, publish, disconnect_mqtt
from app.env import (
    DISABLE_FOXLINK_DISPATCH,
    FOXLINK_DB_HOSTS,
    FOXLINK_DB_PWD,
    FOXLINK_DB_USER,
    MQTT_BROKER,
    MAX_NOT_ALIVE_TIME,
    EMQX_USERNAME,
    EMQX_PASSWORD,
    MOVE_TO_RESCUE_STATION_TIME,
    MQTT_PORT,
    OVERTIME_MISSION_NOTIFY_PERIOD,
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


class FoxlinkEvent(BaseModel):
    id: int
    project: str
    line: str
    device_name: str
    category: int
    start_time: datetime
    end_time: Optional[datetime]
    message: Optional[str]
    start_file_name: Optional[str]
    end_file_name: Optional[str]

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


@database.transaction()
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
                publish(
                    f"foxlink/users/{u.username}/overtime-duty",
                    {"message": "因為您超時工作，所以您目前的任務已被移除。"},
                    qos=1,
                )
                should_cancel = True

        if not should_cancel:
            continue

        await m.update(is_cancel=True, description='換班任務，自動結案')

        copied_mission = await Mission.objects.create(
            name=m.name,
            description=f"換班任務，沿用 Mission ID: {m.id}",
            device=m.device,
            required_expertises=[],
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
    """自動結案任務，如果任務的故障已排除但員工未被指派，則自動結案"""
    working_missions = (
        await Mission.objects.select_related(["assignees"])
        .filter(
            repair_start_date__isnull=True,
            repair_end_date__isnull=True,
            is_cancel=False,
            created_date__lt=datetime.utcnow() - timedelta(minutes=1),
        )
        .all()
    )

    # working_missions = [x for x in working_missions if len(x.assignees) == 0]

    for m in working_missions:
        undone_count = await database.fetch_val("SELECT COUNT(*) FROM missionevents m WHERE m.mission = :mission_id AND m.done_verified = 0", {"mission_id": m.id})
        if undone_count == 0:
            await m.update(is_cancel=True, is_autocanceled=True)

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
        is_accepted = await AuditLogHeader.objects.filter(action=AuditActionEnum.MISSION_ACCEPTED.value,table_name="missions",record_pk=str(working_mission.id),user=s.worker.username).exists()

        # 返回消防站任務提示
        if working_mission.device.is_rescue:
            if not is_accepted:
                await s.update(status=WorkerStatusEnum.notice.value)
            else:
                await s.update(status=WorkerStatusEnum.moving.value)
            return

        if working_mission.repair_start_date is not None and working_mission.repair_end_date is None:
            await s.update(status=WorkerStatusEnum.working.value)
            return

        if is_accepted:
            await s.update(status=WorkerStatusEnum.moving.value)
        else:
            await s.update(status=WorkerStatusEnum.notice.value)


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

    workshop_cache: Dict[int, FactoryMap] = {} # ID, info
    rescue_cache: Dict[int, List[Device]] = {} # ID, List[Device]

    all_workshop_infos = await FactoryMap.objects.fields(['id', 'name', 'related_devices', 'map']).all()

    for info in all_workshop_infos:
        workshop_cache[info.id] = info
        all_rescue_devices = await Device.objects.filter(workshop=info.id, is_rescue=True).all()
        rescue_cache[info.id] = all_rescue_devices
    

    workers = await User.objects.filter(
        level=UserLevel.maintainer.value, is_admin=False
    ).all()

    for w in workers:
        worker_status = (
            await WorkerStatus.objects.select_related(["worker", "at_device"])
            .filter(worker=w)
            .get_or_none()
        )

        if w.location is None:
            continue

        rescue_stations = rescue_cache[w.location.id]

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

            # await WorkerStatus.objects.filter(worker=w.username).update(
            #     status=WorkerStatusEnum.working.value
            # )

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

            await AuditLogHeader.objects.create(
                action=AuditActionEnum.MISSION_ASSIGNED.value,
                user=w.username,
                table_name="missions",
                record_pk=str(mission.id),
                description="前往消防站",
            )

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
                        "duration": m.mission_duration.total_seconds(),
                    },
                    qos=1,
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
    avaliable_missions = [x for x in avaliable_missions if len(x.assignees) == 0]

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

    workshop_cache: Dict[int, FactoryMap] = {} # ID, info
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
        can_dispatch_workers = await database.fetch_all(
        """
            SELECT udl.*, u.full_name  FROM userdevicelevels udl
            INNER JOIN users u ON u.username = udl.`user`
            WHERE udl.device = :device_id AND udl.shift=:shift AND udl.level > 0 AND u.location = :location
        """,
        {'device_id': mission_1st.device.id, 'shift': get_shift_type_now().value, 'location': mission_1st.device.workshop.id}
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
        distance_matrix: List[List[float]] = factory_map.map # 距離矩陣
        mission_device_idx = find_idx_in_factory_map(factory_map, mission_1st.device.id) # 該任務的裝置在矩陣中的位置
        # 移除不符合條件的員工
        can_dispatch_workers = [x for x in can_dispatch_workers if x['user'] not in remove_indice]

        # 如果沒有可派工的員工，則通知管理層並跳過
        if len(can_dispatch_workers) == 0:
            logger.warning(
                f"No workers available to dispatch for mission {mission_1st.id}"
            )

            if not await AuditLogHeader.objects.filter(action=AuditActionEnum.NOTIFY_MISSION_NO_WORKER.value, record_pk=mission_1st.id).exists():
                await AuditLogHeader.objects.create(action=AuditActionEnum.NOTIFY_MISSION_NO_WORKER.value, table_name="missions", record_pk=mission_1st.id)
                publish(
                    f"foxlink/{factory_map.name}/no-available-worker",
                    MissionDto.from_mission(mission_1st).dict(),
                    qos=1,
                )
            continue


        w_list = []
        for w in can_dispatch_workers:
            if w['level'] != UserLevel.maintainer.value:
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
                publish(
                    f"foxlink/{factory_map.name}/no-available-worker",
                    MissionDto.from_mission(mission_1st).dict(),
                    qos=1,
                )
            continue

        dispatch.get_dispatch_info(w_list)
        worker_1st = dispatch.worker_dispatch()

        async with database.transaction():
            try:
                await assign_mission(mission_id, worker_1st)
                await AuditLogHeader.objects.create(
                    table_name="missions",
                    record_pk=mission_id,
                    action=AuditActionEnum.MISSION_ASSIGNED.value,
                    user=worker_1st,
                )
                logger.info(
                    "dispatching mission {} to worker {}".format(mission_1st.id, worker_1st)
                )
            except Exception as e:
                logger.error(f"cannot assign to worker {worker_1st}\nReason: {repr(e)}")


class FoxlinkBackground:
    _dbs: List[Database] = []
    _ticker: Ticker
    table_suffix = "_event_new"
    db_name = "aoi"

    def __init__(self):
        for host in FOXLINK_DB_HOSTS:
            self._dbs += [
                Database(
                    f"mysql+aiomysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{host}",
                    min_size=5,
                    max_size=20,
                )
            ]
        self._ticker = Ticker(self.fetch_events_from_foxlink, 10)
        self._2ndticker = Ticker(self.check_events_is_complete, 5)

    async def connect(self):
        db_connect_routines = [db.connect() for db in self._dbs]
        await asyncio.gather(*db_connect_routines)
        await self._ticker.start()
        await self._2ndticker.start()

    async def close(self):
        await self._2ndticker.stop()
        await self._ticker.stop()
        db_disconnect_routines = [db.disconnect() for db in self._dbs]
        await asyncio.gather(*db_disconnect_routines)

    async def get_db_table_list(self) -> List[List[str]]:
        async def get_db_tables(db: Database) -> List[str]:
            r = await db.fetch_all(
                "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = :table_name",
                {"table_name": self.db_name},
            )

            table_names = [x[0] for x in r if x[0].endswith(self.table_suffix)]
            return table_names
            # return [x for x in table_names if x not in self.table_name_blacklist]

        get_table_names_routines = [get_db_tables(db) for db in self._dbs]
        table_names = await asyncio.gather(*get_table_names_routines)
        return [n for n in table_names]

    async def get_recent_events(
        self, db: Database, table_name: str
    ) -> List[FoxlinkEvent]:
        stmt = f"SELECT * FROM `{self.db_name}`.`{table_name}` WHERE ((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND End_Time is NULL AND Start_Time >= CURRENT_TIMESTAMP() - INTERVAL 1 DAY ORDER BY Start_Time DESC;"
        rows = await db.fetch_all(query=stmt)

        return [
            FoxlinkEvent(
                id=x[0],
                project=table_name,
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

    async def get_a_event_from_table(
        self, db: Database, table_name: str, id: int
    ) -> Optional[FoxlinkEvent]:
        """
        從正崴資料庫中取得一筆事件資料

        Args:
        - db: 正崴資料庫
        - table_name: 資料表名稱
        - id: 事件資料的 id
        """
        
        stmt = f"SELECT * FROM `{self.db_name}`.`{table_name}` WHERE ID = :id;"

        try:
            row: list = await db.fetch_one(query=stmt, values={"id": id})  # type: ignore

            return FoxlinkEvent(
                id=row[0],
                project=table_name,
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

    async def check_events_is_complete(self):
        """檢查目前尚未完成的任務，同時向正崴資料庫抓取最新的故障狀況，如完成則更新狀態"""

        incomplete_mission_events = await MissionEvent.objects.filter(
            event_end_date__isnull=True
        ).all()

        async def validate_event(db: Database, event: MissionEvent):
            e = await self.get_a_event_from_table(db, event.table_name, event.event_id)
            if e is None:
                return False
            if e.end_time is not None:
                await event.update(event_end_date=e.end_time, done_verified=True)
                return True
            return False

        for event in incomplete_mission_events:
            validate_routines = [validate_event(db, event) for db in self._dbs]
            await asyncio.gather(*validate_routines)

    async def fetch_events_from_foxlink(self):
        tables = await self.get_db_table_list()

        for db_idx in range(len(tables)):
            db = self._dbs[db_idx]
            for table_name in tables[db_idx]:
                events = await self.get_recent_events(db, table_name)

                for e in events:
                    if await MissionEvent.objects.filter(
                        event_id=e.id, table_name=table_name
                    ).exists():
                        continue

                    # avaliable category range: 1~199, 300~699
                    if not (
                        (e.category >= 1 and e.category <= 199)
                        or (e.category >= 300 and e.category <= 699)
                    ):
                        continue

                    device_id = self.generate_device_id(e)

                    # if this device's priority is not existed in `CategoryPRI` table, which means it's not an out-of-order event.
                    # Thus, we should skip it.
                    # priority = await CategoryPRI.objects.filter(
                    #     devices__id__iexact=device_id, category=e.category
                    # ).get_or_none()

                    # if priority is None:
                    #     continue

                    device = await Device.objects.filter(
                        id__iexact=device_id
                    ).get_or_none()

                    if device is None:
                        continue

                    # find if this device is already in a mission
                    mission = await Mission.objects.filter(
                        device=device.id, repair_end_date__isnull=True, is_cancel=False
                    ).get_or_none()

                    if mission is not None:
                        await MissionEvent.objects.create(
                            mission=mission.id,
                            event_id=e.id,
                            table_name=table_name,
                            category=e.category,
                            message=e.message,
                            event_start_date=e.start_time,
                        )
                    else:
                        new_mission = Mission(
                            device=device,
                            name=f"{device.id} 故障",
                            required_expertises=[],
                            description="",
                        )
                        await new_mission.save()
                        await new_mission.missionevents.add(
                            MissionEvent(
                                mission=new_mission.id,
                                event_id=e.id,
                                table_name=table_name,
                                category=e.category,
                                message=e.message,
                                event_start_date=e.start_time,
                            )
                        )

    def generate_device_id(self, event: FoxlinkEvent) -> str:
        project = event.project.split(" ")[0]
        return f"{project}@{event.line}@{event.device_name}"


kill_now = False
def graceful_shutdown(signal, frame):
    global kill_now
    kill_now = True


async def main_routine():
    global kill_now

    foxlink_daemon = FoxlinkBackground()

    connect_mqtt(MQTT_BROKER, MQTT_PORT, str(uuid.uuid4()))
    await database.connect()
    if not DISABLE_FOXLINK_DISPATCH:
        await foxlink_daemon.connect()

    # if daemon isn't killed, run forever
    while not kill_now:
        logger.warning('[main_routine] Foxlink daemon is running...')
        start = time.perf_counter()

        await auto_close_missions()
        await worker_monitor_routine()
        await overtime_workers_routine()
        await track_worker_status_routine()
        await check_mission_duration_routine()
        #await check_alive_worker_routine()

        if not DISABLE_FOXLINK_DISPATCH:
            await dispatch_routine()

        end = time.perf_counter()

        logger.warning("[main_routine] took %.2f seconds", end - start)
            
        await asyncio.sleep(1) # idle duration between two loops

    logger.warning("Shutting down...")
    if not DISABLE_FOXLINK_DISPATCH:
        await foxlink_daemon.close()
    await database.disconnect()
    disconnect_mqtt()
    

if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    loop = asyncio.get_event_loop()
    loop.create_task(main_routine())
    loop.run_forever()
