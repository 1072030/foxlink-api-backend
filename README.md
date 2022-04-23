# Foxlink API Backend

## Prerequisite
1. Python 3.8+
2. Docker
3. Mypy linter (Recommend, for development use)

## How to Start?
1. Login ghcr.io via `docker login ghcr.io` command.
    - How to get your own github token please see this [topic](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
2. Edit configuration in **docker-compose.yml** (Optional)
2. In CLI, enter `docker-compose up -d` to start up services.

# MQTT Topics
- foxlink/users/{username}/missions - 當用戶受指派新任務，會觸發這一事件
範例：
```jsonc
{
  "type" : "new", // 該事件的類別：new 為新增任務
  "mission_id" : 12, // 新增任務的 ID
  "device" : {
    "project" : "n104",
    "process" : "M3段",
    "line" : 4,
    "name" : "Device_11"
  },
  "name": "任務名稱",
  "description": "任務的敘述",
  "events": [
    "category" : 190, // 該故障的分類編號
    "message" : "进料打码站故障", // 故障資訊
    "done_verified" : false, // 該故障是否維修完畢
    "event_start_date" : "2022-04-23T07:09:22", // 該故障出現時間
    "event_end_date" : null
  ]
}
```
- foxlink/mission/rejected - 當有任務被拒絕超過兩次，會觸發這一事件
範例：
```jsonc
{
    "id": 1, // 被拒絕超過兩次的任務 ID
    "worker": "string", // 員工姓名
    "rejected_count": 2 // 該任務總共被拒絕了幾次
}
```
- foxlink/no-available-worker - 當有任務無人可以指派時，會推送這個訊息
```jsonc
{
  "mission_id" : 1, // 無人可供指派的任務 ID
  // Device 詳細資訊
  "device" : {
    "device_id" : "D53@1@Device_9",
    "device_name" : "Device_9",
    "project" : "D53",
    "process" : "M3段",
    "line" : 1
  },
  "name" : "D53@1@Device_9 故障", // 任務名稱
  "description" : "", // 該任務的敘述
  "assignees" : [ ],
  // 該任務的 Device 所受影響的故障列表
  "events" : [ {
    "category" : 190,
    "message" : "进料打码站故障",
    "done_verified" : false, // 該故障是否維修完畢
    "event_start_date" : "2022-04-23T07:09:22", // 該故障出現時間
    "event_end_date" : null
  } ],
  "is_started" : false,
  "is_closed" : false,
  "created_date" : "2022-04-23T07:12:31",
  "updated_date" : "2022-04-23T07:12:31"
}
```
- foxlink/users/{username}/subordinate-rejected - 當天如果有下屬拒絕任務兩次以上，就會推送這則訊息
```jsonc
{
    "subordinate_id": '145287', // 下屬的 ID
    "subordinate_name": 'string', // 下屬姓名
    "total_rejected_count": 2 // 下屬當日總拒絕次數
}
```
- foxlink/overtime-workers - 如果有員工超過上班時間（例如早班員工到了晚班時段還在處理任務），就會推送這則訊息
```jsonc
[
  {
    "worker_id": '145287', // 員工的 ID
    "worker_name": 'string', // 員工姓名
    "working_on_mission": {
      "mission_id": 0, // Mission ID
      "mission_name": "string", // 任務名稱
      "device_id": "string", // 機台的 ID
      "mission_start_date": "2022-03-17T08:19:07.169" // 任務創建的時間 (UTC Time)
    }
  }
]
```
- foxlink/users/{username}/move-rescue-station - 當員工閒置於機台超過特定時間時，系統將會通知員工移動至最近的維修站。
```jsonc
{
  "rescue_id": "rescue@第九車間@1", // 要前往的維修站 ID
}
```
- foxlink/users/{username}/worker-unusual-offline - 當員工異常離線時（網路不佳），超過某特定時間，將會通知該員工上級。
```jsonc
{
  "worker_id": "rescue@第九車間@1", // 異常離線的員工 ID
  "worker_name": "string", // 員工姓名
}
```

# Server Config
Config Name                 | Description                                                                                                                 | Default Value | Example Value
----------------------------|-----------------------------------------------------------------------------------------------------------------------------|---------------|--------------
DATABASE_HOST               | Database host                                                                                                               | localhost     | 127.0.0.1
DATABASE_PORT               | Database port                                                                                                               | None          | 3306
DATABASE_USER               | Database user                                                                                                               | None          | root
DATABASE_PASSWORD           | Database password                                                                                                           | None          | None
FOXLINK_DB_HOST             | Foxlink Db's host                                                                                                           | None          | 127.0.0.1
FOXLINK_DB_PORT             | Foxlink Db's port                                                                                                           | None          | 3306
FOXLINK_DB_USER             | Foxlink Db's user                                                                                                           | None          | foxlink
FOXLINK_DB_PASSWORD         | Foxlink Db's password                                                                                                       | None          | foxlink
JWT_SECRET                  | JWT secret.                                                                                                                 | secret        | secret
MQTT_BROKER                 | IP address of MQTT broker                                                                                                   | None          | 127.0.0.1
MQTT_PORT                   | MQTT Broker's Port                                                                                                          | 1883          | 1883
EMQX_USERNAME               | EMQX username                                                                                                               | admin         | admin
EMQX_PASSWORD               | EMQX password                                                                                                               | public        | public
WORKER_REJECT_AMOUNT_NOTIFY | Minimum notify threshold a worker rejects missions in a day                                                                 | 2             | 2
MISSION_REJECT_AMOUT_NOTIFY | Minimum notify threshold that a mission is being rejected                                                                   | 2             | 2
DAY_SHIFT_BEGIN             | Day shift begin time (UTC Time)                                                                                             | 07:40         | 07:40
DAY_SHIFT_END               | Day shift end time (UTC Time)                                                                                               | 19:40         | 19:40
MAX_NOT_ALIVE_TIME          | Maximun time that a worker's application is not alive (in minutes)                                                          | 5             | 5
MOVE_TO_RESCUE_STATION_TIME | Maximun time that a worker can idle at a device. When time's out, worker will be notified to move to nearest rescue station | 5             | 5

# Related Infos
- NTUST MQTT Broker: 140.118.157.9:27010
- Foxlink online API docs: http://140.118.157.9:8080/docs
- Default admin login credential:
  - username: admin
  - password: foxlink
