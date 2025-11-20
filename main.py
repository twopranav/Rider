from fastapi import FastAPI, WebSocket, Depends, WebSocketDisconnect, HTTPException
from sqlalchemy.orm import Session
import json
from datetime import datetime
from typing import List
from server.database import engine, get_db, SessionLocal
from server import models, schemas
from server.connection_manager import ConnectionManager


# Create DB tables (idempotent)
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Zoned Ride-Hailing System")
manager = ConnectionManager()


def calculate_time(zone1: int, zone2: int) -> int:
    """Calculates travel time based on the distance between zones."""
    return abs(zone1 - zone2) * 5  # 5 minutes per zone difference


# -----------------------
# WebSocket: Rider Socket
# -----------------------
@app.websocket("/ws/rider/{rider_id}")
async def rider_websocket(websocket: WebSocket, rider_id: int):
    """
    Rider connects over WebSocket and can send JSON actions:
      {"action":"request_ride", "start_zone":int, "drop_zone":int, "is_priority":bool}
    Server will create a Ride (waiting) and broadcast new_ride to drivers.
    """
    await manager.connect(websocket, "rider", rider_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("action") == "request_ride":
                db = SessionLocal()
                try:
                    is_priority = payload.get("is_priority", False)
                    ride = models.Ride(
                        client_id=rider_id,
                        start_zone=payload["start_zone"],
                        drop_zone=payload["drop_zone"],
                        is_priority=1 if is_priority else 0,
                        status=models.RideStatus.waiting
                    )
                    db.add(ride)
                    db.commit()
                    db.refresh(ride)

                    notification = {
                        "type": "new_ride",
                        "ride_id": ride.id,
                        "start_zone": ride.start_zone,
                        "drop_zone": ride.drop_zone,
                        "is_priority": bool(ride.is_priority)
                    }
                    # Broadcast to all drivers
                    await manager.broadcast_to_drivers(notification)

                    message = "Priority ride requested." if is_priority else "Ride requested."
                    await manager.send_to_rider(rider_id, {"type": "info", "message": f"{message} Searching for drivers..."})
                finally:
                    db.close()

    except WebSocketDisconnect:
        manager.disconnect("rider", rider_id)
        print(f"Rider {rider_id} disconnected.")


# -----------------------
# WebSocket: Driver Socket
# -----------------------
@app.websocket("/ws/driver/{driver_id}")
async def driver_websocket(websocket: WebSocket, driver_id: int, db: Session = Depends(get_db)):
    """
    Driver WebSocket. Driver can send:
      {"action":"accept_ride", "ride_id":int}
      {"action":"complete_ride", "ride_id":int}
      {"action":"accept_pooled", "pooled_id":int}
    """
    await manager.connect(websocket, "driver", driver_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            # Accept single ride action
            if payload.get("action") == "accept_ride":
                ride_id = payload["ride_id"]

                # Use a fresh session for atomic operations
                local_db = SessionLocal()
                try:
                    # Fetch the ride (must be waiting) and driver
                    ride_to_accept = local_db.query(models.Ride).filter(
                        models.Ride.id == ride_id,
                        models.Ride.status == models.RideStatus.waiting
                    ).first()
                    driver = local_db.query(models.Driver).filter(models.Driver.id == driver_id).first()

                    if not ride_to_accept:
                        await websocket.send_text(json.dumps({"type": "error", "message": "Ride is invalid or already taken."}))
                        continue

                    if not driver or driver.status != models.DriverStatus.available:
                        await websocket.send_text(json.dumps({"type": "error", "message": "You are not available to accept a ride."}))
                        continue

                    # 1) Priority enforcement: if any priority waiting ride exists, it must be accepted first
                    oldest_priority_ride = local_db.query(models.Ride).filter(
                        models.Ride.status == models.RideStatus.waiting,
                        models.Ride.is_priority == 1
                    ).order_by(models.Ride.requested_at).first()

                    if oldest_priority_ride:
                        if ride_to_accept.id != oldest_priority_ride.id:
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "message": f"Cannot accept this ride. Priority ride {oldest_priority_ride.id} must be accepted first."
                            }))
                            continue

                    else:
                        # 2) When no priority rides, enforce FCFS among normal rides
                        if ride_to_accept.is_priority == 0:
                            oldest_normal = local_db.query(models.Ride).filter(
                                models.Ride.status == models.RideStatus.waiting,
                                models.Ride.is_priority == 0
                            ).order_by(models.Ride.requested_at).first()
                            if oldest_normal and oldest_normal.id != ride_to_accept.id:
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "message": f"Cannot accept this ride. Normal ride {oldest_normal.id} must be accepted first (FCFS)."
                                }))
                                continue

                    # ASSIGN the ride
                    ride_to_accept.driver_id = driver_id
                    ride_to_accept.status = models.RideStatus.assigned
                    driver.status = models.DriverStatus.busy
                    local_db.commit()

                    time_to_arrive = calculate_time(driver.current_zone, ride_to_accept.start_zone)
                    rider_notification = {
                        "type": "driver_assigned",
                        "driver_name": driver.name,
                        "arrival_time_minutes": time_to_arrive
                    }
                    await manager.send_to_rider(ride_to_accept.client_id, rider_notification)

                    driver_notification = {
                        "type": "ride_taken",
                        "ride_id": ride_to_accept.id,
                        "accepted_by_driver_id": driver_id
                    }
                    await manager.broadcast_to_drivers(driver_notification)

                finally:
                    local_db.close()

            # Complete ride action
            elif payload.get("action") == "complete_ride":
                ride_id = payload["ride_id"]
                local_db = SessionLocal()
                try:
                    ride = local_db.query(models.Ride).filter(
                        models.Ride.id == ride_id,
                        models.Ride.driver_id == driver_id
                    ).first()
                    driver = local_db.query(models.Driver).filter(models.Driver.id == driver_id).first()

                    if ride and driver:
                        ride.status = models.RideStatus.completed
                        driver.status = models.DriverStatus.available
                        driver.current_zone = ride.drop_zone
                        # clear reservation metadata if present
                        driver.reserved_booking_id = None
                        driver.reserved_until = None
                        local_db.commit()

                        rider_notification = {"type": "ride_completed", "message": "Your ride is complete. Thank you!"}
                        await manager.send_to_rider(ride.client_id, rider_notification)

                        driver_notification = {"type": "info", "message": f"Ride {ride.id} completed. Your new zone is {driver.current_zone} and you are now available."}
                        await websocket.send_text(json.dumps(driver_notification))
                    else:
                        await websocket.send_text(json.dumps({"type": "error", "message": "Ride not found or not assigned to you."}))
                finally:
                    local_db.close()

            # Accept pooled ride action
            elif payload.get("action") == "accept_pooled":
                pooled_id = payload.get("pooled_id")
                if pooled_id is None:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Missing pooled_id."}))
                    continue

                local_db = SessionLocal()
                try:
                    pooled = local_db.query(models.PooledRide).filter(
                        models.PooledRide.id == pooled_id,
                        models.PooledRide.status == models.RideStatus.waiting
                    ).first()
                    driver = local_db.query(models.Driver).filter(
                        models.Driver.id == driver_id,
                        models.Driver.status == models.DriverStatus.available
                    ).first()

                    if not pooled:
                        await websocket.send_text(json.dumps({"type": "error", "message": "Pooled ride not available."}))
                        continue
                    if not driver:
                        await websocket.send_text(json.dumps({"type": "error", "message": "Driver not available."}))
                        continue

                    # assign pooled ride
                    pooled.driver_id = driver_id
                    pooled.status = models.RideStatus.assigned
                    driver.status = models.DriverStatus.busy
                    local_db.commit()

                    # notify each client in pooled ride (if connected)
                    try:
                        client_ids = json.loads(pooled.client_ids)
                    except Exception:
                        client_ids = []

                    for cid in client_ids:
                        await manager.send_to_rider(cid, {"type": "driver_assigned", "driver_name": driver.name, "arrival_time_minutes": calculate_time(driver.current_zone, pooled.start_zone)})

                    # broadcast to drivers that pooled ride was taken
                    await manager.broadcast_to_drivers({"type": "ride_taken", "ride_id": f"pooled-{pooled.id}", "accepted_by_driver_id": driver_id})

                finally:
                    local_db.close()

    except WebSocketDisconnect:
        manager.disconnect("driver", driver_id)
        # mark driver available on disconnect using short-lived session
        local_db = SessionLocal()
        try:
            local_db.query(models.Driver).filter(models.Driver.id == driver_id).update({"status": models.DriverStatus.available})
            local_db.commit()
        finally:
            local_db.close()
        print(f"Driver {driver_id} disconnected and set to available.")


