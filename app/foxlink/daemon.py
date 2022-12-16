import argparse
parser = argparse.ArgumentParser()
# parser.add_argument('-i', dest='interval', type=int, default=10)


def create(**p):
    args = []
    for k, _v in p.items():
        args.append('-' + k)
        args.append(str(_v))
    parser.parse_args(args)
    return [__name__] + args


if __name__ == "__main__":
    import asyncio
    import signal
    import time
    import argparse
    from typing import Any, Dict, List, Tuple, Optional
    from datetime import timedelta
    from app.log import logging, CustomFormatter, LOG_FORMAT_FILE
    from app.models.schema import MissionDto, MissionEventOut
    from app.utils.utils import AsyncEmitter
    from foxlink_dispatch.dispatch import Foxlink_dispatch
    from app.foxlink.model import FoxlinkEvent
    from app.utils.utils import DTO
    from app.foxlink.utils import assemble_device_id
    from app.foxlink.db import foxlink_dbs
    from app.services.mission import (
        assign_mission,
        reject_mission,
        set_mission_by_rescue_position
    )
    from app.utils.utils import get_current_shift_type
    from app.mqtt import mqtt_client
    from app.env import (
        MISSION_ASSIGN_OT_MINUTES,
        DISABLE_FOXLINK_DISPATCH,
        FOXLINK_EVENT_DB_NAME,
        FOXLINK_EVENT_DB_TABLE_POSTFIX,
        WORKER_IDLE_OT_RESCUE_MINUTES,
        MISSION_WORK_OT_NOTIFY_PYRAMID_MINUTES,
        DEBUG
    )
    from multiprocessing import Process

    from app.core.database import (
        transaction_with_logger,
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
        UserDeviceLevel,
        api_db
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
    logger.addHandler(
        logging.FileHandler('logs/foxlink(daemon).log', mode="w")
    )
    logger.handlers[-1].setFormatter(CustomFormatter(LOG_FORMAT_FILE))
    if (DEBUG):
        logger.handlers[-1].setLevel(logging.DEBUG)
    else:
        logger.handlers[-1].setLevel(logging.WARN)

    dispatch = Foxlink_dispatch()

    _terminate = None

    MAIN_ROUTINE_MIN_RUNTIME = 3
    NOTIFICATION_INTERVAL = 30

    def show_duration(func):
        async def wrapper(*args, **_args):
            logger.info(f'[{func.__name__}] started running.')
            start = time.perf_counter()
            result = await func(*args, **_args)
            end = time.perf_counter()
            logger.info(f'[{func.__name__}] took {end - start:.2f} seconds.')
            return result
        return wrapper

    def find_idx_in_factory_map(factory_map: FactoryMap, device_id: str) -> int:
        try:
            return factory_map.related_devices.index(device_id)
        except ValueError as e:
            msg = f"{device_id} device is not in the map {factory_map.name}"
            raise ValueError(msg)

    @ transaction
    @ show_duration
    async def send_mission_notification_routine():
        missions = (
            await Mission.objects
            .filter(
                repair_end_date__isnull=True,
                notify_recv_date__isnull=True,
                is_done=False,
                worker__isnull=False
            )
            .select_related(
                [
                    "device", "worker", "device__workshop",
                    "worker__at_device", "events"
                ]
            )
            .exclude_fields(
                FactoryMap.heavy_fields("device__workshop")
            )
            .all()
        )
        # RUBY: related device workshop

        async def driver(m: Mission):
            if m.device.is_rescue == False:
                await mqtt_client.publish(
                    f"foxlink/users/{m.worker.current_UUID}/missions",
                    {
                        "type": "new",
                        "mission_id": m.id,
                        "worker_now_position": m.worker.at_device.id,
                        "badge": m.worker.badge,
                        # RUBY: set worker now position and badge
                        "create_date": m.created_date,
                        "device": {
                            "device_id": m.device.id,
                            "device_name": m.device.device_name,
                            "device_cname": m.device.device_cname,
                            "workshop": m.device.workshop.name,
                            "project": m.device.project,
                            "process": m.device.process,
                            "line": m.device.line,
                        },
                        "name": m.name,
                        "description": m.description,
                        "notify_receive_date": None,
                        "notify_send_date": m.notify_send_date,
                        "events": [
                            MissionEventOut.from_missionevent(e).dict()
                            for e in m.events
                        ],
                        "timestamp": get_ntz_now()
                    },
                    qos=2,
                    retain=True
                )
            else:
                await mqtt_client.publish(
                    f"foxlink/users/{m.worker.current_UUID}/move-rescue-station",
                    {
                        "type": "rescue",
                        "mission_id": m.id,
                        "worker_now_position": m.worker.at_device.id,
                        "badge": m.worker.badge,
                        # RUBY: set worker now position and badge
                        "create_date": m.created_date,
                        "device": {
                            "device_id": m.device.id,
                            "device_name": m.device.device_name,
                            "device_cname": m.device.device_cname,
                            "workshop": m.device.workshop.name,
                            "project": m.device.project,
                            "process": m.device.process,
                            "line": m.device.line,
                        },
                        "name": m.name,
                        "description": m.description,
                        "notify_receive_date": None,
                        "notify_send_date": m.notify_send_date,
                        "events": [],
                        "timestamp": get_ntz_now()
                    },
                    qos=2,
                    retain=True
                )

        await asyncio.gather(
            *[driver(m) for m in missions]
        )

        return True

    # done

    @ transaction
    @ show_duration
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
                ["device", "worker", "worker__shift"]
            )
            .all()
        )

        # prefetch current_shift
        current_shift = await get_current_shift_type()

        async def driver(mission):
            worker_shift = ShiftType(mission.worker.shift.id)

            # shift swap required
            if current_shift == worker_shift:
                return

            # cancel mission
            await mission.update(
                is_done=True,
                is_done_shift=True,
                description='換班任務，自動結案'
            )

            if not mission.device.is_rescue:
                mission_events = await MissionEvent.objects.filter(mission=mission.id).all()

                # replicate mission of the new shift
                replicate_mission = await Mission.objects.create(
                    name=mission.name,
                    description=f"換班任務，沿用 Mission ID: {mission.id}",
                    device=mission.device,
                    is_emergency=mission.is_emergency,
                    created_date=mission.created_date
                )

                # replicate mission events for the new mission

                await asyncio.gather(
                    *[
                        replicate_mission.events.add(
                            MissionEvent(
                                event_id=e.event_id,
                                host=e.host,
                                table_name=e.table_name,
                                category=e.category,
                                message=e.message,
                                event_beg_date=e.event_beg_date,
                                event_end_date=e.event_end_date
                            )
                        ) for e in mission_events
                    ]
                )

            await asyncio.gather(
                # update worker status
                mission.worker.update(
                    status=WorkerStatusEnum.idle.value,
                    finish_event_date=get_ntz_now()
                ),

                # create audit log
                AuditLogHeader.objects.create(
                    action=AuditActionEnum.MISSION_USER_DUTY_SHIFT.value,
                    table_name="missions",
                    description=f"員工換班，維修時長: {get_ntz_now() - mission.repair_beg_date if mission.repair_beg_date is not None else 0}",
                    user=mission.worker.badge,
                    record_pk=mission.id,
                ),

                # send mission finish message
                mqtt_client.publish(
                    f"foxlink/users/{mission.worker.current_UUID}/missions/stop-notify",
                    {
                        "mission_id": mission.id,
                        "badge": mission.worker.badge,
                        # RUBY: set worker badge
                        "mission_state": "overtime-duty",
                        "description": "finish",
                        "timestamp": get_ntz_now()
                    },
                    qos=2,
                    retain=True
                )
            )

        await asyncio.gather(
            *[
                driver(mission) for mission in working_missions
            ]
        )
        return

    @ transaction
    @ show_duration
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

    @ transaction
    @ show_duration
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
                    "worker",
                    "worker__at_device",
                    "device__workshop",
                    "rejections",
                    "events"
                ]
            )
            .exclude_fields(
                FactoryMap.heavy_fields("device__workshop")
            )
            .filter(
                device__is_rescue=False
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

        ################ Building Workshop Valid Worker ######################
        workshop_valid_workers = await asyncio.gather(
            *[
                (
                    User.objects
                    .filter(
                        level=UserLevel.maintainer.value,
                        shift=current_shift.value,
                        workshop=workshop,
                        status=WorkerStatusEnum.idle.value,
                        badge__in=whitelist_users_entity_dict,
                        login_date__lt=get_ntz_now() - timedelta(seconds=5)
                    )
                    .fields(["badge"])
                    .values()

                    if i else

                    User.objects
                    .exclude(
                        badge__in=whitelist_users_entity_dict
                    )
                    .filter(
                        level=UserLevel.maintainer.value,
                        shift=current_shift.value,
                        workshop=workshop,
                        status=WorkerStatusEnum.idle.value,
                        login_date__lt=get_ntz_now() - timedelta(seconds=5),
                        at_device__isnull=False
                    )
                    .fields(["badge"])
                    .values()
                )

                for workshop in workshop_entity_dict.keys() for i in [True, False]
            ]

        )

        workshop_valid_workers = {
            workshop: {
                c: [DTO(worker).badge for worker in workshop_valid_workers[i * 2 + j]]
                for j, c in enumerate([True, False])
            }
            for i, workshop in enumerate(workshop_entity_dict.keys())
        }
        ######################################################################
        worker_entity_dict: Dict[int, User] = {
            worker.badge: worker
            for worker in (
                await User.objects
                .select_related(
                    ["at_device"]
                )
                .all()
            )
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

        async def fetch_mission_candid_workers(mission_id: int) -> Tuple[Mission, List[User]]:
            mission = mission_entity_dict[mission_id]
            workshop = mission.device.workshop.id
            device_in_whitelist = mission.device.id in whitelist_device_entity_dict
            if (not mission):
                return (None, [])

            # fetch valid workers, also consider whitelist device scenarios.
            valid_worker_user_devices = (
                await UserDeviceLevel.objects
                .filter(
                    device=mission.device.id,
                    level__gt=0,
                    user__in=workshop_valid_workers[workshop][device_in_whitelist]
                )
                .fields(["user"])
                .values()
            )

            return (
                mission,
                [
                    worker_entity_dict[DTO(user_device).user]
                    for user_device in valid_worker_user_devices
                ]
            )

        # prefetch all valid workers for mission
        mission_candid_workers: List[List[User]] = await asyncio.gather(
            *[
                fetch_mission_candid_workers(
                    mission_id
                )
                for mission_id in ranked_missions
            ]
        )

        # assigned workers
        exclude_workers = set()

        assigned_mission_counter = 0

        for mission, valid_workers in mission_candid_workers:
            if mission is None:
                continue

            # 取得該裝置隸屬的車間資訊
            workshop = workshop_entity_dict[mission.device.workshop.id]

            # 取得車間地圖資訊
            distance_matrix: List[List[float]] = workshop.map  # 距離矩陣

            # 該任務的裝置在矩陣中的位置
            mission_device_idx = find_idx_in_factory_map(
                workshop,
                mission.device.id
            )

            # create worker infos for the mission
            cand_workers = []

            for worker in valid_workers:
                # if worker rejects this mission before.
                if worker in mission.rejections:
                    continue

                if worker.badge in exclude_workers:
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
                    "daily_count": worker.shift_start_count,
                    "level": worker.level,
                }

                cand_workers.append(worker_info)

            # without worker candidates, notify the supervisor.
            if len(cand_workers) == 0:

                logger.info(
                    f"no worker to assign for mission: {mission.id}."
                )

                if not mission.is_lonely:
                    await mission.update(is_lonely=True)
                    mission_is_lonely = MissionDto.from_mission(mission).dict()
                    mission_is_lonely["timestamp"] = get_ntz_now()
                    await mqtt_client.publish(
                        f"foxlink/{workshop.name}/no-available-worker",
                        mission_is_lonely,
                        qos=2,
                        retain=True
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

                # assign mission
                await asyncio.gather(
                    assign_mission(
                        mission,
                        selected_worker
                    ),

                    AuditLogHeader.objects.create(
                        table_name="missions",
                        record_pk=mission.id,
                        action=AuditActionEnum.MISSION_ASSIGNED.value,
                        user=selected_worker
                    )
                )

                # exclude this worker from further dispatch process.
                exclude_workers.add(selected_worker)

                assigned_mission_counter += 1

                if (assigned_mission_counter == 50):
                    break

        logger.info(
            f"This dispatch cycle successfully assigned {assigned_mission_counter} missions!")

    ######### mission overtime  ########
    # half-done

    @ transaction
    @ show_duration
    async def check_mission_working_duration_overtime():
        """檢查任務持續時間，如果超過一定時間，則發出通知給員工上級但是不取消任務"""
        working_missions = (
            await Mission.objects
            .filter(
                is_done=False,
                overtime_level__lt=len(MISSION_WORK_OT_NOTIFY_PYRAMID_MINUTES),
                worker__isnull=False,
                repair_beg_date__isnull=False,
                repair_end_date__isnull=True,
            )
            .select_related(['worker', 'worker__superior'])
            # RUBY: prevent worker__superior is null
            .all()
        )
        thresholds: List[int] = [0]
        for minutes in MISSION_WORK_OT_NOTIFY_PYRAMID_MINUTES:
            thresholds.append(thresholds[-1] + minutes)
        thresholds.pop(0)
        for mission in working_missions:
            # RUBY: check ouvetime use repair_duration
            superior = mission.worker.superior
            mission_duration_seconds = mission.repair_duration.total_seconds()
            for i, thresh in enumerate(thresholds):
                if mission_duration_seconds >= thresh * 60:
                    if superior is None:
                        break

                    superior = await User.objects.filter(badge=superior.badge).get()

                    if i >= mission.overtime_level:

                        await AuditLogHeader.objects.create(
                            action=AuditActionEnum.MISSION_OVERTIME.value,
                            table_name="missions",
                            description=superior.badge,
                            record_pk=str(mission.id),
                            user=mission.worker.badge,
                        )

                        await mqtt_client.publish(
                            f"foxlink/users/{superior.badge}/mission-overtime",
                            {
                                "mission_id": mission.id,
                                "mission_name": mission.name,
                                "worker_id": mission.worker.badge,
                                "worker_name": mission.worker.username,
                                "duration": mission_duration_seconds,
                                "timestamp": get_ntz_now()
                            },
                            qos=2,
                            retain=True
                        )
                        await mission.update(overtime_level=i + 1)

                    superior = superior.superior

    # done

    @ transaction
    @ show_duration
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
                        "badge": mission.worker.badge,
                        # RUBY: set worker badge
                        "mission_state": "stop-notify" if not mission.notify_recv_date else "return-home-page",
                        "description": "over-time-no-action",
                        "timestamp": get_ntz_now()
                    },
                    qos=2,
                    retain=True
                )

                await reject_mission(mission.id, mission.worker)

                await AuditLogHeader.objects.create(
                    action=AuditActionEnum.MISSION_ACCEPT_OVERTIME.value,
                    table_name="missions",
                    record_pk=str(mission.id),
                    user=mission.worker.badge,
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
            # check if all events have completed
            if (
                (
                    await MissionEvent.objects
                    .filter(
                        mission=event.mission.id,
                        event_end_date__isnull=True
                    )
                    .count()
                ) == 0
            ):
                mission = (
                    await Mission.objects
                    .filter(id=event.mission.id)
                    .select_related("worker")
                    .get()
                )
                emitter = AsyncEmitter()
                emitter.add(
                    mission.update(
                        is_done=True,
                        is_done_cure=True
                    ),
                    AuditLogHeader.objects.create(
                        table_name="missions",
                        action=AuditActionEnum.MISSION_CURED.value,
                        record_pk=str(mission.id),
                        user=None,
                    )
                )
                if mission.worker:
                    emitter.add(
                        mission.worker.update(
                            status=WorkerStatusEnum.idle.value,
                            finish_event_date=get_ntz_now()
                        ),
                        mqtt_client.publish(
                            f"foxlink/users/{mission.worker.current_UUID}/missions/stop-notify",
                            {
                                "mission_id": mission.id,
                                "badge": mission.worker.badge,
                                # RUBY: set worker badge
                                "mission_state": "stop-notify" if not mission.notify_recv_date else "return-home-page",
                                "description": "finish",
                                "timestamp": get_ntz_now()
                            },
                            qos=2,
                            retain=True
                        )
                        # RUBY: mqtt auto-close mission
                    )
                await emitter.emit()
                return True

        return False

    # async def update_complete_events(events):
    #     mission_id = events[0].mission.id

    #     async def driver(event: MissionEvent):
    #         e = await get_incomplete_event_from_table(
    #             event.host,
    #             event.table_name,
    #             event.event_id
    #         )
    #         if e and e.end_time is not None:
    #             await event.update(event_end_date=e.end_time)
    #             return 1
    #         return 0

    #     # check if all events have completed
    #     if (sum(await asyncio.gather(*[driver(event)for event in events])) == len(events)):
    #         mission = (
    #             await Mission.objects
    #             .filter(id=mission_id)
    #             .select_related("worker")
    #             .get()
    #         )
    #         emitter = AsyncEmitter()
    #         emitter.add(
    #             mission.update(
    #                 is_done=True,
    #                 is_done_cure=True
    #             ),
    #             AuditLogHeader.objects.create(
    #                 table_name="missions",
    #                 action=AuditActionEnum.MISSION_CURED.value,
    #                 record_pk=str(mission.id),
    #                 user=None,
    #             )
    #         )
    #         if mission.worker:
    #             emitter.add(
    #                 mission.worker.update(
    #                     status=WorkerStatusEnum.idle.value,
    #                     finish_event_date=get_ntz_now()
    #                 ),
    #                 mqtt_client.publish(
    #                     f"foxlink/users/{mission.worker.current_UUID}/missions/stop-notify",
    #                     {
    #                         "mission_id": mission.id,
    #                         "badge": mission.worker.badge,
    #                         # RUBY: set worker badge
    #                         "mission_state": "stop-notify" if not mission.notify_recv_date else "return-home-page",
    #                         "description": "finish",
    #                         "timestamp": get_ntz_now()
    #                     },
    #                     qos=2,
    #                     retain=True
    #                 )
    #                 # RUBY: mqtt auto-close mission
    #             )
    #         await emitter.emit()
    #         return True
    #     return False

    @ transaction
    @ show_duration
    async def update_complete_events_handler():
        """檢查目前尚未完成的任務，同時向正崴資料庫抓取最新的故障狀況，如完成則更新狀態"""
        # TODO: can further optimize
        incomplete_mission_events = (
            await MissionEvent.objects
            .select_related("mission")
            .filter(
                event_end_date__isnull=True,
                mission__is_done=False,
                mission__repair_beg_date__isnull=True
            )
            .all()
        )

        await asyncio.gather(*[
            update_complete_events(event)
            for event in incomplete_mission_events
        ])

        return

    ######### sync event ########

    async def sync_events_from_foxlink(host: str, table_name: str, beg_id: int):
        events = await get_recent_events_from_foxlink(host, table_name, beg_id)

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
            # RUBY: set mission description
            if mission is None:
                mission = Mission(
                    device=device,
                    name=f"{device.id} 故障",
                    description="一般任務",
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

    async def latest_event_from_foxlink_of_host_table(host, table_name):
        try:
            mission_event = (
                await MissionEvent.objects
                .filter(
                    host=host,
                    table_name=table_name
                )
                .order_by(
                    MissionEvent.event_id.desc()
                )
                .first()
            )
        except Exception as e:
            mission_event = None

        return (
            host,
            table_name,
            mission_event.event_id if mission_event else 0
        )

    @ transaction
    @ show_duration
    async def sync_events_from_foxlink_handler():
        db_table_pairs = await foxlink_dbs.get_all_db_tables()

        host_table_id_pairs = await asyncio.gather(
            *[
                latest_event_from_foxlink_of_host_table(host, table)
                for host, tables in db_table_pairs
                for table in tables
            ]
        )

        await asyncio.gather(*[
            sync_events_from_foxlink(
                host,
                table,
                beg_id,
            )
            for host, table, beg_id in host_table_id_pairs
        ])

    async def get_recent_events_from_foxlink(host: str, table_name: str, beg_id: int = 0) -> List[FoxlinkEvent]:
        stmt = (
            f"SELECT * FROM `{FOXLINK_EVENT_DB_NAME}`.`{table_name}` WHERE "
            "((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND "
            "End_Time is NULL AND "
            f"ID >= {beg_id} "
            "ORDER BY ID ASC "
            "LIMIT 50;"
        )
        rows = await foxlink_dbs[host].fetch_all(
            query=stmt
        )
        return [
            FoxlinkEvent.from_raw_event(x, table_name)
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

            return FoxlinkEvent.from_raw_event(row, table_name)
        except:
            return None

    ######### main #########

    def shutdown_callback():
        global _terminate
        _terminate = True

    async def connect_services():
        api_db.options["min_size"] = 3
        api_db.options["max_size"] = 7
        while True:
            try:
                logger.info("Start to Create Connections.")
                await asyncio.gather(
                    api_db.connect(),
                    foxlink_dbs.connect(),
                    mqtt_client.connect()
                )
            except Exception as e:
                logger.error(f"{e}")
                logger.error(f"Cannot connect to the databases and servers")
                logger.error(f"Reconnect in 5 seconds...")
                await asyncio.wait(5)
            else:
                logger.info("All Connections Created.")
                break

    async def disconnect_services():
        while True:
            logger.info("Termiante Databases/Connections...")
            try:
                await asyncio.gather(
                    api_db.disconnect(),
                    mqtt_client.disconnect(),
                    foxlink_dbs.disconnect()
                )
            except Exception as e:
                logger.error(f"{e}")
                logger.error(f"Cannot disconnect to the databases and servers")
                logger.error(f"Reconnect in 5 seconds...")
                await asyncio.wait(5)
            else:
                logger.info("All Services Disconnected.")
                break

    async def general_routine():
        global _terminate
        logger.info(f"General Routine Start @{get_ntz_now()}")
        last_nofity_time = time.perf_counter()
        while (not _terminate):
            try:
                logger.info('[main_routine] Foxlink daemon is running...')

                beg_time = time.perf_counter()

                await update_complete_events_handler()

                await mission_shift_routine()

                await move_idle_workers_to_rescue_device()

                await check_mission_working_duration_overtime()

                await check_mission_assign_duration_overtime()

                await sync_events_from_foxlink_handler()

                if not DISABLE_FOXLINK_DISPATCH:
                    await mission_dispatch()

                if time.perf_counter() - last_nofity_time > NOTIFICATION_INTERVAL:
                    await send_mission_notification_routine()
                    last_nofity_time = time.perf_counter()

                end_time = time.perf_counter()

                logger.info(
                    "[main_routine] took %.2f seconds", end_time - beg_time
                )

                if (end_time - beg_time < MAIN_ROUTINE_MIN_RUNTIME):
                    await asyncio.sleep(max(MAIN_ROUTINE_MIN_RUNTIME - (end_time - beg_time), 0))

            except Exception as e:
                logger.error(
                    f'Unknown excpetion occur in general routines: {repr(e)}')
                traceback.print_exc()
                logger.error(f'Waiting 5 seconds to restart...')
                await asyncio.sleep(5)

    async def notify_routine():
        global _terminate
        while (not _terminate):
            try:
                await send_mission_notification_routine()

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(
                    f'Unknown excpetion in notify routines: {repr(e)}')
                traceback.print_exc()
                logger.error(f'Waiting 5 seconds to restart...')
                await asyncio.sleep(5)

    async def main():
        global _terminate
        _terminate = False
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, shutdown_callback)
        loop.add_signal_handler(signal.SIGTERM, shutdown_callback)

        logger.info("Daemon Initilialized.")

        ###################################################
        # connect to services
        await connect_services()
        # main loop
        await asyncio.gather(
            general_routine()
            # ,notify_routine()
        )
        # disconnect to services
        await disconnect_services()
        ###################################################

        logger.info("Daemon Terminated.")

    args = parser.parse_args()

    asyncio.run(
        main(),
        debug=DEBUG
    )
