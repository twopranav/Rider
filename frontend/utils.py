import requests
import json
import websockets
import asyncio

API_URL = "http://localhost:8000"  # your FastAPI backend

# -------- HTTP WRAPPERS --------
def post(path, data):
    resp = requests.post(f"{API_URL}{path}", json=data)
    return resp.json()

def get(path):
    resp = requests.get(f"{API_URL}{path}")
    return resp.json()

# -------- WEBSOCKET WRAPPER --------
async def ws_listen(url, callback):
    async with websockets.connect(url) as ws:
        while True:
            msg = await ws.recv()
            callback(json.loads(msg))
