
import math
import random
import pandas as pd
import traceback
import asyncio
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
from app.env import (
    DATABASE_NAME
)
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    FactoryMap,
    Mission,
    WorkerStatusEnum,
    ShiftType,
    api_db,
    transaction,
    UserLevel,
    get_ntz_now,
    unset_nullables
)


data_converter = data_convert()


async def set_start_position_df():
    raw_data_worker_info = await api_db.fetch_all(f"""
        SELECT u.badge,u.workshop,u.shift,d.process,d.project,d.device_name FROM {DATABASE_NAME}.users u
        INNER JOIN user_device_levels udl on udl.user=u.badge
        INNER JOIN devices d on d.id=udl.device 
        WHERE udl.`level` !=0 and u.`level` =1
    """)

    raw_data_device_info = await api_db.fetch_all(f"""SELECT d.id ,d.project ,d.process ,d.line ,d.device_name ,d.x_axis ,d.y_axis,d.workshop  FROM devices d""")
    raw_data_worker_info_df = pd.DataFrame(raw_data_worker_info)
    raw_data_device_info_df = pd.DataFrame(raw_data_device_info)
    if raw_data_device_info_df.empty or raw_data_worker_info_df.empty:
        return
    start_position = await fn_worker_start_position(
        raw_data_worker_info_df, raw_data_device_info_df)
    for index, row in start_position.iterrows():
        badge: str = row["worker_name"]
        start_position: str = row["start_position"]
        worker = await User.objects.filter(badge=badge).get()
        if worker is None:
            continue
        else:
            await worker.update(start_position=start_position)


# 建立員工開班位置；只要資料表有變更 "員工專職表" 或是 "Layout座標表" 都需要重新計算一次
async def fn_worker_start_position(df_w, df_m):  # 輸入車間機台座標資料表，生成簡易移動距離矩陣
    df_worker_start_position = pd.DataFrame()  # 建立空白資料表存取計算結果
    df_m_depot = df_m[df_m["project"] ==
                      "rescue"].reset_index(drop=True)  # 消防站位置
    df_m_device = df_m[df_m["project"] != "rescue"].reset_index(
        drop=True
    )  # device位置

    def get_minvalue(inputlist):
        # get the minimum value in the list
        min_value = min(inputlist)
        # return the index of minimum value
        res = [i for i, val in enumerate(inputlist) if val == min_value]
        return res

    for s in set(
        df_w["shift"].dropna()
    ):  # fn_factory_worker_info 中 parameter 的 shift 種類數
        df_w_shift = df_w[df_w["shift"] == s].groupby(
            ["badge"]
        )  # 選班次
        workers = []
        start_positions = []
        for i, j in df_w_shift:
            # 找對應員工經驗之機檯座標
            find_device = df_m_device[
                (df_m_device["workshop"].isin(set(j["workshop"])))
                & (df_m_device["project"].isin(set(j["project"])))
                & (df_m_device["process"].isin(set(j["process"])))
                & (df_m_device["device_name"].isin(set(j["device_name"])))
            ].reset_index(drop=True)
            # print(find_device)

            distance_list = []
            for d in range(len(df_m_depot)):  # 計算平均距離
                depot = df_m_depot.iloc[d]  # 消防站
                total_distance = (
                    (find_device["x_axis"] - depot["x_axis"]).abs()
                    + (find_device["y_axis"] - depot["y_axis"]).abs()
                ).mean()
                distance_list.append(total_distance)
            # print(distance_list)

            min_list = get_minvalue(distance_list)  # 找到最短總距離
            if len(min_list) > 1:
                min_list = random.choice(min_list)
            # print(min_list)
            position = df_m_depot.iloc[min_list].iloc[0]["id"]  # 找到該位置
            workers.append(i)
            start_positions.append(position)
            # print(position)
        shift_info = pd.DataFrame(
            {"worker_name": workers, "start_position": start_positions}
        )
        # print(shift_info)
        df_worker_start_position = pd.concat(
            [df_worker_start_position, shift_info], ignore_index=1
        )
    return df_worker_start_position
    # print(set(test_workerinfo["parameter"]["shift"].dropna()))


