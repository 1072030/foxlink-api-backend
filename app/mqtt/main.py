from paho.mqtt import client
import logging
import json


mqtt_client: client


def connect_mqtt(broker: str, port: int, client_id: str):
    def on_connect(c, user_data, flags, rc):
        if rc == 0:
            logging.log("Connected to MQTT broker")
        else:
            logging.error("Failed to connect to MQTT, returnee code: ", rc)

    mqtt_client = client.Client(client_id)
    mqtt_client.on_connect = on_connect
    mqtt_client.connect(broker, port=port)


def disconnect_mqtt():
    if mqtt_client is not None:
        mqtt_client.disconnect()


def publish(topic: str, payload, qos: int = 0, retain: bool = False) -> bool:
    if mqtt_client is None:
        raise Exception("MQTT client is not initialized")

    json_str = json.dumps(payload)
    result = mqtt_client.publish(topic, payload=json_str, qos=qos, retain=retain)
    # if result[0] is 0, then publish successfully
    return result[0] == 0
