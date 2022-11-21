import datetime
from paho.mqtt import client
import json
import logging
from app.log import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

class MQTT_Client:

    def __init__(self):
        self.mqtt_client: client.Client = None

    async def connect(self, broker:str, port:int, client_id:str):
        """連線到MQTT broker
        Args:
        - broker: MQTT broker URI
        - port: MQTT broker port
        - client_id: MQTT client ID
        """
        self.mqtt_client = client.Client(client_id)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.connect(broker, port=port)
        self.mqtt_client.loop_start()  
    
    async def disconnect(self):
        """關閉MQTT連線"""
        if self.mqtt_client is not None:
            self.mqtt_client.disconnect()
    
    def publish(self,topic: str, payload, qos: int = 0, retain: bool = False) -> bool:
        """發送訊息到MQTT broker
        Args:
        - topic: 訊息主題
        - payload: 訊息內容
        - qos: 訊息優先度
        - retain: 是否保留訊息
        """
        if self.mqtt_client is None:
            raise Exception("MQTT client is not initialized")

        json_str = json.dumps(payload, default=self.serializer)
        result = self.mqtt_client.publish(topic, payload=json_str, qos=qos, retain=retain)
        # if result[0] is 0, then publish successfully
        return result[0] == 0

    ####### TOOLS ########
    def serializer(self,obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()

    def on_connect(self, c, user_data, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error("Failed to connect to MQTT, returnee code: ", rc)


        
mqtt_client = MQTT_Client()