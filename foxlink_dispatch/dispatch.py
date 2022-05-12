"命名方式"
# fn_       : def, method, function 函數
# df_       : dataframe 資料表
# parm_     : 可控參數 parameter
# _name_    : fn_ 在處理過程中的資料，非物件屬性，無法被取得。
# self.     : 物件屬性，可被取得。
# re_       : 回傳給 server 使用，非 df_ 的 回傳值。
# error     : 回傳出現異常的欄位
#%% 需安裝
from typing import Optional, Any
import pandas as pd
from tqdm import tqdm
import re
from scipy.spatial import distance

#%%
class Foxlink_dispatch:
    def __init__(self):
        """可控參數(parm)"""

        return

    """接收 server 未指派的任務"""

    def get_missions(self, missions):  # m : 代表未指派 mission(event)
        # server回傳資訊，用 dataframe 儲存待辦 mission 對應的相關資訊(未來可持續調整)，下方 mission_list 可做參考
        # mission_list 資訊內容：columns=["missionID","event_count","refuse_count","process","device","category","priority","create_date"] (未來可持續調整)
        self.df_mission_list = pd.DataFrame(
            missions,
            columns=[
                "DeviceID",  # str; 所屬設備ID
                "missionID",  # str；待辦事項的ID
                "event_count",  # int；"此事件"發生的歷史次數(月累積)
                "refuse_count",  # int；此任務被拒絕次數
                "process",  # int；製程段
                "device",  # int；機台"號碼"
                "category",  # int；異常類型
                "priority",  # int；各專案 異常類型 對應的 優先順序
                "create_date",  # 事件發生時間，對應正崴事件View表的 Start_Time
            ],
        )
        return self.df_mission_list

    """未指派 mission 進行優先度排序；Rule_Based"""

    def mission_priority(self):
        # 用 dataframe 儲存
        # 排序規則(當前)：refuse_count、process、priority、create_time,event_count"
        # process_order = CategoricalDtype([3,1,2], ordered=True) # 製程排序；目前 M3 比較重要
        self.df_mission_rank = self.df_mission_list.sort_values(
            by=["refuse_count", "create_date", "process", "priority", "event_count"],
            ascending=[False, True, False, True, True]
            # key = []
        )
        self.re_mission_1st = self.df_mission_rank["missionID"][0]
        return self.re_mission_1st  # 回傳第一順位的待辦事項的 missionID 給 server

    """由 server 回傳 mission_1st 的可用候選員工資訊"""

    def get_dispatch_info(self, workers):
        # server 回傳 mission_1st 所屬的"車間員工"，出席、"技能等級不為0" 且 "閒置" 者
        # 員工資訊內容 : 員工ID、人員當前位置到 mission_1st 位置在該 factorymap 的距離、閒置時間(秒)、今日派遣次數、總指派次數、對應任務的指派次數、員工的技能等級(類似"員工經驗表"那樣)
        self.df_candidate_info = pd.DataFrame(
            workers,
            columns=[
                "workerID",  # str
                "distance",  # float；# 人員當前位置至 mission_1st 位置在該 factorymap 中的距離
                "idle_time",  # datatime；人員閒置時間
                "daily_count",  # int；"今日指派次數"
                # "dis_hist_count", # int；根據歷史紀錄抓取"總指派次數"
                # "event_hist_count", # int；對應任務的歷史指派次數"
                "level",  # int；技能等級
            ],
        )
        return self.df_candidate_info

    """員工派工，優先順序；Rule_Based"""

    def worker_dispatch(self):
        # Rule-Based：移動距離、指派次數、閒置時間、技能等級...
        self.df_worker_rank = self.df_candidate_info.sort_values(
            by=["distance", "level", "idle_time", "daily_count"],
            ascending=[True, False, False, True]
            # key = []
        )
        self.re_candidate_1st = self.df_worker_rank["workerID"][0]
        return self.re_candidate_1st  # 回傳第一順位的人的 workerID 給 server

    """若有一員工原地等待超過"特定時間"，則返還至消防站；一次處理一人"""

    def move_to_rescue(self, distances):
        # 單一人員的位置；人員所屬車間移動距離矩陣
        self.df_rescue_dis = pd.DataFrame(
            distances,  # server 回傳該人員在所對應的"車間移動距離矩陣"中，抓取當前位置對應至"各消防站的距離"
            columns=["rescueID", "distance"],  # 消防站位置 ID  # float；員工"當前位置"移動至"各消防站"的距離
        ).set_index("rescueID")

        self.re_rescue_point = self.df_rescue_dis.idxmin().sample(n=1)[0]
        return self.re_rescue_point  # 找到最小距離的 rescueID 回傳給 server


