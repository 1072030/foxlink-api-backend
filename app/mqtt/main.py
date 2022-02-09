from paho.mqtt import client as mqtt_client
from app.env import MQTT_PORT, MQTT_BROKER
import json


def connect_mqtt(broker: str, port: int, client_id: str):
    def on_connect(client, user_data, flags, rc):
        if rc == 0:
            print("Connected to MQTT broker")
        else:
            print("Failed to connect to MQTT, returnee code: ", rc)

    c = mqtt_client.Client(client_id, protocol=mqtt_client.MQTTv5)
    c.on_connect = on_connect
    c.connect(broker, port=port)

    return c


client = connect_mqtt(MQTT_BROKER, MQTT_PORT, "foxlink_api_server")


def publish(topic: str, payload, qos: int = 0) -> bool:
    if client is None:
        raise Exception("MQTT client is not initialized")

    json_str = json.dumps(payload)
    result = client.publish(topic, payload=json_str, qos=qos)
    # if result[0] is 0, then publish successfully
    return result[0] == 0
