import asyncio
import websockets
import json
import sys

async def rider_logic(rider_id: int):
    uri = f"ws://127.0.0.1:8000/ws/rider/{rider_id}"
    # Use ping_interval=None to avoid timeouts during testing
    async with websockets.connect(uri, ping_interval=None) as websocket:
        print(f"--- Rider App (ID: {rider_id}) ---")
        print(f"Connected to server.")
        
        try:
            start_zone = int(input("Enter your current zone (e.g., 2): "))
            drop_zone = int(input("Enter your destination zone (e.g., 5): "))

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
        except Exception as e:
            print(f"Error or Disconnect: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clients/rider_client.py <rider_id>")
    else:
        asyncio.run(rider_logic(int(sys.argv[1])))