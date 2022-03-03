"命名方式"
# fn_       : def, method, function 函數 
# df_       : dataframe 資料表
# parm_     : 可控參數 parameter
# _name_    : fn_ 在處理過程中的資料，非物件屬性，無法被取得。
# self.     : 物件屬性，可被取得。
# re_       : 回傳給 server 使用，非 df_ 的 回傳值。
#%%
import pandas as pd
#%%
class Foxlink_dispatch():
    def __init__(self):
        """可控參數(parm)"""
        return
    
    '''接收 server 未指派的任務'''
    def get_missions(self,missions): # m : 代表未指派 mission(event)
        # server回傳資訊，用 dataframe 儲存待辦 mission 對應的相關資訊(未來可持續調整)，下方 mission_list 可做參考
        # mission_list 資訊內容：columns=["missionID","event_count","refuse_count","process","device","category","priority","create_date"] (未來可持續調整)
        self.df_mission_list = pd.DataFrame(missions,columns=["DeviceID", # str; 所屬設備ID
                                                              "missionID", # str；待辦事項的ID
                                                              "event_count", # int；"此事件"發生的歷史次數(月累積)
                                                              "refuse_count", # int；此任務被拒絕次數
                                                              "process", # int；製程段
                                                              "device", # int；機台"號碼"
                                                              "category",# int；異常類型
                                                              "priority", # int；各專案 異常類型 對應的 優先順序
                                                              "create_date" # 事件發生時間，對應正崴事件View表的 Start_Time
                                                              ])
        return self.df_mission_list

    '''未指派 mission 進行優先度排序；Rule_Based'''
    def mission_priority(self):
        # 用 dataframe 儲存
        # 排序規則(當前)：refuse_count、process、priority、create_time,event_count"
        # process_order = CategoricalDtype([3,1,2], ordered=True) # 製程排序；目前 M3 比較重要
        self.df_mission_rank = self.df_mission_list.sort_values(by = ["refuse_count","create_date","process","priority","event_count"],
                                                                ascending = [False,True,False,True,True]
                                                                # key = []
                                                                )
        self.re_mission_1st = self.df_mission_rank["missionID"][0]
        return self.re_mission_1st # 回傳第一順位的待辦事項的 missionID 給 server
    
#%%
    '''由 server 回傳 mission_1st 的可用候選員工資訊'''
    def get_dispatch_info(self,workers):
        # server 回傳 mission_1st 所屬的"車間員工"，出席、"技能等級不為0" 且 "閒置" 者
        # 員工資訊內容 : 員工ID、人員當前位置到 mission_1st 位置在該 factorymap 的距離、閒置時間(秒)、今日派遣次數、總指派次數、對應任務的指派次數、員工的技能等級(類似"員工經驗表"那樣)
        self.df_candidate_info = pd.DataFrame(workers,columns=["workerID", # str
                                                               "distance", # float；# 人員當前位置至 mission_1st 位置在該 factorymap 中的距離
                                                               "idle_time", # datatime；人員閒置時間
                                                               "daily_count", # int；"今日指派次數"
                                                               # "dis_hist_count", # int；根據歷史紀錄抓取"總指派次數"
                                                               # "event_hist_count", # int；對應任務的歷史指派次數"
                                                               "level" # int；技能等級
                                                               ])
        return self.df_candidate_info
        
    '''員工派工，優先順序；Rule_Based'''
    def worker_dispatch(self):
        # Rule-Based：移動距離、指派次數、閒置時間、技能等級...
        self.df_worker_rank = self.df_candidate_info.sort_values(by = ["distance","level","idle_time","daily_count"],
                                                                 ascending = [True,False,False,True]
                                                                 # key = []
                                                                 )
        self.re_candidate_1st = self.df_worker_rank["workerID"][0]
        return self.re_candidate_1st # 回傳第一順位的人的 workerID 給 server

    '''若有一員工原地等待超過"特定時間"，則返還至消防站；一次處理一人'''
    def move_to_rescue(self,distances):
        # 單一人員的位置；人員所屬車間移動距離矩陣
        self.df_rescue_dis = pd.DataFrame(distances, # server 回傳該人員在所對應的"車間移動距離矩陣"中，抓取當前位置對應至"各消防站的距離"    
                                          columns = ["rescueID",# 消防站位置 ID
                                                  "distance"] # float；員工"當前位置"移動至"各消防站"的距離       
                                          ).set_index("rescueID")
        
        self.re_rescue_point = self.df_rescue_dis.idxmin().sample(n = 1)[0]
        return self.re_rescue_point # 找到最小距離的 rescueID 回傳給 server
    
