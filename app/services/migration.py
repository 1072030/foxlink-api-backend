import logging
from typing import List, Callable, Coroutine, Dict, Any
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    UserLevel,
    UserShiftInfo,
    Mission,
    FactoryMap,
    CategoryPRI,
    database,
)
from fastapi.exceptions import HTTPException
from app.models.schema import UserCreate
from app.services.user import get_password_hash, create_user
from app.services.device import get_device_id
from fastapi import UploadFile
from datetime import datetime
import csv
import pandas as pd

# TODO: integration
def roster_file_transform(path, output_path="./"):  # 檔案讀取位置、輸出位置(預設為本py檔下)；檔案格式限制 .xlsx
    file = pd.read_excel(path, sheet_name=None, header=None)
    key = file.keys()
    df_attend = pd.DataFrame()  # 預備儲存新的排班資料
    for d in key:  # 白班(0)夜班(1)
        df = file[d]
        df = df.dropna(how="all")  # 去除空白row
        df = df.dropna(
            thresh=len(df) / 2, axis=1
        )  # 去除 nan 太多的 column (excel讀取問題)；thresh：非nan值 的數量大於此參數值，則保留row/column
        "儲存員工出勤資訊的新結構資料表"
        df_trans = pd.DataFrame(
            columns=[
                "Worker_Name",
                "project",
                "Process",
                "Line",
                "Device_Name",
                "date",
                "day_or_night",
                "attend",
                "线长",
                "组长",
                "課級",
            ]
        )
        "資料切成四塊；日期(date_info)、產線資訊(process_info)、員工(worker_info)、管理階層(manager_info)；經過一日期一個循環"
        r = 0
        while r < len(df):
            "判斷是否為日期"
            if isinstance(df.iloc[r, 0], datetime.date):  #  檢查是不是日期資料
                date_info = df.iloc[r, 0]  # 儲存日期
                process_info = df.iloc[r + 1 : r + 3, :]  # 儲存產線資訊；自動機製程段、班別機種
                r += 3  # 跳到各班別機種員工資訊row
                # 進入一循環
                for w in range(r, len(df)):
                    if df.iloc[w, 0] == "线长":  # 以"线长"資訊欄未作為判斷，是否為非指派之員工
                        worker_info = df.iloc[r:w, :]  # 儲存員工資訊
                        manager_info = df.iloc[w : w + 3, :]  # 儲存 线长, 组长, 課級資訊
                        r = w + 3  # 理論上會跳到下一日期之 row
                        break
                    else:
                        pass
                "處理所得之四項 info 進行資料轉換"
                # nan 填補
                process_info = process_info.fillna(
                    method="ffill", axis=1
                )  # 填補 column；向右填補
                manager_info = manager_info.fillna(
                    method="ffill", axis=1
                )  # 填補 column；向右填補
                for wr in range(0, len(worker_info)):  # worker_info row 長度；注意是iloc
                    for wc in range(
                        2, len(worker_info.columns), 2
                    ):  # worker_info column 長度；wc 從 2 開始，間隔 1 (注意是iloc)
                        df_trans = df_trans.append(
                            {
                                "Worker_Name": worker_info.iloc[wr, wc],
                                "Process": process_info.iloc[0, wc].strip(
                                    "M段"
                                ),  # 只保留數字部分
                                "project": worker_info.iloc[wr, 0],
                                "Line": worker_info.iloc[wr, 1].strip(
                                    "Line"
                                ),  # 只保留數字部分
                                "Device_Name": process_info.iloc[1, wc],
                                "date": date_info,
                                "day_or_night": d,
                                "attend": worker_info.iloc[wr, wc + 1],
                                "线长": manager_info.iloc[0, wc],
                                "组长": manager_info.iloc[1, wc],
                                "課級": manager_info.iloc[2, wc],
                            },
                            ignore_index=1,
                        )
            else:
                r += 1
        df_attend = df_attend.append(df_trans)  # 合併白夜班
    "去除依舊有 nan 的 row"
    df_attend = df_attend.dropna(how="any")
    "相關欄位轉小寫"
    df_attend["project"] = df_attend["project"].str.lower()
    df_attend["Device_Name"] = df_attend["Device_Name"].str.lower()
    "切割 Device, 线长, 组长, 課級 資訊"
    df_attend["Device_Name"] = df_attend["Device_Name"].str.split(",")
    df_attend["线长"] = df_attend["线长"].str.split(",")
    df_attend["组长"] = df_attend["组长"].str.split(",")
    df_attend["課級"] = df_attend["課級"].str.split(",")
    "根據日期和班別排序"
    df_attend = df_attend.sort_values(by=["date", "day_or_night"]).reset_index(
        drop=True
    )
    "輸出、另存新檔csv,excel"
    df_attend.to_csv(
        output_path + "table_Roster_" + str(datetime.datetime.now().date()) + ".csv",
        encoding="utf-8",
        index=0,
    )
    df_attend.to_excel(
        output_path + "table_Roster_" + str(datetime.datetime.now().date()) + ".xlsx",
        encoding="utf-8",
        index=0,
    )
    return df_attend