#%%
"""
Custom Error；新增防呆報錯項目
"""


class DispatchException(Exception):
    def __init__(self, msg: str, detail: Optional[Any]):
        self.message = msg
        self.detail = detail

    def __repr__(self) -> str:
        class_name = self.__class__.__name__

        if self.detail is not None:
            return f"{class_name}: {self.message} ({self.detail})"
        else:
            return f"{class_name}: {self.message}"


class Error_FileName(DispatchException):  # 資料名稱錯誤
    def __init__(self, detail):
        super().__init__("資料表名稱有誤", detail)


class Error_FileContent(DispatchException):  # 資料內容錯誤
    def __init__(self, msg="資料內容錯誤", detail=None):
        super().__init__(msg, detail)


class Error_None(DispatchException):  # 空值
    def __init__(self, msg="資訊表有尚未填寫的部分", detail=None):
        super().__init__(msg, detail)


class Error_Superior(DispatchException):  # 員工負責人
    def __init__(self, msg: str, detail=None):
        super().__init__(msg, detail)


class Error_Axis(DispatchException):  # 座標
    def __init__(self, msg="車間 Layout 座標表中的座標填寫有誤", detail=None):
        super().__init__(msg, detail)


#%%
"""
相關 Excel資料表(.xlsx)匯入，需要先進行轉換，再匯入 server
"""