#%%
"相關Excel資料表匯入，需要先進行轉換，再匯入server"
class data_convert():

    def __init__(self):
        """可控參數(parm)"""
        self.parm_cate = [i for i in range(1,200)]+[i for i in range(300,700)] # 需要指派員工的category ； 當前為 1~199,300~699
        self.parm_process = ["M1段","M2段","M3段"] # 製程段
        self.parm_machine = ["Device_"+str(i) for i in range(1,14)] # 機台名稱； 目前有 Device_1~13
        self.parm_exp = [0, 1, 2, 3] # 經驗值等級
        self.parm_job = [i for i in range(1,5)] # 職務等級； 目前 1 ~ 4
        return
    
    """車間員工資訊表"""
    def fn_factory_worker_info(self,excel_file_path):
        print("轉換中...")
        "讀取員工資料表"
        # 如跳出"UserWarning: Data Validation extension is not supported and will be removed" 是因為excel表有使用到'資料驗證'功能，但並不影響程式執行與轉換，可正常執行。
        self.df_factory_worker_info = pd.read_excel(excel_file_path, sheet_name = 0, header = None)
        "抓取員工資訊；職位判斷，負責人關係..."
        self.df_worker_info = self.df_factory_worker_info.iloc[5:,0:6].rename(columns = self.df_factory_worker_info.iloc[4,0:6])

        "抓取專案與機台資訊"
        self.df_project_info = self.df_factory_worker_info.iloc[0:4,5:].set_index(5).fillna(method = "ffill",axis = 1) # 填補 nan (excel 合併儲存格，python讀取後只有一格有值，其他為nan)

        "抓取員工機台經驗資訊"
        _exp_ = self.df_factory_worker_info.iloc[5:,6:]
        self.df_factory_worker_info_convert = pd.DataFrame() # 空白資料表，準備儲存使用

        for w in range(len(self.df_worker_info)):# 員工數量
            for p in range(len(self.df_project_info.columns)): # 所有專案中機台數量
                 # 逐筆新增
                self.df_factory_worker_info_convert = self.df_factory_worker_info_convert.append({"worker_id":str(self.df_worker_info["員工編號"].iloc[w]), # str； 員工工號
                                                                                                  "worker_name":str(self.df_worker_info["員工名字"].iloc[w]), # str； 員工名字
                                                                                                  "job":self.df_worker_info["職務"].iloc[w], # int； 員工所屬職位，可用於判斷是否為管理層
                                                                                                  "superior":str(self.df_worker_info["負責人"].iloc[w]), # str； 員工所屬之上級管理人
                                                                                                  "workshop":str(self.df_worker_info["車間"].iloc[w]), # str； 所屬車間
                                                                                                  "project":str(self.df_project_info.loc["專案"].iloc[p]), # str； 所屬專案
                                                                                                  "process":str(self.df_project_info.loc["自動機製程段"].iloc[p]), # str； 所屬專案之製程段
                                                                                                  "device_name":str(self.df_project_info.loc["Device"].iloc[p]), # str； 所屬專案之機台
                                                                                                  "shift":int(self.df_worker_info["班別"].iloc[w]), # int； 排班別
                                                                                                  "level":int(_exp_.iloc[w,p]) # int； 員工機台經驗等級
                                                                                                  },ignore_index=1)
        self.df_factory_worker_info_convert["project"] = self.df_factory_worker_info_convert["project"].str.split("/")# project 切分/ ； 各 project 獨立一欄
        self.df_factory_worker_info_convert = self.df_factory_worker_info_convert.explode('project').reset_index(drop = 1)
        print("轉換完成")
        return self.df_factory_worker_info_convert # 資料表轉換完成，提供給server做後續匯入動作

    """車間機種事件簿"""
    # 一次處理一個機種事件簿 excel表； e.g. D5X device事件簿.xlsx
    def fn_proj_eventbooks(self,excel_file_path): # 輸入資料路徑與名稱；須注意資料名稱格式
        print("轉換中...")
        _project_name_ = excel_file_path.split("/")[-1].split(" ")[0] # 抓取 project 檔案名稱
        self.df_proj_eventbooks = pd.read_excel(excel_file_path,sheet_name=None) # 讀 excel 資料
        _devices_ = list(self.df_proj_eventbooks.keys()) #根據"工作表"名稱進行抓取device名稱
        
        
        
        self.df_proj_eventbooks_convert = pd.DataFrame() # 空白資料表，準備儲存使用
        for j in _devices_: # 依照 device 進行區分
            _events_ = self.df_proj_eventbooks[j][["Category","MESSAGE","优先顺序"]] # 該 device 的 event 資訊欄位
            _events_["project"] = _project_name_ # 新增欄位；整column填入
            _events_["Device_Name"] = j # 新增欄位；整column填入
            self.df_proj_eventbooks_convert = self.df_proj_eventbooks_convert.append(_events_, ignore_index=True) # 一筆筆新增
        # 篩選出含括在 Category 中的項目
        self.df_proj_eventbooks_convert = self.df_proj_eventbooks_convert[self.df_proj_eventbooks_convert["Category"].isin(self.parm_cate)].reset_index(drop = True)
        print("轉換完成")
        return self.df_proj_eventbooks_convert # 資料表轉換完成，提供給server做後續匯入動作
    
