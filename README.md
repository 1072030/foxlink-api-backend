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
  "description": "任務的敘述，目前是放故障的問題原因"
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
  "mission_id" : 12, // 沒有人可以指派的任務 ID
  "device_id": "string", // DeviceID
  "description": "string" // 任務的敘述，目前是放故障的問題原因
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

# Related Infos
- NTUST MQTT Broker: 140.118.157.9:27010
- Foxlink online API docs: http://140.118.157.9:8080/docs
- Default admin login credential:
  - username: admin
  - password: foxlink
