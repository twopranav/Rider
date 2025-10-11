from fastapi import FastAPI, WebSocket, Depends, WebSocketDisconnect, HTTPException
from sqlalchemy.orm import Session
import json
from .server import models, schemas
from .server.database import engine, get_db, SessionLocal
from .server.connection_manager import ConnectionManager

# This command creates all the tables if they don't exist
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Zoned Ride-Hailing System")
manager = ConnectionManager()

def calculate_time(zone1: int, zone2: int) -> int:
    """Calculates travel time based on the distance between zones."""
    return abs(zone1 - zone2) * 5  # Assume 5 minutes per zone difference

# --- WebSocket Endpoints ---

@app.websocket("/ws/rider/{rider_id}")
async def rider_websocket(websocket: WebSocket, rider_id: int):
    """Handles WebSocket connections for riders to request rides and receive updates."""
    await manager.connect(websocket, "rider", rider_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            if payload["action"] == "request_ride":
                # Create a new, fresh database session for this specific task
                db = SessionLocal()
                try:
                    # Add ride to DB with 'waiting' status
                    ride = models.Ride(
                        client_id=rider_id,
                        start_zone=payload["start_zone"],
                        drop_zone=payload["drop_zone"],
                        status='waiting'
                    )
                    db.add(ride)
                    db.commit()
                    db.refresh(ride)

                    # Notify all drivers of the new ride request
                    notification = {
                        "type": "new_ride",
                        "ride_id": ride.id,
                        "start_zone": ride.start_zone,
                        "drop_zone": ride.drop_zone
                    }
                    await manager.broadcast_to_drivers(notification)
                    await manager.send_to_rider(rider_id, {"type": "info", "message": "Ride requested. Searching for drivers..."})
                finally:
                    # IMPORTANT: Always close the session after the task is done
                    db.close()

    except WebSocketDisconnect:
        manager.disconnect("rider", rider_id)
        print(f"Rider {rider_id} disconnected.")

@app.websocket("/ws/driver/{driver_id}")
async def driver_websocket(websocket: WebSocket, driver_id: int, db: Session = Depends(get_db)):
    """Handles WebSocket connections for drivers to receive notifications and accept/complete rides."""
    await manager.connect(websocket, "driver", driver_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            if payload["action"] == "accept_ride":
                ride_id = payload["ride_id"]
                ride = db.query(models.Ride).filter(models.Ride.id == ride_id, models.Ride.status == 'waiting').first()
                driver = db.query(models.Driver).filter(models.Driver.id == driver_id).first()

                if ride and driver and driver.status == 'available':
                    ride.driver_id = driver_id
                    ride.status = 'assigned'
                    driver.status = 'busy'
                    db.commit()

                    time_to_arrive = calculate_time(driver.current_zone, ride.start_zone)
                    rider_notification = {
                        "type": "driver_assigned",
                        "driver_name": driver.name,
                        "arrival_time_minutes": time_to_arrive
                    }
                    await manager.send_to_rider(ride.client_id, rider_notification)

                    driver_notification = {
                        "type": "ride_taken",
                        "ride_id": ride.id,
                        "accepted_by_driver_id": driver_id
                    }
                    await manager.broadcast_to_drivers(driver_notification)
                else:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Ride could not be accepted."}))

            elif payload["action"] == "complete_ride":
                ride_id = payload["ride_id"]
                ride = db.query(models.Ride).filter(models.Ride.id == ride_id, models.Ride.driver_id == driver_id).first()
                driver = db.query(models.Driver).filter(models.Driver.id == driver_id).first()

                if ride and driver:
                    ride.status = 'completed'
                    driver.status = 'available'
                    driver.current_zone = ride.drop_zone
                    db.commit()

                    rider_notification = {"type": "ride_completed", "message": "Your ride is complete. Thank you!"}
                    await manager.send_to_rider(ride.client_id, rider_notification)

                    driver_notification = {"type": "info", "message": f"Ride {ride.id} completed. Your new zone is {driver.current_zone} and you are now available."}
                    await websocket.send_text(json.dumps(driver_notification))

    except WebSocketDisconnect:
        manager.disconnect("driver", driver_id)
        db.query(models.Driver).filter(models.Driver.id == driver_id).update({"status": "available"})
        db.commit()
        print(f"Driver {driver_id} disconnected and set to available.")

# --- REST Endpoints ---
@app.post("/clients/register", response_model=schemas.Client)
def register_client(client: schemas.ClientCreate, db: Session = Depends(get_db)):
    db_client = models.Client(**client.dict())
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client

@app.post("/drivers/register", response_model=schemas.Driver)
def register_driver(driver: schemas.DriverCreate, db: Session = Depends(get_db)):
    db_driver = models.Driver(**driver.dict())
    db.add(db_driver)
    db.commit()
    db.refresh(db_driver)
    return db_driver

@app.get("/rides/waiting", response_model=list[schemas.Ride])
def get_waiting_rides(db: Session = Depends(get_db)):
    """Returns a list of all rides currently in the 'waiting' state (the FCFS queue)."""
    waiting_rides = db.query(models.Ride).filter(models.Ride.status == 'waiting').order_by(models.Ride.requested_at).all()
    return waiting_rides

@app.post("/rides/request_http", response_model=schemas.Ride)
async def request_ride_http(ride_request: schemas.RideRequest, db: Session = Depends(get_db)):
    """Allows creating a ride request via a standard HTTP POST, for testing."""
    new_ride = models.Ride(client_id=ride_request.client_id, start_zone=ride_request.start_zone, drop_zone=ride_request.drop_zone)
    db.add(new_ride)
    db.commit()
    db.refresh(new_ride)
    
    notification = {
        "type": "new_ride",
        "ride_id": new_ride.id,
        "start_zone": new_ride.start_zone,
        "drop_zone": new_ride.drop_zone
    }
    await manager.broadcast_to_drivers(notification)
    return new_ride