@database.transaction()
async def process_csv_file(
    csv_file: UploadFile,
    callback: Callable[..., Coroutine],
    params: Dict[str, Any] = {},
    ignore_header: bool = True,
):
    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    is_met_header = False
    row_count = 0

    try:
        for row in reader:
            if not is_met_header and ignore_header:
                is_met_header = True
            else:
                await callback(row, **params)
            row_count += 1
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            400,
            f"raise an error when parsing csv file: {str(e)}, row count {row_count}",
        )


# async def import_users(csv_file: UploadFile):
#     """
#     Improt user list form csv file
#     """

#     lines: str = (await csv_file.read()).decode("utf-8")
#     reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

#     users: List[User] = []
#     for row in reader:
#         user = User(
#             username=row[0],
#             password_hash=get_password_hash(row[1]),
#             full_name=row[2],
#             expertises=row[3],
#             is_active=row[4],
#             is_admin=row[5],
#         )
#         users.append(user)

#     await User.objects.bulk_create(users)


async def import_devices(csv_file: UploadFile, clear_all: bool = False):
    """
    Import device list from csv file.
    """

    async def process(row: List[str]) -> None:
        max_length = 8
        if len(row) != max_length:
            raise HTTPException(400, f"each row must be {max_length} columns long")

        workshop = await FactoryMap.objects.get_or_none(name=row[5])

        if workshop is None:
            workshop = await FactoryMap.objects.create(
                name=row[5], related_devices="[]", map="[]"
            )

        if row[2] != "rescue":
            # device_id = get_device_id(row[2], int(float(row[3])), row[4])
            device = await Device.objects.get_or_none(id=row[0])

            if device is None:
                device = await Device.objects.create(
                    id=row[0],
                    project=row[1],
                    process=int(float(1)),
                    line=int(float(row[3])),
                    device_name=row[4],
                    x_axis=float(row[6]),
                    y_axis=float(row[7]),
                    workshop=workshop,
                    is_rescue=False,
                )
            else:
                await device.update(
                    process=int(float(1)),
                    x_axis=float(row[6]),
                    y_axis=float(row[7]),
                    workshop=workshop,
                )
        else:
            # is rescue station
            device = await Device.objects.get_or_create(
                id=row[0],
                project=f"{row[3]}-{row[4]}",
                device_name=row[4],
                x_axis=float(row[6]),
                y_axis=float(row[7]),
                is_rescue=True,
                workshop=workshop,
            )

    if clear_all is True:
        await Device.objects.delete(each=True)

    await process_csv_file(csv_file, process)


