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
- foxlink/mission/rejected - 當有任務被拒絕超過兩次，會觸發這一事件