# -----------------------
# REST: Registration APIs
# -----------------------
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


# ------------------------------
# REST: Ride queue & waiting list
# ------------------------------
@app.get("/rides/waiting", response_model=list[schemas.Ride])
def get_waiting_rides(db: Session = Depends(get_db)):
    """
    Return waiting rides ordered with priority rides first then oldest first.
    """
    waiting_rides = db.query(models.Ride).filter(models.Ride.status == models.RideStatus.waiting).order_by(
        models.Ride.is_priority.desc(),
        models.Ride.requested_at.asc()
    ).all()
    return waiting_rides


@app.get("/rides/queue")
def get_full_queue(db: Session = Depends(get_db)):
    """
    Returns a visible representation of the current queue:
      - priority booking-origin rides first (is_priority == 1)
      - pooled rides that are waiting
      - open pool offers
      - normal waiting rides afterwards
    """
    priority = db.query(models.Ride).filter(models.Ride.status == models.RideStatus.waiting, models.Ride.is_priority == 1).order_by(models.Ride.requested_at.asc()).all()
    normal = db.query(models.Ride).filter(models.Ride.status == models.RideStatus.waiting, models.Ride.is_priority == 0).order_by(models.Ride.requested_at.asc()).all()
    pooled_waiting = db.query(models.PooledRide).filter(models.PooledRide.status == models.RideStatus.waiting).all()
    offers = db.query(models.PoolOffer).filter(models.PoolOffer.status == models.PoolOfferStatus.open).order_by(models.PoolOffer.scheduled_for.asc()).all()

    def ride_to_dict(r):
        return {
            "id": r.id,
            "type": "ride",
            "client_id": r.client_id,
            "booking_id": r.booking_id,
            "start_zone": r.start_zone,
            "drop_zone": r.drop_zone,
            "is_priority": bool(r.is_priority),
            "requested_at": r.requested_at.isoformat()
        }

    def pooled_to_dict(p):
        return {
            "id": p.id,
            "type": "pooled_ride",
            "client_ids": json.loads(p.client_ids),
            "booking_ride_ids": json.loads(p.booking_ride_ids) if p.booking_ride_ids else None,
            "start_zone": p.start_zone,
            "drop_zone": p.drop_zone,
            "status": p.status.value,
            "created_at": p.created_at.isoformat()
        }

    def offer_to_dict(o):
        return {
            "id": o.id,
            "booking_ride_ids": json.loads(o.booking_ride_ids),
            "start_zone": o.start_zone,
            "drop_zone": o.drop_zone,
            "scheduled_for": o.scheduled_for.isoformat(),
            "status": o.status.value
        }

    queue = {
        "priority_rides": [ride_to_dict(r) for r in priority],
        "pooled_rides": [pooled_to_dict(p) for p in pooled_waiting],
        "pool_offers": [offer_to_dict(o) for o in offers],
        "normal_rides": [ride_to_dict(r) for r in normal]
    }
    return queue