async def import_employee_repair_experience_table(
    csv_file: UploadFile, clear_all: bool = False
):
    async def process(row: List[str]) -> None:
        if len(row) != 6:
            raise HTTPException(400, "each row must be 6 columns long")

        user = await User.objects.get_or_none(username=row[0])

        if user is None:
            user = await create_user(
                UserCreate(
                    username=row[0],
                    password="foxlink",
                    full_name=row[1],
                    expertises=[],
                    level=UserLevel.maintainer.value,
                )
            )

        project_names = row[2].split(",")

        try:
            devices = await Device.objects.filter(
                project__istartswith=row[2], device_name=row[3]
            ).all()
            for d in devices:
                level = UserDeviceLevel(
                    user=user, device=d, shift=bool(row[4]), level=int(row[5])
                )
                await level.upsert()
        except Exception as e:
            raise HTTPException(
                400, f"raise an error when parsing csv file: {str(e)}",
            )

    if clear_all:
        await UserDeviceLevel.objects.delete(each=True)

    await process_csv_file(csv_file, process)


async def import_employee_shift_table(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        if len(row) != 8:
            raise HTTPException(400, "each row must be 8 columns long")

        user = await User.objects.get_or_none(full_name=row[0])

        if user is None:
            logging.error(f"user {row[0]} not found")
            return

        device_names = row[4].split(",")
        devices: List[Device] = []

        for n in device_names:
            arr = await Device.objects.filter(device_name=row[4]).all()
            devices += arr

        shift_type = "Night" if row[6] == "1" else "Day"
        date_of_shift = datetime.strptime(row[5], "%Y-%m-%d")

        shift = await UserShiftInfo.objects.get_or_create(
            user=user, day_or_night=shift_type, shift_date=date_of_shift
        )

        await shift.devices.add(devices[0])  # type: ignore

    await process_csv_file(csv_file, process)


async def import_employee_table(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        if len(row) != 2:
            raise HTTPException(400, "each row must be 2 columns long")
        user = User(
            id=row[0],
            username=row[0],
            full_name=row[1],
            password_hash=get_password_hash("foxlink"),
            expertises=[],
            is_active=True,
            is_admin=False,
            level=0,
        )
        await user.upsert()

    await process_csv_file(csv_file, process)


# 匯入 Device's Category & Priority
@database.transaction()
async def import_project_category_priority(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        if len(row) != 5:
            raise HTTPException(400, "each row must be 5 columns long")

        devices = await Device.objects.filter(
            project__istartswith=row[3].lower(), device_name=row[4]
        ).all()

        p = await CategoryPRI.objects.create(
            category=int(row[0]), message=row[1], priority=int(row[2])
        )

        for d in devices:
            await p.devices.add(d)  # type: ignore

    await process_csv_file(csv_file, process)


@database.transaction()
async def import_factory_map_table(name: str, csv_file: UploadFile):
    factory_m = await FactoryMap.objects.get_or_none(name=name)

    if factory_m is None:
        raise HTTPException(404, "the factory map you request is not found")

    lines: str = (await csv_file.read()).decode("utf-8")
    reader = csv.reader(lines.splitlines(), delimiter=",", quotechar='"')

    first_row: List[str] = []
    matrix: List[List[float]] = []

    row_idx = 0  # rows
    col_idx = 0  # columns
    for row in reader:
        col_idx = 0
        if row_idx == 0:
            first_row = row
            row_idx += 1
            continue
        m = []
        for col in row:
            if col_idx == 0:
                col_idx += 1
                continue

            m.append(float(col))
            col_idx += 1

        if len(m) != len(first_row) - 1:  # -1 becuase first cell(1,1) is 'id' text
            raise HTTPException(400, "each row must be the same length")

        matrix.append(m)
        row_idx += 1

    if len(matrix) != len(first_row) - 1:
        raise HTTPException(400, "each column must be the same length")

    await factory_m.update(map=matrix, related_devices=first_row[1:])


async def transform_events(csv_file: UploadFile):
    async def process(row: List[str]) -> None:
        max_length = 10
        if len(row) != max_length:
            raise HTTPException(400, f"each row must be {max_length} columns long")

        device_id = get_device_id(row[0], int(float(row[2])), row[3])
        device = await Device.objects.get_or_none(id=device_id)

        if device is None:
            return

        await Mission.objects.create(
            device=device,
            name="Mission",
            description=row[7],
            required_expertises=[],
            related_event_id=int(float(row[1])),
            is_cancel=False,
            event_start_date=datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S"),
            event_end_date=datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S"),
        )

    await process_csv_file(csv_file, process)

