import asyncio
import websockets
import json
import sys

async def rider_logic(rider_id: int):
    uri = f"ws://127.0.0.1:8000/ws/rider/{rider_id}"
    # This line includes the fix to prevent timeout errors
    async with websockets.connect(uri, ping_interval=None) as websocket:
        print(f"--- Rider App (ID: {rider_id}) ---")
        print(f"Connected to server on port {websocket.local_address[1]}.")
        
        start_zone = int(input("Enter your current zone (e.g., a number from 1-20): "))
        drop_zone = int(input("Enter your destination zone (e.g., a number from 1-20): "))

        await websocket.send(json.dumps({
            "action": "request_ride",
            "start_zone": start_zone,
            "drop_zone": drop_zone
        }))
        
        print("\nListening for driver assignment...")
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            if data.get("type") == "info":
                print(f"[SERVER]: {data['message']}")
            elif data.get("type") == "driver_assigned":
                print(f"\n[SUCCESS]: Driver {data['driver_name']} has been assigned!")
                print(f"They will arrive in approximately {data['arrival_time_minutes']} minutes.")
            elif data.get("type") == "ride_completed":
                print(f"\n[SERVER]: {data['message']}")
                break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clients/rider_client.py <rider_id>")
    else:
        try:
            
            asyncio.run(rider_logic(int(sys.argv[1])))
        except Exception as e:
            print(f"An error occurred: {e}")