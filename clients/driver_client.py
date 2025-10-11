import asyncio
import websockets
import json
import sys

async def handle_user_input(websocket):
    """Handles user input in a separate thread to not block WebSocket listening."""
    loop = asyncio.get_event_loop()
    while True:
        user_input = await loop.run_in_executor(None, sys.stdin.readline)
        parts = user_input.strip().split()
        
        if len(parts) == 2 and parts[0].lower() == "accept":
            try:
                ride_id = int(parts[1])
                await websocket.send(json.dumps({"action": "accept_ride", "ride_id": ride_id}))
                print(f"Sent request to accept ride {ride_id}.")
            except ValueError:
                print("Invalid ride ID. Please use the format: accept <ride_id>")

        elif len(parts) == 2 and parts[0].lower() == "complete":
            try:
                ride_id = int(parts[1])
                await websocket.send(json.dumps({"action": "complete_ride", "ride_id": ride_id}))
                print(f"Sent request to complete ride {ride_id}.")
            except ValueError:
                print("Invalid ride ID. Please use the format: complete <ride_id>")
        else:
            print("Invalid command. Use 'accept <id>' or 'complete <id>'.")

async def driver_logic(driver_id: int):
    uri = f"ws://127.0.0.1:8000/ws/driver/{driver_id}"
    async with websockets.connect(uri, ping_interval=None) as websocket:
        print(f"--- Driver App (ID: {driver_id}) ---")
        print(f"Connected to server on port {websocket.local_address[1]}. Waiting for rides...")
        print("To accept a ride, type 'accept <ride_id>' and press Enter.")
        
        input_task = asyncio.create_task(handle_user_input(websocket))
        
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            print(f"\n--- New Notification ---")
            if data.get("type") == "new_ride":
                print(f"Ride Available! ID: {data['ride_id']}")
                print(f"From Zone: {data['start_zone']} -> To Zone: {data['drop_zone']}")
            elif data.get("type") == "ride_taken":
                print(f"Ride {data['ride_id']} has been taken by Driver {data['accepted_by_driver_id']}.")
            elif data.get("type") == "info":
                 print(f"[SERVER]: {data['message']}")
            elif data.get("type") == "error":
                print(f"[ERROR]: {data['message']}")
            print("----------------------")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clients/driver_client.py <driver_id>")
    else:
        asyncio.run(driver_logic(int(sys.argv[1])))