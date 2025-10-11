from fastapi import WebSocket
from typing import Dict, List
import json

class ConnectionManager:
    def __init__(self):
        self.driver_connections: Dict[int, WebSocket] = {}
        self.rider_connections: Dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_type: str, client_id: int):
        await websocket.accept()
        if client_type == "driver":
            self.driver_connections[client_id] = websocket
        elif client_type == "rider":
            self.rider_connections[client_id] = websocket

    def disconnect(self, client_type: str, client_id: int):
        if client_type == "driver" and client_id in self.driver_connections:
            del self.driver_connections[client_id]
        elif client_type == "rider" and client_id in self.rider_connections:
            del self.rider_connections[client_id]

    async def broadcast_to_drivers(self, message: dict):
        for connection in self.driver_connections.values():
            await connection.send_text(json.dumps(message))
            
    async def send_to_rider(self, rider_id: int, message: dict):
        if rider_id in self.rider_connections:
            websocket = self.rider_connections[rider_id]
            await websocket.send_text(json.dumps(message))