@transaction(force=True)
async def import_devices(excel_file: UploadFile, user: User) -> Tuple[List[str], pd.DataFrame]:

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
                .select_related(["begin_users", "nearby_users"])
                .all()
            )
        }
        for workshop in workshops
    }

    # create/update new devices infos
    for index, row in frame.iterrows():
        # ===============HARD SETTINGS===============
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
        # ===============SOFT SETTINGS===============
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

        if (workshop in device_entity_dict and device_id in device_entity_dict[workshop]):
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
            key=lambda x: x.is_rescue,
            reverse=True
        )

        current_workshop_device_ids = [
            device.id for device in current_workshop_device
        ]

        workshop_rescue_device[workshop] = current_workshop_device[0]

        current_all_device_ids += current_workshop_device_ids

        if(
        (
            await Mission.objects
            .exclude(
                device__in=current_workshop_device_ids
            )
            .filter(
                is_done=False,
                worker__isnull=False
            )
            .count() 
        ) > 0
        ):
            raise Exception("trying to remove device that are still working by or assigned to a worker.")


        # update soft settings of devices
        if (len(update_device_bulk[workshop]) > 0):
            await Device.objects.bulk_update(
                objects=update_device_bulk[workshop],
                columns=["x_axis", "y_axis", "sop_link", "process"]
            )

        # create devices
        if (len(create_device_bulk[workshop]) > 0):
            await Device.objects.bulk_create(create_device_bulk[workshop])

        params = await calcuate_factory_layout_matrix(workshop, frame)

    # deal with unlisted devices, remove and cancel the related missions, update nearby and startup users.
    emitter = AsyncEmitter()
    for workshop, devices in device_entity_dict.items():
        for mission in (
            await Mission.objects.filter(
                is_done=False,
                device__in=list(devices.keys())
            )
            .all()
        ):
            emitter.add(_cancel_mission(mission, user))
    await emitter.emit()

    emitter = AsyncEmitter()
    for workshop, devices in device_entity_dict.items():
        legacy_begin_users = []
        legacy_nearby_users = []
        for device in devices.values():
            legacy_begin_users += [user.badge for user in device.begin_users]
            legacy_nearby_users += [user.badge for user in device.nearby_users]
        emitter.add(
            User.objects
            .filter(
                badge__in=legacy_begin_users
            )
            .update(
                start_position=workshop_rescue_device[workshop].id
            ),
            User.objects
            .filter(
                badge__in=legacy_nearby_users
            )
            .update(
                at_device=workshop_rescue_device[workshop].id
            )
        )
    await emitter.emit()

    # remote unlisted devices.
    await Device.objects.exclude(id__in=current_all_device_ids).delete(each=True)

    await set_start_position_df()
    
    return frame["id"].unique().tolist(), params


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


@transaction()
async def import_factory_worker_infos(workshop: str, worker_file: UploadFile) -> pd.DataFrame:

    raw_excel: bytes = await worker_file.read()

    data = data_converter.fn_factory_worker_info(
        worker_file.filename, raw_excel
    )

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
        # ========== HARD CONDITIONS ===============
        badge: str = row["worker_id"]
        # ========== HARD CONDITIONS ===============
        username: str = row["worker_name"]
        workshop: int = workshop_entity_dict[row["workshop"]]
        superior: str = None
        shift: int = int(row["shift"]) + 1
        level: int = int(row["job"])
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
                at_device=workshop_default_rescue[workshop.name]
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
            columns=["username", "workshop", "superior", "start_position", "level", "shift"]
        )

    # remove workers not within the provided table
    # await User.objects.exclude(
    #     or_(
    #         badge__in=[user.badge for user in (
    #             create_worker_bulk + update_worker_bulk)],
    #         level__gt=UserLevel.maintainer.value
    #     )
    # ).delete(each=True)

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

    async def device_level_auditor(row):
        workshop = row["workshop"]
        process: int = row["process"]
        level: int = int(row["level"])
        project: str = row["project"]
        device_name: str = row["device_name"]
        user: str = row["worker_id"]
        device_id: str = assemble_device_id(project, "%", device_name)
        split_device_id = device_id.split('%')
        assert len(split_device_id) == 2, "the format isn't correct, need adjustments."

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

    await asyncio.gather(
        *[
            device_level_auditor(row)
            for _, row in device_worker_level_unique_frame.iterrows()
        ]
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

    await set_start_position_df()

    # remove unlisted users
    current_worker_badges = [user.badge for user in create_worker_bulk + update_worker_bulk]
    query = (
        User.objects.exclude(
            or_(
                badge__in=current_worker_badges,
                level__gt=UserLevel.chief.value
            )
        )
    )

    remove_worker_entities = (
        await query
        .select_related("assigned_missions")
        .filter(assigned_missions__is_done=False)
        .all()
    )

    emitter = AsyncEmitter()
    for worker in remove_worker_entities:
        for mission in worker.assigned_missions:
            mission = unset_nullables(mission, Mission)
            emitter.add(mission.update())
    await emitter.emit()

    await query.delete(each=True)

    return params
