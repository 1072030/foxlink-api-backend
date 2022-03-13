"命名方式"
# fn_       : def, method, function 函數 
# df_       : dataframe 資料表
# parm_     : 可控參數 parameter
# _name_    : fn_ 在處理過程中的資料，非物件屬性，無法被取得。
# self.     : 物件屬性，可被取得。
# re_       : 回傳給 server 使用，非 df_ 的 回傳值。
# error     : 回傳出現異常的欄位
#%% 需安裝
import pandas as pd
import validators
import xlrd
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
"""
Custom Error；防呆報錯
"""
class Error(Exception):
    "Base class for other exceptions"
    pass
class Error_FileName(Error): # 資料名稱錯誤
    pass
class Error_FileContent(Error): # 資料內容錯誤
    pass
class Error_None(Error): # 空值
    pass
class Error_Project(Error): # 專案類別
    pass
class Error_Shift(Error): # 班別:白班(0) 夜班(1)
    pass
class Error_Workshop(Error): # 車間
    pass
class Error_Device(Error): # 機台
    pass
class Error_Process(Error): # 製程段
    pass
class Error_Line(Error): # 線段
    pass
class Error_Category(Error): # 需要指派員工的 category
    pass
class Error_Job(Error): # 職務等級
    pass
class Error_Superior(Error): # 員工負責人
    pass
class Error_Exp(Error): # 經驗值等級
    pass
class Error_Axis(Error): # 座標
    pass
class Error_SOP(Error): # 機台SOP
    pass
