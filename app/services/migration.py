from datetime import datetime
import math
import random
from typing import Dict, List, Tuple
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    FactoryMap,
    # CategoryPRI,
    WorkerStatusEnum,
    ShiftType,
    api_db,
)
from fastapi import HTTPException, status as HTTPStatus
from app.services.user import get_password_hash
from fastapi import UploadFile
import pandas as pd
from foxlink_dispatch.dispatch import data_convert
from app.foxlink.db import foxlink_dbs
from app.foxlink.utils import assemble_device_id
from sqlalchemy.sql import func
import traceback
import asyncio
from datetime import datetime
from ormar import or_, and_
import pandas as pd
from app.core.database import (
    transaction,
    UserLevel,
    get_ntz_now
)

data_converter = data_convert()


@transaction
async def set_start_position_df():
    raw_data_worker_info = await api_db.fetch_all(f"""
        SELECT u.badge,u.workshop,u.shift,d.process,d.project,d.device_name FROM testing_api.users u
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


 #建立員工開班位置；只要資料表有變更 "員工專職表" 或是 "Layout座標表" 都需要重新計算一次
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


@transaction
async def import_devices(excel_file: UploadFile) -> Tuple[List[str], pd.DataFrame]:
    try:
        frame: pd.DataFrame = pd.read_excel(await excel_file.read(), sheet_name=0)

        workshops = frame["workshop"].drop_duplicates()

        create_device_bulk: Dict[str, List[Device]] = {}
        update_device_bulk: Dict[str, List[Device]] = {}

        workshop_entity_dict: Dict[str, FactoryMap] = {}

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

        # create/update devices
        for index, row in frame.iterrows():
            is_rescue: bool = row["project"] == "rescue"
            line: int = int(row["line"]) if not math.isnan(
                row["line"]) else None
            workshop: str = row["workshop"]
            project: str = row["project"]
            process: str = row["process"] if type(
                row["process"]) is str else None
            device_name: str = row["device_name"]
            x_axis: float = float(row["x_axis"])
            y_axis: float = float(row["y_axis"])
            sop_link: str = row["sop_link"]

            device_id: str = assemble_device_id(
                project,
                workshop if is_rescue else line,
                device_name
            )

            if is_rescue:
                device_cname = f"{workshop} - {row['device_name']} 號救援站"
            else:
                device_cname = await foxlink_dbs.get_device_cname(
                    workshop,
                    project,
                    line,
                    device_name
                )

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

            # categorize device object type.
            if await Device.objects.filter(id=device_id).exists():
                update_device_bulk[workshop].append(device)
            else:
                create_device_bulk[workshop].append(device)

            # configure frame for further needs.
            frame.at[index, "id"] = device_id

        # update workshap entity & remove unlisted devices
        current_all_device_ids: List[str] = []
        for workshop in workshops:
            _workshop = await FactoryMap.objects.exclude_fields(["map", "image"]).get(name=workshop)
            current_workshop_device_ids = [
                device.id for device in (
                    update_device_bulk[workshop] + create_device_bulk[workshop]
                )
            ]

            current_all_device_ids += current_workshop_device_ids

            # update devices
            if (len(update_device_bulk[workshop]) > 0):
                sample = update_device_bulk[workshop][0]
                await Device.objects.bulk_update(
                    objects=update_device_bulk[workshop],
                    columns=list(sample.dict(exclude_defaults=True).keys())
                )

            # create devices
            if (len(create_device_bulk[workshop]) > 0):
                await Device.objects.bulk_create(create_device_bulk[workshop])

            params = await calcuate_factory_layout_matrix(workshop, frame)

        await Device.objects.exclude(id__in=current_all_device_ids).delete(each=True)

        await set_start_position_df()

        return frame["id"].unique().tolist(), params

    except Exception as e:
        print(e)
        traceback.print_exc()
        raise e

# TODO: remove orphan category priorities
# 匯入 Device's Category & Priority
# @transaction
# async def import_workshop_events(excel_file: UploadFile) -> pd.DataFrame:
#     """
#     Return: parameters in pandas format
#     """
#     raw_excel: bytes = await excel_file.read()
#     data = data_converter.fn_proj_eventbooks(excel_file.filename, raw_excel)
#     df, param = data["result"], data["parameter"]

#     project_name = df["project"].unique()[0]

#     for device_name in df["Device_Name"].unique():
#         devices = await Device.objects.filter(
#             project__iexact=project_name,
#             device_name__iexact=device_name.replace(" ", "_"),
#         ).all()

#         for d in devices:
#             await d.categorypris.clear()

#     for index, row in data["result"].iterrows():
#         if math.isnan(row["优先顺序"]):
#             continue

#         devices = await Device.objects.filter(
#             project__iexact=row["project"],
#             device_name__iexact=row["Device_Name"].replace(" ", "_"),
#         ).all()

#         # await CategoryPRI.objects.filter(devices=devices).delete(each=True)

#         p = await CategoryPRI.objects.create(
#             category=row["Category"], message=row["MESSAGE"], priority=row["优先顺序"],
#         )

#         for d in devices:
#             await p.devices.add(d)  # type: ignore

#     return param


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
async def import_factory_worker_infos(workshop: str, worker_file: UploadFile) -> pd.DataFrame:

    raw_excel: bytes = await worker_file.read()

    try:
        data = data_converter.fn_factory_worker_info(
            worker_file.filename, raw_excel
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=repr(e))

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
        
    await set_start_position_df()

    return params
