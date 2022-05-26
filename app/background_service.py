import logging, asyncio, aiohttp
import uuid
import signal
import time
from databases import Database
from ormar import or_, and_
import pytz
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.models.schema import MissionDto
from app.utils.timer import Ticker
from foxlink_dispatch.dispatch import Foxlink_dispatch
from app.services.mission import assign_mission
from app.services.user import get_user_first_login_time_today
from app.my_log_conf import LOGGER_NAME
from app.utils.utils import CST_TIMEZONE, get_shift_type_now, get_shift_type_by_datetime
from app.mqtt.main import connect_mqtt, publish, disconnect_mqtt
from app.env import (
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

        if w.location is None:
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
                and_(
                    # left: user still working on a mission, right: user is not accept a mission yet.
                    or_(
                        and_(
                            repair_start_date__isnull=False,
                            repair_end_date__isnull=True,
                        ),
                        and_(
                            repair_start_date__isnull=True, repair_end_date__isnull=True
                        ),
                    ),
                    assignees__username=w.user.username,
                    is_cancel=False,
                )
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
        logger.warning(
            f"no worker available to dispatch for mission: (mission_id: {mission_1st_id}, device_id: {mission_1st.device.id})"
        )
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


class FoxlinkBackground:
    _dbs: List[Database] = []
    _ticker: Ticker
    table_suffix = "_event_new"
    db_name = "aoi"

    def __init__(self):
        for host in FOXLINK_DB_HOSTS:
            self._dbs += [
                Database(f"mysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{host}")
            ]
        self._ticker = Ticker(self.fetch_events_from_foxlink, 3)
        self._2ndticker = Ticker(self.check_events_is_complete, 10)

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
                    mission_event = await MissionEvent.objects.filter(
                        event_id=e.id, table_name=table_name
                    ).get_or_none()

                    if mission_event is not None:
                        continue

                    device_id = self.generate_device_id(e)

                    # if this device's priority is not existed in `CategoryPRI` table, which means it's not an out-of-order event.
                    # Thus, we should skip it.
                    priority = await CategoryPRI.objects.filter(
                        devices__id__iexact=device_id, category=e.category
                    ).get_or_none()

                    if priority is None:
                        continue

                    device = await Device.objects.filter(id__iexact=device_id).get()

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


foxlink_daemon = FoxlinkBackground()
kill_now = False


def graceful_shutdown(signal, frame):
    global kill_now
    kill_now = True


async def main_routine():
    global kill_now

    connect_mqtt(MQTT_BROKER, MQTT_PORT, str(uuid.uuid4()))
    await database.connect()
    await foxlink_daemon.connect()

    while not kill_now:
        await asyncio.gather(
            auto_close_missions(),
            worker_monitor_routine(),
            notify_overtime_workers(),
            check_mission_duration_routine(),
        )
        await check_alive_worker_routine()
        await dispatch_routine()

        time.sleep(5)

    logger.warning("Shutting down...")
    await database.disconnect()
    disconnect_mqtt()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    asyncio.run(main_routine())