#%%
"""
相關 Excel資料表(.xlsx)匯入，需要先進行轉換，再匯入 server
"""
class data_convert():

    def __init__(self):
        "可控參數(parm)"
        self.parm_shift = [str(i) for i in [0,1]] # 班別:白班(0) 夜班(1)
        self.parm_project = ["D52","D53","D54","N104","N84","D5X"] # 專案別 ；MySQL中有出現 D5X、PEPPER 等命名方式；注意 D5X 不是 "D52","D53","D54" 共用的意思
        self.parm_process = ["M1段","M2段","M3段"] # 製程段
        self.parm_device = ["Device_" + str(i) for i in range(1,14)] # 機台名稱； 目前有 Device_1~13
        self.parm_exp = [str(i) for i in [0,1,2,3]] # 經驗值等級
        self.parm_job = [str(i) for i in [1,2,3,4]] # 職務等級； 目前 1 ~ 4
        self.parm_cate = [str(i) for i in range(1,200)] + [str(i) for i in range(300,700)] # 需要指派員工的category ； 當前為 1~199,300~699
        self.parm_workshop = ["第九車間"] # 車間： 目前有 第九車間(9)，可為數字或是string，最後都會轉成string
        return
    #%%
    """
    車間員工資訊表
    """
    def fn_factory_worker_info(self,raw_excel:bytes):
        print("轉換中...")
        self.df_factory_worker_info_convert = pd.DataFrame() # 空白資料表，準備儲存使用
        try: 
            "讀取員工資料表"
            # 如跳出 "UserWarning: Data Validation extension is not supported and will be removed" 是因為excel表有使用到'資料驗證'功能，但並不影響程式執行與轉換，可正常執行。
            self.df_factory_worker_info = pd.read_excel(raw_excel, sheet_name = 0, header = None)
            if "車間員工資訊表" not in raw_excel.split("/")[-1]: # 檢查 資料表名稱
                raise Error_FileName
            if ~self.df_factory_worker_info.isin(["班別","員工工號","員工名字","車間","職務","負責人"]).any().iloc[0:6].all(): # 檢查資料表內容，如果沒有此些值，合理判斷是上傳錯誤的內容，或是公版被修改
                raise Error_FileContent
            
            "抓取員工資訊；職位判斷，負責人關係..."
            self.df_worker_info = self.df_factory_worker_info.iloc[5:,0:6].rename(columns = self.df_factory_worker_info.iloc[4,0:6])
            
            if self.df_worker_info.isnull().values.any(): # 檢查是否有空值
                self.df_error_list = self.df_worker_info[self.df_worker_info.isnull()]
                raise Error_None
            if ~self.df_worker_info["職務"].astype(str).isin(self.parm_job).all(): # 檢查"職務人"填寫是否正確
                self.df_error_list = self.df_worker_info[~self.df_worker_info["職務"].astype(str).isin(self.parm_job)]
                value = self.df_error_list["職務"]
                raise Error_Job
            if ~self.df_worker_info["負責人"].astype(str).isin(self.df_worker_info["員工名字"]).all(): # 檢查"負責人"填寫是否正確；"負責人"含括在"員工名字"
                self.df_error_list = self.df_worker_info[~self.df_worker_info["負責人"].astype(str).isin(self.df_worker_info["員工名字"])]
                value = self.df_error_list["負責人"]
                raise Error_Superior
            if ~self.df_worker_info["班別"].astype(str).isin(self.parm_shift).all(): # 檢查"班別"填寫是否正確
                self.df_error_list = self.df_worker_info[~self.df_worker_info["班別"].astype(str).isin(self.parm_shift)]
                value = self.df_error_list["班別"]
                raise Error_Shift
            if ~self.df_worker_info["車間"].isin(self.parm_workshop).all():  # 檢查"車間"填寫是否正確
                self.df_error_list = self.df_worker_info[~self.df_worker_info["車間"].isin(self.parm_workshop)]
                value = self.df_error_list["車間"]
                raise Error_Workshop
            
            "抓取專案與機台資訊"
            self.df_project_info = self.df_factory_worker_info.iloc[0:4,5:].set_index(5).fillna(method = "ffill",axis = 1) # 填補 nan (excel 合併儲存格，python讀取後只有一格有值，其他為nan)

            if self.df_project_info.loc["專案"].str.split("/").apply(lambda x:any([i not in self.parm_project for i in x])).any(): # 檢查"專案名稱"填寫是否正確
                self.df_error_list = self.df_project_info.loc["專案"][self.df_project_info.loc["專案"].str.split("/").apply(lambda x:any([i not in self.parm_project for i in x]))]
                raise Error_Project
            if ~self.df_project_info.loc["自動機製程段"].astype(str).isin(self.parm_process).all(): # 檢查"製程段"填寫是否正確
                self.df_error_list = self.df_project_info.loc["自動機製程段"][~self.df_project_info.loc["自動機製程段"].astype(str).isin(self.parm_process)].values
                raise Error_Process
            if ~self.df_project_info.loc["Device"].astype(str).isin(self.parm_device).all(): # 檢查"機台名稱"填寫是否正確
                self.df_error_list = self.df_project_info.loc["Device"][~self.df_project_info.loc["Device"].astype(str).isin(self.parm_device)].values
                raise Error_Device
            
            "抓取員工機台經驗資訊"
            self.df_exp = self.df_factory_worker_info.iloc[5:,6:]
            if self.df_exp.isnull().values.any(): # 檢查是否有空值
                self.df_error_list = pd.concat([self.df_worker_info, self.df_exp[self.df_exp.isnull().values]],join ="inner", axis=1)
                raise Error_None
            if ~self.df_exp.astype(str).isin(self.parm_exp).values.all():# 符合 parm_exp
                self.df_error_list = pd.concat([self.df_worker_info, self.df_exp[~self.df_exp.astype(str).isin(self.parm_exp).values]],join ="inner", axis=1)
                raise Error_Exp
            
            for w in range(len(self.df_worker_info)):# 員工數量
                for p in range(len(self.df_project_info.columns)): # 所有專案中機台數量
                     # 逐筆新增
                    self.df_factory_worker_info_convert = self.df_factory_worker_info_convert.append({"worker_id":str(self.df_worker_info["員工工號"].iloc[w]), # str； 員工工號
                                                                                                      "worker_name":str(self.df_worker_info["員工名字"].iloc[w]), # str； 員工名字
                                                                                                      "job":self.df_worker_info["職務"].iloc[w], # int； 員工所屬職位，可用於判斷是否為管理層
                                                                                                      "superior":str(self.df_worker_info["負責人"].iloc[w]), # str； 員工所屬之上級管理人
                                                                                                      "workshop":str(self.df_worker_info["車間"].iloc[w]), # str； 所屬車間
                                                                                                      "project":str(self.df_project_info.loc["專案"].iloc[p]), # str； 所屬專案
                                                                                                      "process":str(self.df_project_info.loc["自動機製程段"].iloc[p]), # str； 所屬專案之製程段
                                                                                                      "device_name":str(self.df_project_info.loc["Device"].iloc[p]), # str； 所屬專案之機台
                                                                                                      "shift":int(self.df_worker_info["班別"].iloc[w]), # int； 排班別
                                                                                                      "level":int(self.df_exp.iloc[w,p]) # int； 員工機台經驗等級
                                                                                                      },ignore_index=1)
            self.df_factory_worker_info_convert["project"] = self.df_factory_worker_info_convert["project"].str.split("/")# project 切分/ ； 各 project 獨立一欄
            self.df_factory_worker_info_convert = self.df_factory_worker_info_convert.explode('project').reset_index(drop = 1)
            
            print("轉換完成")
            return self.df_factory_worker_info_convert # 資料表轉換完成，提供給server做後續匯入動作
        except Error_FileName:
            print("oh oh~ 資料表名稱有誤喔~")
            # 印出有問題資料
            print(raw_excel)
        except Error_FileContent:
            print("oh oh~ 內容可能不是員工資訊表喔~")
        except Error_None:
            print("oh oh~ 員工資訊表中有\"尚未填寫\"的部分喔~")
            print(self.df_error_list)
        except Error_Project:
            print("oh oh~ 員工資訊表中有不存在的\"專案名稱\"，或是不符合格式喔~")
            print(self.df_error_list)
        except Error_Job:
            print("oh oh~ 員工資訊表中有不存在的\"職務\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Superior:
            print("oh oh~ 員工資訊表中有不存在的\"負責人\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Shift:
            print("oh oh~ 員工資訊表中有不存在的\"輪班\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Workshop:
            print("oh oh~ 員工資訊表中有不存在的\"車間\"喔~")
            print(self.df_error_list)
        except Error_Process:
            print("oh oh~ 員工資訊表中有不存在的\"製程段\"喔~")
            print(self.df_error_list)          
        except Error_Device:
            print("oh oh~ 員工資訊表中有不存在的\"機台名稱\"喔~")
            print(self.df_error_list)
        except Error_Exp:
            print("oh oh~ 員工資訊表中有不存在的\"經驗等級\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Exception as e:
            print(e)
            print("oh oh~ 資料表可能有內容不符合相關要求喔~") 
#%%
    """
    專案 Device 事件簿
    """
    # 一次處理一個 Device 事件簿 excel表； e.g. D5X device事件簿.xlsx
    def fn_proj_eventbooks(self,filename:str, raw_excel:bytes): # 輸入資料路徑與名稱；須注意資料名稱格式
        self.df_proj_eventbooks_convert = pd.DataFrame() # 空白資料表，準備儲存使用
        print("轉換中...")
        try:             
            _project_name_ = filename.split("Device")[0].strip(" ") # 抓取 project 檔案名稱；用device去切，注意忽略"空格" 
            if _project_name_ not in [i for i in self.parm_project]: # 檢查資料表名稱 e.g. D5X device事件簿.xlsx 會取得 D5X
                raise Error_Project
            self.df_proj_eventbooks = pd.read_excel(raw_excel, sheet_name=None) # 讀 excel 資料
            _devices_ = list(self.df_proj_eventbooks.keys()) #根據"工作表"名稱抓取 Device 名稱
            if len(set(_devices_).difference(self.parm_device))>0: # 檢查"機台名稱"填寫是否正確
                self.df_error_list = set(_devices_).difference(self.parm_device)
                raise Error_Device
            for j in _devices_: # 依照 device 進行區分
                if ~self.df_proj_eventbooks[j].columns.isin(["Category","MESSAGE","优先顺序"]).all():
                    self.df_error_list = self.df_proj_eventbooks[j].columns
                    value = set(self.df_proj_eventbooks[j].columns).difference(["Category","MESSAGE","优先顺序"])
                    raise Error_FileContent
                _events_ = self.df_proj_eventbooks[j][["Category","MESSAGE","优先顺序"]] # 事件簿使用的資訊欄位；
                if _events_["Category"].isnull().values.any():#donecheck# 檢查 category 欄位是不是有空值
                    self.df_error_list =_events_[_events_["Category"].isnull().values]
                    raise Error_None
                else: # 確定category欄位沒有nan後
                    _events_= _events_[_events_["Category"].astype(str).isin(self.parm_cate)].reset_index(drop = True) # 篩選出含括在 Category 中的項目
                    # 因為不確定有哪一些category，只知道範圍，目前以1~199,300~699篩選；但如果異常事件發生時出現資料表中沒有沒有的項目，需要通知管理層處理:更新資料和派遣(不一定)
                if _events_[["MESSAGE","优先顺序"]].isnull().values.any(): # 最檢查單一機台的資料中是否有空值
                    self.df_error_list = _events_[_events_[["MESSAGE","优先顺序"]].isnull().values]
                    raise Error_None
                else:
                    _events_["project"] = _project_name_.lower() # 新增專案名稱欄位；小寫
                    _events_["Device_Name"] = j.lower() # 新增機台名稱欄位；小寫
                    self.df_proj_eventbooks_convert = self.df_proj_eventbooks_convert.append(_events_, ignore_index=True) # 一筆筆新增
                if ~_events_["优先顺序"].apply(lambda y:isinstance(y,(float,int))).all():# 優先順序範圍需是"數字" 且最大值不大於需要派遣的category種類數 
                    self.df_error_list = _events_[~_events_["优先顺序"].apply(lambda y:isinstance(y,(float,int)))]
                    value = self.df_error_list["优先顺序"]
                    raise Error_FileContent
            print("轉換完成")
        except Error_Project:
            print("oh oh~ "+filename+" 的\"專案名稱\"不存在或輸入有誤喔~")
        except Error_None:
            print("oh oh~ 在",filename,"的 Worksheet:",j,"中有\"尚未填寫\"的部分喔~")
            print(self.df_error_list)
        except Error_Device:
            print("oh oh~ 在",filename,"的 Worksheet:",j,"中，有不存在的\"機台名稱\"喔~")
            print(self.df_error_list)
        except Error_FileContent:
            print("oh oh~ 在",filename,"的 Worksheet:",j,"的內容值可能不對喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Exception as e:
            print(e)
            print("oh oh~ "+_project_name_+"device事件簿可能有內容不符合相關要求喔~")
        return self.df_proj_eventbooks_convert # 資料表轉換完成，提供給server做後續匯入動作
    
#%%    
    """
    車間 layout 座標表
    server 必須要製作機台 id 才可以進行轉換!
    生成車間移動距離表
    """
    # 目前為針對 第九車間 layout 客製化計算，layout 無更動 (僅是換機台名稱、座標值) 則可使用； 無法針對 layout 變動後做計算
    def fn_factorymap(self,raw_excel:bytes):# 輸入車間機台座標資料表，生成簡易移動距離矩陣
        print("轉換中...") 
        self.df_movingMatrix = None #  空白資料表，準備儲存使用
        try:
            self.df_device_xy = pd.read_excel(raw_excel,sheet_name=0) # 讀取車間機台座標表
            if self.df_device_xy[["id","workshop","project","x_axis","y_axis"]].isnull().values.any(): # done # 確認資料表"id","workshop","project","x_axis","y_axis"欄位有無空值
                self.df_error_list = self.df_device_xy[self.df_device_xy[["id","workshop","project","x_axis","y_axis"]].isnull().values]
                raise Error_None
            elif ~self.df_device_xy["x_axis"].apply(lambda x:isinstance(x,(float,int))).all(): # done # 檢查 x axis 座標值是不是整數或浮點數
                self.df_error_list = self.df_device_xy[~self.df_device_xy["x_axis"].apply(lambda x:isinstance(x,(float,int)))]
                value = self.df_error_list["x_axis"]
                raise Error_Axis
            elif ~self.df_device_xy["y_axis"].apply(lambda y:isinstance(y,(float,int))).all(): # done # 檢查 y axis 座標值是不是整數或浮點數
                self.df_error_list = self.df_device_xy[~self.df_device_xy["y_axis"].apply(lambda y:isinstance(y,(float,int)))]
                value = self.df_error_list["y_axis"]
                raise Error_Axis
            elif ~self.df_device_xy["workshop"].isin(self.parm_workshop).all(): # done # 檢查"車間"填寫是否正確
                self.df_error_list = self.df_device_xy[~self.df_device_xy["workshop"].isin(self.parm_workshop)]
                value = self.df_error_list["workshop"].values
                raise Error_Workshop
                
            _devices_ = self.df_device_xy[self.df_device_xy["project"]!="rescue"] # 機台(非消防站)資訊
            if _devices_.isnull().values.any(): # done # 確認所有機台相關欄位無空值
                self.df_error_list = _devices_[_devices_.isnull().values]
                raise Error_None
            elif ~_devices_["project"].isin(self.parm_project).all(): # done # 檢查"專案名稱"填寫是否正確
                self.df_error_list = _devices_[~_devices_["project"].isin(self.parm_project)]
                value = self.df_error_list["project"].values
                raise Error_Project
            elif ~_devices_["process"].isin(self.parm_process).all(): # done # 檢查"製程段"填寫是否正確
                self.df_error_list = _devices_[~_devices_["process"].isin(self.parm_process)]
                value = self.df_error_list["process"].values
                raise Error_Process
            elif ~_devices_["line"].apply(lambda l:isinstance(l,(float,int))).all(): # done # 檢查"線段"填寫是否正確
                self.df_error_list = _devices_[~_devices_["line"].apply(lambda l:isinstance(l,(float,int)))]
                value = self.df_error_list["line"].values
                raise Error_Line
            elif ~_devices_["device_name"].isin(self.parm_device).all(): # done # 檢查"機台名稱"填寫是否正確
                self.df_error_list = _devices_[~_devices_["device_name"].isin(self.parm_device)]
                value = self.df_error_list["device_name"].values
                raise Error_Device          
            if ~_devices_["sop_link"].apply(lambda s:validators.url(s)).all():
                self.df_error_list = _devices_[_devices_["sop_link"].apply(lambda s:bool(validators.url(s)))==False]
                value  =  self.df_error_list["sop_link"]
                raise Error_SOP

            # 根據資料表所有的"id"，製作對稱矩陣
            self.df_movingMatrix = pd.DataFrame(index = self.df_device_xy["id"], columns=self.df_device_xy["id"]) # 建立空對稱矩陣，用於儲存計算後的機台間移動距離
            "試算距離 Manhattan Distance"
            for i in range(len(self.df_device_xy)):      
                From_device = self.df_device_xy.iloc[i] # 起點 device
                for j in range(i,len(self.df_device_xy)):
                    To_device = self.df_device_xy.iloc[j] # 終點device
                    "相關判斷"
                    if From_device["process"] != To_device["process"]: # 判斷兩device 是否屬於相同製程(process)
                        dis_cal =sum(abs(To_device[["x_axis","y_axis"]]-From_device[["x_axis","y_axis"]])) # 屬於不同製程，直接計算 Manhattan Distance
                    else:# 如果是同製程       
                        #檢查在當前(M1或M3)製程中，有沒有其他device(障礙物)的y座標位於這兩個device的y座標之間
                        if self.df_device_xy[self.df_device_xy["process"]==From_device["process"]]["y_axis"].between(min(From_device["y_axis"],To_device["y_axis"]),max(From_device["y_axis"],To_device["y_axis"]),inclusive="neither").any():
                            if From_device["process"] in ["M1段","M2段"]: # 判斷製程是M1或M2
                                to_aisle = 1.0 #最邊緣兩測的device中心點，到走道的來回距離(因為有一開始從邊緣device到走道的距離和後面從走道到邊緣device的距離，所以是0.5*2)
                            else:
                                if To_device["project"].lower() in ["n84"]:# 判斷是否是在M3製程中的n84機種
                                    to_aisle = 0.5 # 0.25*2
                                else:
                                    to_aisle = 1.0
                            # 找到起始device(From_device)那一條產線最左邊與最右邊的device座標
                            From_left = self.df_device_xy.iloc[self.df_device_xy[(self.df_device_xy["process"]==From_device["process"])&(self.df_device_xy["project"]==From_device["project"])]["x_axis"].idxmin()]
                            From_right = self.df_device_xy.iloc[self.df_device_xy[(self.df_device_xy["process"]==From_device["process"])&(self.df_device_xy["project"]==From_device["project"])]["x_axis"].idxmax()]
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
        
        except Error_None:
            print("oh oh~ 車間layout座標表中有\"尚未填寫\"的部分喔~")
            print(self.df_error_list)
        except Error_FileContent as e:
            print("oh oh~ 車間layout座標表的內容值可能不對喔~")
            print(self.df_error_list),print(e)
        except Error_Workshop:
            print("oh oh~ 車間layout座標表中有不存在的\"車間\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Project:
            print("oh oh~ 車間layout座標表中有不存在的\"專案名稱\"，或是不符合格式喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Device:
            print("oh oh~ 車間layout座標表中，有不存在的\"機台名稱\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Process:
            print("oh oh~ 車間layout座標表中有不存在的\"製程段\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Line:
            print("oh oh~ 車間layout座標表中有不存在的\"線段\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Device:
            print("oh oh~ 車間layout座標表中有不存在的\"機台名稱\"喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_Axis:
            print("oh oh~ 車間layout座標表中的\"座標\"填寫有誤喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Error_SOP:
            print("oh oh~ 車間layout座標表中的\"SOP link\"填寫有誤喔~")
            print(self.df_error_list),print("錯誤值:\n",value)
        except Exception as e:
            print(e)
            print("oh oh~ 車間layout座標表可能有內容不符合相關要求喔~") 
        return self.df_movingMatrix # 回傳計算完的機台間移動距離矩陣表        
#%%
"""測試派工系統"""
# test_dispatch = Foxlink_dispatch() # 建立物件

#%%
"""測試資料匯入"""
# test_data_import = data_convert() # 建立物件

# '測試員工資訊表 轉換'
# test_file_path_workerinfo = "test_data/車間員工資訊表_公版_TEST用.xlsx" # 資料路徑
# test_workerinfo = test_data_import.fn_factory_worker_info(test_file_path_workerinfo)

# '測試機種事件簿 轉換'
# test_file_path_eventbook = "test_data/D5X Device 事件簿[修正].xlsx" # 資料路徑
# test_file_path_eventbook = "test_data/N104 Device 事件簿.xlsx" # 資料路徑
# test_file_path_eventbook = "test_data/Z104 Device 事件簿_[不存在專案].xlsx" # 資料路徑
# test_file_path_eventbook = "test_data/N84 Device 事件簿.xls" # 資料路徑
# test_eventbook = test_data_import.fn_proj_eventbooks(test_file_path_eventbook.split("/")[-1].strip(".xlsx"),test_file_path_eventbook)

# '測試機台座標表 計算移動距離矩陣'
# test_file_path_layout = "../#原始資料/車間 Layout 座標表_公版_TEST用.xlsx" # 資料路徑
# test_moving_matrix = test_data_import.fn_factorymap(test_file_path_layout)
        
#%%
# df_test = pd.read_excel("test_data/車間員工資訊表_公版.xlsx", sheet_name = 0, header = None)
# df_test_worker = df_test.iloc[5:,0:6].rename(columns = df_test.iloc[4,0:6])       
# print(df_test_worker[df_test_worker.isnull().values])
# test_eventbook.to_excel("test.xlsx")
        
        
        
        
        
        
        
        
        