# -----------------------
# REST: Booking endpoints
# -----------------------
@app.post("/bookings/", response_model=schemas.BookingOut)
def create_booking(booking_in: schemas.BookingCreate, db: Session = Depends(get_db)):
    days_str = ",".join([d.lower() for d in booking_in.days_of_week])
    booking = models.Booking(
        client_id=booking_in.client_id,
        start_zone=booking_in.start_zone,
        drop_zone=booking_in.drop_zone,
        days_of_week=days_str,
        time_of_day=booking_in.time_of_day,
        start_date=booking_in.start_date,
        end_date=booking_in.end_date,
        monthly_price=booking_in.monthly_price,
        status=models.BookingStatus.active
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/bookings/{client_id}", response_model=list[schemas.BookingOut])
def get_bookings_for_client(client_id: int, db: Session = Depends(get_db)):
    bookings = db.query(models.Booking).filter(models.Booking.client_id == client_id).all()
    return bookings


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    b = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    b.status = models.BookingStatus.cancelled
    db.commit()
    return {"detail": "Booking cancelled"}


@app.get("/bookings/{booking_id}/upcoming", response_model=list[schemas.BookingRideOut])
def upcoming_booking_rides(booking_id: int, db: Session = Depends(get_db)):
    items = db.query(models.BookingRide).filter(models.BookingRide.booking_id == booking_id).order_by(models.BookingRide.scheduled_for.asc()).all()
    return items


# -----------------------
# REST: Pooling endpoints
# -----------------------
@app.get("/pooling/offers", response_model=list[schemas.PoolOfferOut])
def list_pool_offers(db: Session = Depends(get_db)):
    offers = db.query(models.PoolOffer).filter(models.PoolOffer.status == models.PoolOfferStatus.open).order_by(models.PoolOffer.scheduled_for.asc()).all()
    return offers


@app.post("/pooling/{offer_id}/accept", response_model=schemas.PooledRideOut)
def accept_pool_offer(offer_id: int, accept_in: schemas.PoolAcceptIn, db: Session = Depends(get_db)):
    """
    Client calls this to accept joining a pool offer.
    When enough clients accept (min_clients), the API creates a PooledRide (priority) and marks offer filled.
    """
    MIN_CLIENTS_TO_FILL = 2

    offer = db.query(models.PoolOffer).filter(models.PoolOffer.id == offer_id, models.PoolOffer.status == models.PoolOfferStatus.open).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Pool offer not found or closed.")

    booking_ride_ids = json.loads(offer.booking_ride_ids)
    # collect booking clients who are still waiting
    candidates = []
    for br_id in booking_ride_ids:
        br = db.query(models.BookingRide).filter(models.BookingRide.id == br_id).first()
        if br and br.status == models.RideStatus.waiting:
            booking = db.query(models.Booking).filter(models.Booking.id == br.booking_id).first()
            if booking:
                candidates.append({"client_id": booking.client_id, "booking_ride_id": br.id})

    # Add the accepting client if not present
    accept_client_id = accept_in.client_id
    if not any(c["client_id"] == accept_client_id for c in candidates):
        candidates.append({"client_id": accept_client_id, "booking_ride_id": None})

    if len(candidates) >= MIN_CLIENTS_TO_FILL:
        client_ids = [c["client_id"] for c in candidates]
        booking_ids = [c["booking_ride_id"] for c in candidates if c["booking_ride_id"] is not None]
        pr = models.PooledRide(
            client_ids=json.dumps(client_ids),
            booking_ride_ids=json.dumps(booking_ids) if booking_ids else None,
            start_zone=offer.start_zone,
            drop_zone=offer.drop_zone,
            status=models.RideStatus.waiting,
            is_priority=1
        )
        db.add(pr)
        # mark booking rides referenced as assigned
        for bid in booking_ride_ids:
            br = db.query(models.BookingRide).filter(models.BookingRide.id == bid).first()
            if br:
                br.status = models.RideStatus.assigned
        offer.status = models.PoolOfferStatus.filled
        db.commit()
        db.refresh(pr)
        return pr

    raise HTTPException(status_code=400, detail="Not enough participants to fill pool yet. Poll the offer to see updates.")


@app.post("/pooling/{offer_id}/decline")
def decline_pool_offer(offer_id: int, decline_in: schemas.PoolAcceptIn, db: Session = Depends(get_db)):
    offer = db.query(models.PoolOffer).filter(models.PoolOffer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    # For simplicity we do not persist declines in this demo
    return {"detail": "Declined"}
