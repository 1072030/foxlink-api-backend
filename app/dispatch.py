# -*- coding: utf-8 -*-

"""
本次專案之派工以"一個車間"為單位進行計算，不跨車間計算
"""
#%%
import pandas as pd

#%%
# =============================================================================
# 定義類別(class)；定義的"變數"與"函式"皆為"實體屬性"
# =============================================================================
class FoxlinkDispatch:
    def __init__(self):
        return

    """接收 server 未指派的任務"""

    def get_missions(self, missions):  # m : 代表未指派 mission(event)
        # server回傳資訊，用 dataframe 儲存待辦 mission 對應的相關資訊(未來可持續調整)，下方 mission_list 可做參考
        # mission_list 資訊內容：columns=["missionID","event_count","refuse_count","process","device","category","priority","create_date"] (未來可持續調整)
        self.mission_list = pd.DataFrame(
            missions,
            columns=[
                "missionID",  # str；待辦事項的ID
                "event_count",  # int；"此事件"發生的歷史次數(月累積)
                "refuse_count",  # int；此任務被拒絕次數
                "process",  # int；製程段
                "device",  # int；設備號碼
                "category",  # int；異常類型
                "priority",  # int；各專案 異常類型 對應的 優先順序
                "create_date",
            ],
        )  # 事件發生時間，對應正崴事件View表的 Start_Time
        return self.mission_list

    """未指派 mission 進行優先度排序；Rule_Based"""

    def mission_priority(self):
        # 用 dataframe 儲存
        # 排序規則(當前)：refuse_count、process、priority、create_time,event_count"
        self.mission_rank = self.mission_list.sort_values(
            by=["refuse_count", "create_date", "process", "priority", "event_count"],
            ascending=[False, True, False, True, True],
        )
        # 回傳第一順位的待辦事項的 missionID 給 server
        self.mission_1st = self.mission_rank["missionID"][0]
        return self.mission_1st

    """由 server 回傳 mission_1st 的可用員工資訊"""

    def get_dispatch_info(self, workers):
        # server 回傳 mission_1st 所屬的"車間員工"，出席、"技能等級不為0" 且 "閒置" 者
        # 員工資訊內容 : 員工ID、人員當前位置到 mission_1st 位置在該 factorymap 的距離、閒置時間(秒)、今日派遣次數、總指派次數、對應任務的指派次數、員工技能等級
        self.event_worker_info = pd.DataFrame(
            workers,
            columns=[
                "workerID",  # str
                "distance",  # float；# 人員當前位置至 mission_1st 位置在該 factorymap 中的距離
                "idle_time",  # datatime；人員閒置時間
                "daily_count",  # int；"今日指派次數"
                "level",  # int；技能等級
            ],
        )
        return self.event_worker_info

    """員工派工，優先順序；Rule_Based"""

    def worker_dispatch(self) -> str:
        # Rule-Based：移動距離、指派次數、閒置時間、技能等級...
        self.worker_rank = self.event_worker_info.sort_values(
            by=["distance", "level", "idle_time", "daily_count"],
            ascending=[True, False, False, True],
        )
        # worker 內容: 員工ID、所有技能等級、當前位置、指派次數、前一次任務完成到現在的閒置時間(秒)；資料呈現類似"員工經驗表"
        self.worker_1st = self.worker_rank["workerID"][0]  # 回傳第一順位的人的 workerID 給 server
        return self.worker_1st

    #%%
    """若有一員工原地等待超過"特定時間"，則返還至消防站；一次處理一人"""

    def move_to_rescue(self, distances):
        # 單一人員的位置；人員所屬車間移動距離矩陣
        self.rescue_dis = pd.DataFrame(
            distances,  # server 回傳該人員在所對應的"車間移動距離矩陣"中，抓取當前位置對應至"各消防站的距離"
            columns=["rescueID", "distance"],  # 消防站位置 ID  # float；員工"當前位置"移動至"各消防站"的距離
        ).set_index("rescueID")
        # 找到最小距離的 rescueID 回傳給 server
        self.rescue_point = self.rescue_dis.idxmin().sample(n=1)[0]

        return self.rescue_point
