import asyncio
import websockets
import json
import sys

# --- UPGRADED DRIVER CLIENT ---

async def handle_user_input(websocket):
    """Handles user input to accept Normal Rides OR Pooled Rides."""
    loop = asyncio.get_event_loop()
    while True:
        # Read input in a way that doesn't block the websocket loop
        user_input = await loop.run_in_executor(None, sys.stdin.readline)
        parts = user_input.strip().split()
        
        if not parts:
            continue

        command = parts[0].lower()

        # 1. Normal Ride Acceptance
        if command == "accept" and len(parts) == 2:
            try:
                ride_id = int(parts[1])
                await websocket.send(json.dumps({"action": "accept_ride", "ride_id": ride_id}))
                print(f"Sent request to accept NORMAL ride {ride_id}.")
            except ValueError:
                print("Invalid ID format.")

        # 2. Pooled Ride Acceptance (The New Feature)
        elif command == "pool" and len(parts) == 2:
            try:
                pooled_id = int(parts[1])
                await websocket.send(json.dumps({"action": "accept_pooled", "pooled_id": pooled_id}))
                print(f"Sent request to accept POOLED ride {pooled_id}.")
            except ValueError:
                print("Invalid ID format.")

        # 3. Complete Ride
        elif command == "complete" and len(parts) == 2:
            try:
                ride_id = int(parts[1])
                await websocket.send(json.dumps({"action": "complete_ride", "ride_id": ride_id}))
                print(f"Sent request to complete ride {ride_id}.")
            except ValueError:
                print("Invalid ID format.")

        else:
            print("Commands:")
            print("  accept <id>  -> Accept a normal single ride")
            print("  pool <id>    -> Accept a shared carpool ride")
            print("  complete <id> -> Finish a ride")

async def driver_logic(driver_id: int):
    uri = f"ws://127.0.0.1:8000/ws/driver/{driver_id}"
    async with websockets.connect(uri, ping_interval=None) as websocket:
        print(f"--- Upgraded Driver App (ID: {driver_id}) ---")
        print(f"Connected. Ready for Normal and Pooled rides.")
        
        # Start the input listener in the background
        asyncio.create_task(handle_user_input(websocket))
        
        while True:
            try:
                message = await websocket.recv()
                data = json.loads(message)
                
                print(f"\n--- Server Message ---")
                if data.get("type") == "new_ride":
                    print(f"🔔 NORMAL RIDE Available! ID: {data['ride_id']}")
                    print(f"   From: {data['start_zone']} -> To: {data['drop_zone']}")
                
                elif data.get("type") == "ride_taken":
                    print(f"ℹ️ Ride {data['ride_id']} taken by Driver {data['accepted_by_driver_id']}.")
                
                elif data.get("type") == "info":
                     print(f"INFO: {data['message']}")
                
                elif data.get("type") == "error":
                    print(f"❌ ERROR: {data['message']}")
                
                print("----------------------")
            except websockets.exceptions.ConnectionClosed:
                print("Server disconnected. Please restart the driver app.")
                break

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clients/driver_client.py <driver_id>")
    else:
        asyncio.run(driver_logic(int(sys.argv[1])))