
import uuid
import json

import asyncio
import datetime
from paho.mqtt import client
from app.env import MQTT_BROKER, MQTT_PORT
from app.log import logging

logger = logging.getLogger("mqtt-client")


class MQTT_Client:

    def __init__(self, client_id, broker, port):
        self.mqtt_client = client.Client(client_id)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.broker = broker
        self.port = port
        self.connected = False

    async def connect(self):
        """連線到MQTT broker
        Args:
        - broker: MQTT broker URI
        - port: MQTT broker port
        - client_id: MQTT client ID
        """
        self.mqtt_client.loop_stop()
        self.mqtt_client.connect_async(self.broker, port=self.port,)
        self.mqtt_client.loop_start()
        try:
            await asyncio.wait_for(self.check_status(True), timeout=10)
        except TimeoutError as e:
            logger.error(f'Connection timeout! Failed to connect to Broker:{self.broker}:{self.port}')
            raise TimeoutError("cannot connect to mqtt")

    async def check_status(self, desire):
        while not self.status() == desire:
            await asyncio.sleep(1)

    async def disconnect(self):
        """關閉MQTT連線"""
        if self.mqtt_client is not None:
            self.mqtt_client.disconnect()

        try:
            await asyncio.wait_for(self.check_status(False), timeout=10)
        except TimeoutError as e:
            logger.error(f'Connection timeout! Failed to disconnect from Broker:{self.broker}:{self.port}')
            raise TimeoutError("cannot disconnect from mqtt")

    async def publish(self, topic: str, payload, qos: int = 0, retain: bool = False) -> bool:
        """發送訊息到MQTT broker
        Args:
        - topic: 訊息主題
        - payload: 訊息內容
        - qos: 訊息優先度
        - retain: 是否保留訊息
        """
        if not self.connected:
            await self.connect()

        json_str = json.dumps(payload, default=self.serializer)

        result = self.mqtt_client.publish(topic, payload=json_str, qos=qos, retain=retain)

        # if result[0] is 0, then publish successfully
        return result[0] == 0

    ####### TOOLS ########
    def serializer(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()

    def on_connect(self, c, user_data, flags, rc):
        if (rc == 0):
            logger.info(f"Connection successful: @{self.broker}:{self.port}")
            self.connected = True
        elif (rc == 1):
            logger.warn("Connection refused - incorrect protocol version")
        elif (rc == 2):
            logger.warn("Connection refused - invalid client identifier")
        elif (rc == 3):
            logger.warn("Connection refused - server unavailable")
        elif (rc == 4):
            logger.warn("Connection refused - bad username or password")
        elif (rc == 5):
            logger.warn("Connection refused - not authorised")
        else:
            logger.error("Connection refused - unknown error.")

    def on_disconnect(self, client, userdata, rc):
        if rc == 0:
            logger.info("Disconnect successful")
        else:
            logger.error("Disconnect - unknown error.")
        self.connected = False

    def status(self):
        return self.connected


mqtt_client = MQTT_Client(str(uuid.uuid4()), MQTT_BROKER, MQTT_PORT)