class data_convert:
    def __init__(self):
        return

    def natural_sort(self, l):  # 自然排序
        convert = lambda text: int(text) if text.isdigit() else text.lower()
        alphanum_key = lambda key: [convert(c) for c in re.split("([0-9]+)", key)]
        return sorted(l, key=alphanum_key)

    #%%
    """
    車間員工資訊表
    """

    def fn_factory_worker_info(self, filename: str, raw_excel: bytes):
        print(filename + " 轉換中...")
        self.df_factory_worker_info_convert = pd.DataFrame()  # 空白資料表，準備儲存使用
        try:
            "讀取員工資料表"
            # 如跳出 "UserWarning: Data Validation extension is not supported and will be removed" 是因為excel表有使用到'資料驗證'功能，但並不影響程式執行與轉換，可正常執行。
            self.df_factory_worker_info = pd.read_excel(
                raw_excel, sheet_name=0, header=None
            )
            "抓取員工資訊；職位判斷，負責人關係..."
            self.df_worker_info = self.df_factory_worker_info.iloc[5:, 0:6].rename(
                columns=self.df_factory_worker_info.iloc[4, 0:6]
            )
            if ~self.df_worker_info.columns.isin(
                ["班別", "員工工號", "員工名字", "車間", "職務", "負責人"]
            ).all():  # 檢查資料表內容，如果沒有此些值，合理判斷是上傳錯誤的內容，或是公版被修改
                self.df_error_list = self.df_worker_info.columns
                raise Error_FileContent(
                    msg=f'{filename} 的"欄位名稱"可能有誤喔~', detail=self.df_error_list
                )
            if self.df_worker_info.isnull().values.any():  # 檢查是否有空值；可以避免空欄位
                self.df_error_list = self.df_worker_info[
                    self.df_worker_info.isnull().values
                ]
                raise Error_None(
                    msg=f'{filename} 的"尚未填寫"的部分~', detail=self.df_error_list
                )
            if (
                ~self.df_worker_info["負責人"]
                .astype(str)
                .isin(self.df_worker_info["員工名字"])
                .all()
            ):  # 檢查"負責人"填寫是否正確；"負責人"含括在"員工名字"
                self.df_error_list = self.df_worker_info[
                    ~self.df_worker_info["負責人"]
                    .astype(str)
                    .isin(self.df_worker_info["員工名字"])
                ]
                value = self.df_error_list["負責人"]
                raise Error_Superior(msg=f"{filename} 有不存在的負責人", detail=value)
            "抓取專案與機台資訊"
            self.df_project_info = (
                self.df_factory_worker_info.iloc[0:4, 5:]
                .set_index(5)
                .fillna(method="ffill", axis=1)
            )  # 填補 nan (excel 合併儲存格，python讀取後只有一格有值，其他為nan)
            "抓取員工機台經驗資訊"
            self.df_exp = self.df_factory_worker_info.iloc[5:, 6:]
            if self.df_exp.isnull().values.any():  # 檢查是否有空值；可以避免空欄位
                self.df_error_list = pd.concat(
                    [self.df_worker_info, self.df_exp[self.df_exp.isnull().values]],
                    join="inner",
                    axis=1,
                )
                raise Error_None(
                    msg=f'{filename} 的"尚未填寫"的部分~', detail=self.df_error_list
                )
            for w in tqdm(range(len(self.df_worker_info))):  # 員工數量
                for p in range(len(self.df_project_info.columns)):  # 所有專案中機台數量
                    self.df_factory_worker_info_convert = pd.concat(
                        [
                            self.df_factory_worker_info_convert,
                            pd.DataFrame(
                                [
                                    {
                                        "worker_id": str(
                                            self.df_worker_info["員工工號"].iloc[w]
                                        ),  # str； 員工工號
                                        "worker_name": str(
                                            self.df_worker_info["員工名字"].iloc[w]
                                        ),  # str； 員工名字
                                        "job": self.df_worker_info["職務"].iloc[
                                            w
                                        ],  # int； 員工所屬職位，可用於判斷是否為管理層
                                        "superior": str(
                                            self.df_worker_info["負責人"].iloc[w]
                                        ),  # str； 員工所屬之上級管理人
                                        "workshop": str(
                                            self.df_worker_info["車間"].iloc[w]
                                        ),  # str； 所屬車間
                                        "project": str(
                                            self.df_project_info.loc["專案"].iloc[p]
                                        ),  # str； 所屬專案
                                        "process": str(
                                            self.df_project_info.loc["自動機製程段"].iloc[p]
                                        ),  # str； 所屬專案之製程段
                                        "device_name": str(
                                            self.df_project_info.loc["Device"].iloc[p]
                                        ),  # str； 所屬專案之機台
                                        "shift": int(
                                            self.df_worker_info["班別"].iloc[w]
                                        ),  # int； 排班別
                                        "level": int(
                                            self.df_exp.iloc[w, p]
                                        ),  # int； 員工機台經驗等級
                                    }
                                ]
                            ),
                        ],
                        ignore_index=1,
                    )
            self.df_factory_worker_info_convert[
                "project"
            ] = self.df_factory_worker_info_convert["project"].str.split(
                "/"
            )  # project 切分/ ； 各 project 獨立一欄
            self.df_factory_worker_info_convert = self.df_factory_worker_info_convert.explode(
                "project"
            ).reset_index(
                drop=1
            )

            "找出各欄位參數資訊"
            parm = {
                "worker": list(
                    zip(self.df_worker_info["員工工號"], self.df_worker_info["員工名字"])
                ),
                "workshop": sorted(
                    list(set(self.df_factory_worker_info_convert["workshop"]))
                ),
                "project": sorted(
                    list(set(self.df_factory_worker_info_convert["project"]))
                ),
                "process": self.natural_sort(
                    list(set(self.df_factory_worker_info_convert["process"]))
                ),
                "device": self.natural_sort(
                    list(set(self.df_factory_worker_info_convert["device_name"]))
                ),
                "shift": sorted(
                    list(set(self.df_factory_worker_info_convert["shift"]))
                ),
                "exp": sorted(list(set(self.df_factory_worker_info_convert["level"]))),
                "job": sorted(list(set(self.df_factory_worker_info_convert["job"]))),
            }
            self.df_factory_worker_info_parm = pd.concat(
                [pd.Series(v, name=k) for k, v in parm.items()], axis=1
            )

            print("轉換完成")
            # 資料表轉換完成，提供給server做後續匯入動作
            return {
                "result": self.df_factory_worker_info_convert,  # 轉換完成的結果
                "worker_info": self.df_worker_info.sort_values(
                    by="職務", ascending=0
                ),  # 員工資訊
                "parameter": self.df_factory_worker_info_parm,
            }  # 相關參數
        except Exception as e:
            raise DispatchException(msg="Unexpected exception", detail=str(e))

    #%%
    """
    專案 Device 事件簿
    """
    # 一次處理一個 Device 事件簿 excel表； e.g. D5X device事件簿.xlsx
    def fn_proj_eventbooks(
        self, filename: str, raw_excel: bytes
    ):  # 輸入資料路徑與名稱；須注意資料名稱格式
        self.df_proj_eventbooks_convert = pd.DataFrame()  # 空白資料表，準備儲存使用
        print(filename + " 轉換中...")
        try:
            _project_name_ = filename.split("Device")[0].strip(
                " "
            )  # 抓取 project 檔案名稱；用 "Device" 去切，注意忽略"空格"
            self.df_proj_eventbooks = pd.read_excel(
                raw_excel, sheet_name=None
            )  # 讀 excel 資料
            _devices_ = list(self.df_proj_eventbooks.keys())  # 根據"工作表"名稱抓取 Device 名稱
            for j in tqdm(_devices_):  # 依照 device 進行區分
                _events_ = self.df_proj_eventbooks[j]  # 事件簿device資訊
                if ~_events_.columns.isin(
                    ["Category", "MESSAGE", "优先顺序"]
                ).all():  # 檢查欄位名稱是否正確；確定匯入的資料正確
                    self.df_error_list = _events_.columns
                    value = set(_events_.columns).difference(
                        ["Category", "MESSAGE", "优先顺序"]
                    )
                    raise Error_FileContent(
                        msg=f"在{filename} 的 Worksheet: {j} 中有「尚未填寫」的部分喔~", detail=value
                    )
                if _events_["Category"].isnull().values.any():  # 檢查欄位是不是有空值
                    self.df_error_list = _events_[_events_["Category"].isnull().values]
                    raise Error_None(
                        msg=f"在{filename} 的 Worksheet: {j} 中的內容值可能不對喔~",
                        detail=self.df_error_list,
                    )
                _events_["project"] = _project_name_.lower()  # 新增專案名稱欄位；小寫
                _events_["Device_Name"] = j.lower()  # 新增機台名稱欄位；小寫
                self.df_proj_eventbooks_convert = pd.concat(
                    [self.df_proj_eventbooks_convert, _events_], ignore_index=True
                )  # 一筆筆df新增

            "Category欄位參數資訊；篩選 优先顺序 欄位有值者，代表需要指派"
            parm = {
                "category": sorted(
                    list(
                        set(
                            self.df_proj_eventbooks_convert[
                                ~self.df_proj_eventbooks_convert["优先顺序"].isna()
                            ]["Category"]
                        )
                    )
                )
            }
            self.df_proj_eventbooks_parm = pd.DataFrame(parm)

            print("轉換完成")
            # 資料表轉換完成，提供給server做後續匯入動作
            return {
                "result": self.df_proj_eventbooks_convert,  # 轉換完成的結果
                "parameter": self.df_proj_eventbooks_parm,
            }  # 相關參數

        except Exception as e:
            raise DispatchException(msg="Device 事件簿出現非預期的錯誤！", detail=str(e))

    #%%
    """
    車間 Layout 座標表
    server 必須要製作機台 id 才可以進行轉換!
    生成車間移動距離表
    """
    # 因當前車間機台有明顯劃分的"製程段"段區域，移動距離矩陣資料可套用至此類型之車間Layout座標表
    def fn_factorymap(self, frame: pd.DataFrame):  # 輸入車間機台座標資料表，生成簡易移動距離矩陣
        def manhattan_dis(From, To):  # 曼哈頓距離
            return sum(abs(val1 - val2) for val1, val2 in zip(From, To))

        try:
            self.df_device_xy = frame  # 讀取車間機台座標表
            if ~self.df_device_xy.columns.isin(
                [
                    "id",
                    "workshop",
                    "project",
                    "process",
                    "line",
                    "device_name",
                    "x_axis",
                    "y_axis",
                    "sop_link",
                ]
            ).all():  # 檢查欄位名稱是否正確；確定匯入的資料正確
                self.df_error_list = self.df_device_xy.columns
                raise Error_FileContent(
                    msg='車間layout座標表中有"尚未填寫"的部分喔~', detail=self.df_error_list
                )
            if (
                self.df_device_xy[["id", "x_axis", "y_axis"]].isnull().values.any()
            ):  # done # 確認資料表"id","x_axis","y_axis"欄位有無空值；才可算移動距離
                self.df_error_list = self.df_device_xy[
                    self.df_device_xy[["id", "x_axis", "y_axis"]].isnull().values
                ]
                raise Error_None(
                    msg='車間layout座標表中有"尚未填寫"的部分喔~', detail=self.df_error_list
                )
            elif (
                ~self.df_device_xy["x_axis"]
                .apply(lambda x: isinstance(x, (float, int)))
                .all()
            ):  # done # 檢查 x axis 座標值是不是整數或浮點數
                self.df_error_list = self.df_device_xy[
                    ~self.df_device_xy["x_axis"].apply(
                        lambda x: isinstance(x, (float, int))
                    )
                ]
                value = self.df_error_list["x_axis"]
                raise Error_Axis(msg='車間layout座標表中的"座標"填寫有誤喔~', detail=value)
            elif (
                ~self.df_device_xy["y_axis"]
                .apply(lambda y: isinstance(y, (float, int)))
                .all()
            ):  # done # 檢查 y axis 座標值是不是整數或浮點數
                self.df_error_list = self.df_device_xy[
                    ~self.df_device_xy["y_axis"].apply(
                        lambda y: isinstance(y, (float, int))
                    )
                ]
                value = self.df_error_list["y_axis"]
                raise Error_Axis(msg='車間layout座標表中的"座標"填寫有誤喔~', detail=value)
            _devices_ = self.df_device_xy[
                self.df_device_xy["project"] != "rescue"
            ]  # 機台(非消防站)資訊
            if _devices_.isnull().values.any():  # done # 確認所有機台相關欄位無空值
                self.df_error_list = _devices_[_devices_.isnull().values]
                raise Error_None(
                    msg='車間layout座標表中有"尚未填寫"的部分喔~', detail=self.df_error_list
                )
            "找出各欄位參數資訊"
            parm = {
                "workshop": sorted(list(set(_devices_["workshop"]))),
                "project": sorted(list(set(_devices_["project"]))),
                "process": self.natural_sort(list(set(_devices_["process"]))),
                "line": sorted(list(set(_devices_["line"]))),
                "device": self.natural_sort(list(set(_devices_["device_name"]))),
            }
            self.df_factorymap_parm = pd.concat(
                [pd.Series(v, name=k) for k, v in parm.items()], axis=1
            )
            # 根據資料表所有的"id"，製作對稱矩陣
            self.df_movingMatrix = pd.DataFrame(
                index=self.df_device_xy["id"], columns=self.df_device_xy["id"]
            )  # 建立空對稱矩陣，用於儲存計算後的機台間移動距離
            "試算距離 Manhattan Distance"
            for i in tqdm(range(len(self.df_device_xy))):
                From_device = self.df_device_xy.iloc[i]  # 起點 device
                for j in range(i, len(self.df_device_xy)):
                    To_device = self.df_device_xy.iloc[j]  # 終點device
                    if (
                        From_device["process"] == To_device["process"]
                    ):  # 判斷兩device 是否屬於相同製程(process)
                        # 如果是同製程 # 檢查在當前製程中，有沒有其他device(障礙物)的y座標位於這兩個device的y座標之間
                        if (
                            self.df_device_xy[
                                self.df_device_xy["process"] == From_device["process"]
                            ]["y_axis"]
                            .between(
                                min(From_device["y_axis"], To_device["y_axis"]),
                                max(From_device["y_axis"], To_device["y_axis"]),
                                inclusive="neither",
                            )
                            .any()
                        ):
                            # 找到起始device(From_device)那一條產線最左邊與最右邊的device座標
                            fit_xy = self.df_device_xy[
                                (
                                    (
                                        self.df_device_xy[
                                            ["project", "process", "line"]
                                        ]
                                        == From_device[["project", "process", "line"]]
                                    ).all(axis=1)
                                )
                            ]  # 選出符合條件的座標資料
                            From_left = self.df_device_xy.iloc[
                                fit_xy["x_axis"].idxmin()
                            ]  # 左邊
                            From_right = self.df_device_xy.iloc[
                                fit_xy["x_axis"].idxmax()
                            ]  # 右邊
                            # 計算 Manhattan Distance；是由"起始device"到"左、右"的距離，再加上"左、右"到"終點"的距離
                            From_left_dis = distance.cityblock(
                                [
                                    From_device["x_axis"],
                                    From_device["y_axis"],
                                    From_left["x_axis"],
                                    From_left["y_axis"],
                                ],
                                [
                                    From_left["x_axis"],
                                    From_left["y_axis"],
                                    To_device["x_axis"],
                                    To_device["y_axis"],
                                ],
                            )
                            From_right_dis = distance.cityblock(
                                [
                                    From_device["x_axis"],
                                    From_device["y_axis"],
                                    From_right["x_axis"],
                                    From_right["y_axis"],
                                ],
                                [
                                    From_right["x_axis"],
                                    From_right["y_axis"],
                                    To_device["x_axis"],
                                    To_device["y_axis"],
                                ],
                            )
                            dis_cal = min(
                                From_left_dis, From_right_dis
                            )  # 移動有左右兩種，取其中較短的距離
                        else:
                            dis_cal = distance.cityblock(
                                From_device[["x_axis", "y_axis"]],
                                To_device[["x_axis", "y_axis"]],
                            )
                    else:
                        dis_cal = distance.cityblock(
                            From_device[["x_axis", "y_axis"]],
                            To_device[["x_axis", "y_axis"]],
                        )  # 屬於不同製程，直接計算 Manhattan Distance
                    # "儲存移動距離"
                    # 根據起始與終點device的id，儲存到self.df_movingMatrix對應的位置
                    self.df_movingMatrix.loc[
                        From_device["id"], To_device["id"]
                    ] = dis_cal
            "對稱補植；對稱矩陣"
            for i in range(len(self.df_movingMatrix)):
                for j in range(i, len(self.df_movingMatrix)):
                    self.df_movingMatrix.iloc[j, i] = self.df_movingMatrix.iloc[i, j]

            print("轉換完成")
            # 回傳計算完的機台間移動距離矩陣表
            return {
                "result": self.df_movingMatrix,  # 轉換完成的結果
                "parameter": self.df_factorymap_parm,
            }  # 相關參數
        except Exception as e:
            raise DispatchException(msg="處理計算機台間移動距離矩陣表時發生錯誤：", detail=repr(e))

    #%%
    """
    建立各資料之參數(parameter)表
    """

    def fn_parm_update(self, parm_files: bytes):
        columns = [
            "worker",
            "workshop",
            "project",
            "process",
            "line",
            "device",
            "shift",
            "exp",
            "job",
            "category",
        ]
        self.df_parm = pd.concat(parm_files, ignore_index=1)
        self.df_parm = pd.concat(
            [
                self.df_parm[col].dropna().drop_duplicates().reset_index(drop=True)
                for col in self.df_parm.columns
            ],
            axis=1,
        )
        self.df_parm = self.df_parm[columns]
        return self.df_parm


