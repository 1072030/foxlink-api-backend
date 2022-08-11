import datetime
from paho.mqtt import client
import json
import logging
from app.my_log_conf import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)
mqtt_client: client.Client


def connect_mqtt(broker: str, port: int, client_id: str):
    """連線到MQTT broker

    Args:
    - broker: MQTT broker URI
    - port: MQTT broker port
    - client_id: MQTT client ID
    """
    def on_connect(c, user_data, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error("Failed to connect to MQTT, returnee code: ", rc)

    global mqtt_client
    mqtt_client = client.Client(client_id)
    mqtt_client.on_connect = on_connect
    mqtt_client.connect(broker, port=port)
    mqtt_client.loop_start()


def disconnect_mqtt():
    """關閉MQTT連線"""
    if mqtt_client is not None:
        mqtt_client.disconnect()

def default(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()


def publish(topic: str, payload, qos: int = 0, retain: bool = False) -> bool:
    """發送訊息到MQTT broker

    Args:
    - topic: 訊息主題
    - payload: 訊息內容
    - qos: 訊息優先度
    - retain: 是否保留訊息
    """
    if mqtt_client is None:
        raise Exception("MQTT client is not initialized")

    json_str = json.dumps(payload, default=default)
    result = mqtt_client.publish(topic, payload=json_str, qos=qos, retain=retain)
    # if result[0] is 0, then publish successfully
    return result[0] == 0
