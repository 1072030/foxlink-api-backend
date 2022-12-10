
import math
import pandas as pd
import traceback
from ormar import or_, and_
from sqlalchemy.sql import func
from typing import Dict, List, Tuple
from fastapi import UploadFile
from fastapi import HTTPException, status as HTTPStatus
from foxlink_dispatch.dispatch import data_convert
from app.foxlink.db import foxlink_dbs
from app.foxlink.utils import assemble_device_id
from app.services.mission import _cancel_mission
from app.services.user import get_password_hash
from app.utils.utils import AsyncEmitter
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    FactoryMap,
    WorkerStatusEnum,
    ShiftType,
    api_db,
    transaction,
    UserLevel,
    get_ntz_now
)


data_converter = data_convert()


@transaction
async def import_devices(excel_file: UploadFile, user:User) -> Tuple[List[str], pd.DataFrame]:
    try:
        frame: pd.DataFrame = pd.read_excel(await excel_file.read(), sheet_name=0)

        workshops = frame["workshop"].drop_duplicates()

        create_device_bulk: Dict[str, List[Device]] = {}
        update_device_bulk: Dict[str, List[Device]] = {}

        workshop_entity_dict: Dict[str, FactoryMap] = {}
        device_entity_dict: Dict[str, Device] = {}

        # first create workshop if not exists
        for workshop in workshops:
            factory = await FactoryMap.objects.filter(name=workshop).get_or_none()

            if not factory:
                factory = await FactoryMap.objects.create(
                    name=workshop, related_devices="[]", map="[]"
                )

            workshop_entity_dict[workshop] = factory
            create_device_bulk[workshop] = []
            update_device_bulk[workshop] = []

        # fetch current devices
        device_entity_dict = {
            workshop: {
                device.id: device
                for device in (
                    await Device.objects
                    .filter(workshop=workshop_entity_dict[workshop].id)
                    .select_related(["missions","missions__worker","begin_users","nearby_users"])
                    .all()
                )
            }
            for workshop in workshops
        }
    
        # create/update new devices infos
        for index, row in frame.iterrows():
            #===============HARD SETTINGS===============
            is_rescue: bool = row["project"] == "rescue"
            line: int = int(row["line"]) if not math.isnan(
                row["line"]) else None
            workshop: str = row["workshop"]
            project: str = row["project"]
            device_name: str = row["device_name"]
            device_id: str = assemble_device_id(
                project,
                workshop if is_rescue else line,
                device_name
            )
            #===============SOFT SETTINGS===============
            process: str = row["process"] if type(row["process"]) is str else None
            x_axis: float = float(row["x_axis"])
            y_axis: float = float(row["y_axis"])
            sop_link: str = row["sop_link"]

            if is_rescue:
                device_cname = f"{workshop} - {row['device_name']} 號救援站"
            else:
                device_cname = await foxlink_dbs.get_device_cname(
                    workshop,
                    project,
                    line,
                    device_name
                )
           

            if(workshop in device_entity_dict and device_id in device_entity_dict[workshop]):
                device = device_entity_dict[workshop].pop(device_id)
                # update soft settings
                device.process = process
                device.x_axis = x_axis
                device.y_axis = y_axis
                device.sop_link = sop_link
                update_device_bulk[workshop].append(device)
            else:
                # create  new device
                device = Device(
                    id=device_id,
                    project=project,
                    process=process,
                    device_name=device_name,
                    line=line,
                    x_axis=x_axis,
                    y_axis=y_axis,
                    sop_link=sop_link,
                    is_rescue=is_rescue,
                    workshop=workshop_entity_dict[workshop].id,
                    device_cname=device_cname,
                    updated_date=get_ntz_now()
                )
                create_device_bulk[workshop].append(device)

            # configure frame for further needs.
            frame.at[index, "id"] = device_id
        
        # update workshop entity
        current_all_device_ids: List[str] = []
        workshop_rescue_device = {workshop: None for workshop in workshops}
        for workshop in workshops:
            current_workshop_device = sorted(
                update_device_bulk[workshop] + create_device_bulk[workshop],
                key= lambda x: x.is_rescue,
                reverse=True
            )

            current_workshop_device_ids = [
                device.id for device in current_workshop_device
            ]

            workshop_rescue_device[workshop] = current_workshop_device[0]

            current_all_device_ids += current_workshop_device_ids

            # update soft settings of devices
            if (len(update_device_bulk[workshop]) > 0):
                await Device.objects.bulk_update(
                    objects=update_device_bulk[workshop],
                    columns=["x_axis","y_axis","sop_link","process"]
                )

            # create devices
            if (len(create_device_bulk[workshop]) > 0):
                await Device.objects.bulk_create(create_device_bulk[workshop])

            params = await calcuate_factory_layout_matrix(workshop, frame)

        # deal with unlisted devices, remove and cancel the related missions, update nearby and startup users.
        emitter = AsyncEmitter()
        for workshop,devices in device_entity_dict.items():
            legacy_begin_users = []
            legacy_nearby_users = []
            for device in devices.values():
                for mission in device.missions:
                    emitter.add(_cancel_mission(mission,user))
                legacy_begin_users += [ user.badge for user in device.begin_users]
                legacy_nearby_users += [ user.badge for user in device.nearby_users]
            emitter.add(
                User.objects
                .filter(
                    badge__in=legacy_begin_users
                )
                .update(
                    start_position = workshop_rescue_device[workshop].id
                ),
                User.objects
                .filter(
                    badge__in=legacy_nearby_users
                )
                .update(
                    at_device = workshop_rescue_device[workshop].id
                )
            )
        await emitter.emit()

        # remote unlisted devices.
        await Device.objects.exclude(id__in=current_all_device_ids).delete(each=True)

        # done, return results
        return frame["id"].unique().tolist(), params

    except Exception as e:
        print(e)
        traceback.print_exc()
        raise e


