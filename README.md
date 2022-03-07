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
{"type": "new", "mission_id": 12, "device": {"project": "n104", "process": "M3段", "line": 4, "name": "Device_11"}}
```
- foxlink/mission/rejected - 當有任務被拒絕超過兩次，會觸發這一事件
範例：
```jsonc
{"id": "任務的 ID", "worker": "員工姓名", "rejected_count": "該任務總拒絕次數"}}
```
- foxlink/messages - 發送相關重要錯誤訊息。下為範例，當沒有可指派的員工時：
```jsonc
{"type": "error", "message": "no worker available to fix devices"}
```