#%%
"""測試派工系統"""
# test_dispatch = Foxlink_dispatch() # 建立物件

#%%
"""測試資料匯入"""
# test_data_import = data_convert()  # 建立物件

# "測試員工資訊表 轉換"
# test_file_path_workerinfo = "test_data/車間員工資訊表_公版_TEST用.xlsx"  # 測試員工資訊表資料路徑
# # test_file_path_workerinfo = "test_data/員工車間專職管理表20408[修正].xlsx" # 測試員工資訊表資料路徑
# test_workerinfo = test_data_import.fn_factory_worker_info(test_file_path_workerinfo)

# "測試機種事件簿 轉換"
# test_file_path_eventbook = "test_data/D5X Device 事件簿[修正].xlsx"  # 測試機種事件簿資料路徑
# # test_file_path_eventbook = "test_data/N104 Device 事件簿.xlsx" # 資料路徑
# # test_file_path_eventbook = "test_data/Z104 Device 事件簿_[不存在專案].xlsx" # 資料路徑
# # test_file_path_eventbook = "test_data/N84 Device 事件簿.xls" # 資料路徑
# test_eventbook = test_data_import.fn_proj_eventbooks(
#     test_file_path_eventbook.split("/")[-1], test_file_path_eventbook
# )

# "測試機台座標表 計算移動距離矩陣"
# test_file_path_layout = "test_data/車間 Layout 座標表_公版_TEST用.xlsx"  # 資料路徑
# test_moving_matrix = test_data_import.fn_factorymap(test_file_path_layout)

# "測試三表更新參數表"
# test_file_path_parm = "test_data/程式碼參數_TEST用.xlsx"  # 資料路徑
# test_parm = test_data_import.fn_parm_update(
#     [
#         test_workerinfo["parameter"],
#         test_eventbook["parameter"],
#         test_moving_matrix["parameter"],
#     ]
# )  # 更新參數表
# test_parm.to_excel("test_data/程式碼參數(及時更新)_TEST用.xlsx",index = 0)
#%%
