import asyncio
import httpx
import uuid
from datetime import datetime
from fastapi import FastAPI, status
from pydantic import BaseModel

# --- Configuration ---
# The port this client will run on to accept requests from the interface
CLIENT_PORT = 8080

# The full URL of your main server's endpoint (from your provided code)
MAIN_SERVER_URL = "http://localhost:8001/rides"

# --- Pydantic model for incoming data (should match your server's expectations) ---
class RideRequestClient(BaseModel):
    user_id: str
    source_location: int
    destination_location: int

# --- In-memory async queue to hold incoming ride requests ---
ride_request_queue = asyncio.Queue()

# --- FastAPI App Definition ---
app = FastAPI(
    title="Ride Request Queuing Service",
    description="Accepts ride requests and forwards them to the main server in a FCFS queue.",
)

async def queue_processor():
    """
    This function runs as a background task.
    It continuously watches the queue and sends requests to the main server one by one.
    """
    print("🚀 Queue processor background task started. Waiting for requests...")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                request_to_process = await ride_request_queue.get()
                
                request_id = request_to_process.get('request_id', 'N/A')
                print(f"\n⚙️  Processing request {request_id} from the queue...")
                print(f"  - Forwarding to main server at {MAIN_SERVER_URL}")

                try:
                    # Send the request to your actual server asynchronously
                    response = await client.post(MAIN_SERVER_URL, json=request_to_process, timeout=15.0)
                    
                    response.raise_for_status() # Raises an exception for 4xx or 5xx status codes
                    
                    print(f"  - ✅ Successfully processed by main server. Response: {response.json()}")

                except httpx.HTTPStatusError as e:
                    print(f"  - ⚠️  Main server responded with an error: {e.response.status_code} | Body: {e.response.text}")
                except httpx.RequestError as e:
                    print(f"  - ❌ CRITICAL: Could not connect to the main server. Error: {e}")
                
                finally:
                    ride_request_queue.task_done()

            except Exception as e:
                print(f"An unexpected error occurred in the queue processor: {e}")


@app.on_event("startup")
async def startup_event():
    # On application startup, create the background task for the queue processor.
    asyncio.create_task(queue_processor())


@app.post("/request-ride", status_code=status.HTTP_202_ACCEPTED)
async def receive_ride_request(ride: RideRequestClient):
    """
    This endpoint is called by the requester's interface.
    It accepts a ride request and puts it into the async queue.
    """
    ride_data = ride.dict()
    
    ride_data['request_id'] = str(uuid.uuid4())
    ride_data['queued_at'] = datetime.now().isoformat()
    
    await ride_request_queue.put(ride_data)
    
    print(f"✅ Request {ride_data['request_id']} received and added to queue. Queue size: {ride_request_queue.qsize()}")

    return {
        "message": "Ride request has been accepted and is queued for processing.",
        "request_id": ride_data['request_id']
    }

if __name__ == "__main__":
    import uvicorn
    print(f"Starting client-side queue server on http://localhost:{CLIENT_PORT}")
    uvicorn.run(app, host="127.0.0.1", port=CLIENT_PORT)