#%%
    """車間移動距離表；server必須要製作id才可以進行轉換!"""
    # 目前為針對 第九車間 layout 客製化計算，layout無更動(僅是換機台名稱)則可使用；無法針對layout變動後做計算
    def fn_factorymap(self,excel_file_path):# 輸入車間機台座標資料表，生成簡易移動距離矩陣
        print("轉換中...")    
        self.df_deivce_xy = pd.read_excel(excel_file_path) # 讀取車間機台座標表
        # 根據座標資料table取出所有device還有消防站的"id"
        self.df_movingMatrix = pd.DataFrame(index = self.df_deivce_xy["id"], columns=self.df_deivce_xy["id"]) # 建立空對稱矩陣，用於儲存計算後的機台間移動距離
        "試算距離 Manhattan Distance"
        for i in range(len(self.df_deivce_xy)):      
            From_device = self.df_deivce_xy.iloc[i] # 起點 device
            for j in range(i,len(self.df_deivce_xy)):
                To_device = self.df_deivce_xy.iloc[j] # 終點device
                "相關判斷"
                if From_device["process"] != To_device["process"]: # 判斷兩device 是否屬於相同製程(process)
                    dis_cal =sum(abs(To_device[["x_axis","y_axis"]]-From_device[["x_axis","y_axis"]])) # 屬於不同製程，直接計算 Manhattan Distance
                else:# 如果是同製程       
                    #檢查在當前(M1或M3)製程中，有沒有其他device(障礙物)的y座標位於這兩個device的y座標之間
                    if self.df_deivce_xy[self.df_deivce_xy["process"]==From_device["process"]]["y_axis"].between(min(From_device["y_axis"],To_device["y_axis"]),max(From_device["y_axis"],To_device["y_axis"]),inclusive="neither").any():
                        if From_device["process"] in ["M1段","M2段"]: # 判斷製程是M1或M2
                            to_aisle = 1.0 #最邊緣兩測的device中心點，到走道的來回距離(因為有一開始從邊緣device到走道的距離和後面從走道到邊緣device的距離，所以是0.5*2)
                        else:
                            if To_device["project"].lower() in ["n84"]:# 判斷是否是在M3製程中的n84機種
                                to_aisle = 0.5 # 0.25*2
                            else:
                                to_aisle = 1.0
                        # 找到起始device(From_device)那一條產線最左邊與最右邊的device座標
                        From_left = self.df_deivce_xy.iloc[self.df_deivce_xy[(self.df_deivce_xy["process"]==From_device["process"])&(self.df_deivce_xy["project"]==From_device["project"])]["x_axis"].idxmin()]
                        From_right = self.df_deivce_xy.iloc[self.df_deivce_xy[(self.df_deivce_xy["process"]==From_device["process"])&(self.df_deivce_xy["project"]==From_device["project"])]["x_axis"].idxmax()]
                        # 計算 Manhattan Distance；是由"起始device"到"走道"的距離，再加上"走道"到"終點"的距離
                        From_left_dis = abs(From_device["x_axis"]-From_left["x_axis"])+abs(From_device["y_axis"]-From_left["y_axis"])+abs(From_left["x_axis"]-To_device["x_axis"])+abs(From_left["y_axis"]-To_device["y_axis"])+to_aisle
                        From_right_dis = abs(From_device["x_axis"]-From_right["x_axis"])+abs(From_device["y_axis"]-From_right["y_axis"])+abs(From_right["x_axis"]-To_device["x_axis"])+abs(From_right["y_axis"]-To_device["y_axis"])+to_aisle
                        # 移動有左右兩種，取其中較短的距離
                        dis_cal = min(From_left_dis,From_right_dis)
                    # 相鄰兩製程段中間如果沒有其他y，代表無障礙，可以直接算Manhattan Distance
                    else:
                        dis_cal =sum(abs(To_device[["x_axis","y_axis"]]-From_device[["x_axis","y_axis"]]))
                "儲存移動距離"
                # 根據起始與終點device的id，儲存到self.df_movingMatrix對應的位置
                self.df_movingMatrix.loc[From_device["id"],To_device["id"]] = dis_cal
        "對稱補植；對稱矩陣"
        for i in range(len(self.df_movingMatrix)):
            for j in range(i,len(self.df_movingMatrix)):
                self.df_movingMatrix.iloc[j,i] = self.df_movingMatrix.iloc[i,j]
        print("轉換完成")
        return self.df_movingMatrix # 回傳計算完的機台間移動距離矩陣表        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        