async def calcuate_factory_layout_matrix(workshop: str, frame: pd.DataFrame) -> pd.DataFrame:
    data = data_converter.fn_factorymap(
        frame.loc[frame["workshop"] == workshop])
    matrix: List[List[float]] = []

    for index, row in data["result"].iterrows():
        native_arr = [float(x) for x in row.values.tolist()]
        matrix.append(native_arr)

    await FactoryMap.objects.filter(name=workshop).update(
        related_devices=data["result"].columns.values.tolist(), map=matrix
    )

    return data["parameter"]


@transaction
async def import_factory_worker_infos(workshop: str, worker_file: UploadFile, device_file: UploadFile) -> pd.DataFrame:

    raw_excel: bytes = await worker_file.read()
    raw_excel_device_xy: bytes = await device_file.read()

    data = data_converter.fn_factory_worker_info(
        worker_file.filename, raw_excel
    )
    frame_device_xy: pd.DataFrame = pd.read_excel(
        raw_excel_device_xy, sheet_name=0
    )
    moving_matrix = data_converter.fn_factorymap(frame_device_xy)
    initial_pos = data_converter.fn_worker_start_position()

    factory_worker_info, params = data["result"], data["parameter"]
    workshop_entity_dict: Dict[str, FactoryMap] = {}
    workshop_default_rescue: Dict[str, Device] = {}
    worker_name_entity_dict: Dict[str, User] = {}
    create_worker_bulk: List[User] = []
    update_worker_bulk: List[User] = []
    create_user_device_levels_bulk: List[UserDeviceLevel] = []
    update_user_device_levels_bulk: List[UserDeviceLevel] = []

    # fetch occuring workshop related entities
    for workshop in factory_worker_info['workshop'].unique():
        # build entity matching
        entity = await FactoryMap.objects.fields(["id", "name"]).filter(name=workshop).get_or_none()
        if (entity == None):
            raise HTTPException(
                status_code=400, detail=f"unknown workshop name: {workshop}"
            )
        workshop_entity_dict[workshop] = entity
        entity.map
        # build rescue station matching
        rescue = await Device.objects.filter(workshop=workshop_entity_dict[workshop], is_rescue=True).first()
        if (rescue == None):
            raise HTTPException(
                status_code=400, detail=f"rescue device missing in workshop: {workshop}"
            )
        workshop_default_rescue[workshop] = rescue

    # process non-repeating worker rows
    default_password_hash: str = get_password_hash("foxlink")
    worker_unique_frame = factory_worker_info[[
        'workshop', 'worker_id', 'worker_name', 'job', 'superior', 'shift'
    ]].drop_duplicates()

    # create name and id mapping
    name_id_map = {
        row[1]: row[0]
        for _, row in worker_unique_frame[["worker_id", "worker_name"]].iterrows()
    }

    for index, row in worker_unique_frame.iterrows():
        badge: str = row["worker_id"]
        username: str = row["worker_name"]
        workshop: int = workshop_entity_dict[row["workshop"]]
        superior: str = None
        shift: int = int(row["shift"]) + 1
        level: int = int(row["job"])
        if level == 1:
            try:
                start_position = initial_pos.loc[initial_pos["worker_name"]
                                                == badge].iloc[0]["start_position"]            
            except:
                start_position= None

        else:
            start_position = None
        worker = None

        worker = await User.objects.filter(badge=badge).get_or_none()

        if not await User.objects.filter(badge=badge).exists():
            # create worker entity
            worker = User(
                badge=badge,
                username=username,
                password_hash=default_password_hash,
                workshop=workshop,
                superior=superior,
                level=level,
                shift=shift,
                status=WorkerStatusEnum.leave.value,
                start_position=start_position,
                at_device=workshop_default_rescue[workshop.name],
                finish_event_date=get_ntz_now(),
            )
            worker_name_entity_dict[username] = worker
            create_worker_bulk.append(worker)
        else:
            # update worker entity
            worker = User(
                badge=badge,
                username=username,
                workshop=workshop,
                superior=superior,
                start_position=start_position,
                at_device=workshop_default_rescue[workshop.name],
                level=level,
                shift=shift,
            )
            update_worker_bulk.append(worker)

        worker_name_entity_dict[username] = worker

    # create worker
    if len(create_worker_bulk) > 0:
        await User.objects.bulk_create(create_worker_bulk)

    # update worker
    if len(update_worker_bulk) > 0:
        sample = update_worker_bulk[0]
        await User.objects.bulk_update(
            objects=update_worker_bulk,
            columns=list(sample.dict(exclude_defaults=True).keys())
        )

    # remove workers not within the provided table
    await User.objects.exclude(
        or_(
            badge__in=[user.badge for user in (
                create_worker_bulk + update_worker_bulk)],
            level__gt=UserLevel.maintainer.value
        )
    ).delete(each=True)

    # superior mapping
    for index, row in worker_unique_frame.iterrows():
        username: str = row["worker_name"]
        superior: str = (
            name_id_map[row["superior"]]
            if not row["superior"] == username else
            None
        )
        worker_name_entity_dict[username].superior = superior

    await User.objects.bulk_update(
        objects=list(worker_name_entity_dict.values()),
        columns=["superior"]
    )

    # process user device levels
    device_worker_level_unique_frame = factory_worker_info[[
        'workshop', 'process', 'project', 'device_name', 'worker_id', 'level'
    ]].drop_duplicates()
    unknown_devices_in_table = []

    for _, row in device_worker_level_unique_frame.iterrows():
        workshop = row["workshop"]
        process: int = row["process"]
        level: int = int(row["level"])
        project: str = row["project"]
        device_name: str = row["device_name"]
        user: str = row["worker_id"]
        device_id: str = assemble_device_id(project, "%", device_name)
        split_device_id = device_id.split('%')
        assert len(
            split_device_id) == 2, "the format isn't correct, need adjustments."

        match_devices: List[Device] = await Device.objects.filter(
            id__istartswith=split_device_id[0],
            id__iendswith=split_device_id[1]
        ).all()

        if (len(match_devices) == 0):
            unknown_devices_in_table.append(
                (workshop, project, device_name, user, device_id)
            )
        else:
            for device in match_devices:
                entity = await UserDeviceLevel.objects.filter(
                    device=device.id,
                    user=user
                ).get_or_none()

                if (entity):
                    update_user_device_levels_bulk.append(
                        UserDeviceLevel(
                            id=entity.id,
                            device=device.id,
                            user=user,
                            level=level,
                            updated_date=get_ntz_now()
                        )
                    )
                else:
                    create_user_device_levels_bulk.append(
                        UserDeviceLevel(
                            device=device.id,
                            user=user,
                            level=level
                        )
                    )

    # create user device levels
    if len(create_user_device_levels_bulk) > 0:
        await UserDeviceLevel.objects.bulk_create(create_user_device_levels_bulk)

    # update user device levels

    if len(update_user_device_levels_bulk) > 0:
        sample = update_user_device_levels_bulk[0]
        await UserDeviceLevel.objects.bulk_update(
            objects=update_user_device_levels_bulk,
            columns=list(sample.dict(
                exclude={"user", "device"}, exclude_defaults=True))
        )

    return params
