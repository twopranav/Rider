from fastapi import FastAPI, WebSocket, Depends, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session
import json

from server.database import engine, get_db, SessionLocal
from server import models, schemas
from server.connection_manager import ConnectionManager

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Namma Yatri Clone")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
manager = ConnectionManager()

ZONE_MAP = {
    1: "Koramangala", 2: "Indiranagar", 3: "HSR Layout", 4: "Electronic City",
    5: "Whitefield", 6: "MG Road", 7: "Jayanagar", 8: "Marathahalli",
    9: "Hebbal", 10: "Airport (KIAL)"
}

BASE_RATE = 15.0
POOL_DISCOUNT = 0.6

def get_location_name(zone_id: int):
    return ZONE_MAP.get(zone_id, f"Zone {zone_id}")

def calculate_price(start: int, drop: int, is_pool: bool = False) -> int:
    dist = abs(start - drop) or 1
    price = dist * BASE_RATE * 10
    if is_pool: price *= POOL_DISCOUNT
    return int(price)

@app.get("/")
def show_login(request: Request): return templates.TemplateResponse("login.html", {"request": request})
@app.get("/register")
def show_reg(request: Request): return templates.TemplateResponse("register.html", {"request": request})
@app.get("/dashboard")
def show_admin(request: Request): return templates.TemplateResponse("admin.html", {"request": request})
@app.get("/app/rider/{client_id}")
def show_rider(request: Request, client_id: int): return templates.TemplateResponse("rider.html", {"request": request, "id": client_id})
@app.get("/app/driver/{driver_id}")
def show_driver(request: Request, driver_id: int): return templates.TemplateResponse("driver.html", {"request": request, "id": driver_id})

# --- WEBSOCKETS ---
@app.websocket("/ws/rider/{rider_id}")
async def rider_websocket(websocket: WebSocket, rider_id: int):
    await manager.connect(websocket, "rider", rider_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("action") == "get_price_estimate":
                s = payload["start_zone"]; d = payload["drop_zone"]
                await manager.send_to_rider(rider_id, {
                    "type": "price_estimate", 
                    "solo": calculate_price(s,d,False), 
                    "pool": calculate_price(s,d,True)
                })

            elif payload.get("action") == "request_ride":
                db = SessionLocal()
                try:
                    s = payload["start_zone"]; d = payload["drop_zone"]
                    r_type = payload.get("ride_type", "solo")
                    
                    is_vip = False
                    try:
                        sub = db.query(models.Booking).filter(models.Booking.client_id == rider_id, models.Booking.status == models.BookingStatus.active).first()
                        if sub: is_vip = True
                    except: pass

                    if r_type == "pool" and not is_vip:
                        await manager.send_to_rider(rider_id, {"type": "error", "message": "🔒 Pool is VIP only! Schedule a pass first."})
                        continue

                    ride = models.Ride(client_id=rider_id, start_zone=s, drop_zone=d, is_priority=(1 if is_vip else 0), status=models.RideStatus.waiting)
                    db.add(ride); db.commit(); db.refresh(ride)

                    notif = {
                        "type": "new_ride", 
                        "ride_id": ride.id, 
                        "from": get_location_name(s), 
                        "to": get_location_name(d),
                        "is_vip": is_vip, 
                        "price": calculate_price(s, d, r_type == "pool"),
                        "vehicle_type": r_type
                    }
                    await manager.broadcast_to_drivers(notif)
                    await manager.send_to_rider(rider_id, {"type": "info", "message": "Searching for driver..."})

                except Exception as e:
                    print(f"Error: {e}")
                    db.rollback()
                finally:
                    db.close()
    except WebSocketDisconnect:
        manager.disconnect("rider", rider_id)

@app.websocket("/ws/driver/{driver_id}")
async def driver_websocket(websocket: WebSocket, driver_id: int):
    await manager.connect(websocket, "driver", driver_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action")
            db = SessionLocal()
            try:
                if action == "accept_ride":
                    ride = db.query(models.Ride).filter(models.Ride.id == payload["ride_id"]).first()
                    driver = db.query(models.Driver).filter(models.Driver.id == driver_id).first()
                    
                    if ride and driver:
                        ride.driver_id = driver_id; ride.status = models.RideStatus.assigned
                        driver.status = models.DriverStatus.busy
                        db.commit()
                        
                        await manager.send_to_rider(ride.client_id, {"type": "driver_assigned", "driver_name": driver.name, "vehicle": driver.vehicle_number, "arrival": 3})
                        await manager.send_to_driver(driver_id, {"type": "ride_confirmed", "ride_id": ride.id})
                        await manager.broadcast_to_drivers({"type": "ride_taken", "ride_id": ride.id}) 

                elif action in ["driver_arrived", "start_trip", "complete_ride"]:
                    active_rides = db.query(models.Ride).filter(models.Ride.driver_id == driver_id, models.Ride.status == models.RideStatus.assigned).all()
                    for r in active_rides:
                        if action == "complete_ride":
                            r.status = models.RideStatus.completed
                            await manager.send_to_rider(r.client_id, {"type": "ride_completed"})
                            await manager.send_to_driver(driver_id, {"type": "trip_finished"})
                        elif action == "driver_arrived":
                            await manager.send_to_rider(r.client_id, {"type": "status_update", "message": "🚖 Driver Arrived!"})
                        elif action == "start_trip":
                            await manager.send_to_rider(r.client_id, {"type": "status_update", "message": "🚀 Trip Started!"})
                    
                    if action == "complete_ride":
                        db.query(models.Driver).filter(models.Driver.id == driver_id).update({"status": models.DriverStatus.available})
                    db.commit()

                elif action == "accept_pooled":
                    pool_id = payload["pooled_id"]
                    offer = db.query(models.PoolOffer).filter(models.PoolOffer.id == pool_id).first()
                    if offer and offer.status == models.PoolOfferStatus.open:
                        offer.status = models.PoolOfferStatus.filled
                        driver = db.query(models.Driver).filter(models.Driver.id == driver_id).first()
                        if driver: driver.status = models.DriverStatus.busy
                        
                        booking_ids = json.loads(offer.booking_ride_ids)
                        clients = []
                        for bid in booking_ids:
                            br = db.query(models.BookingRide).filter(models.BookingRide.id == bid).first()
                            if br:
                                booking = db.query(models.Booking).filter(models.Booking.id == br.booking_id).first()
                                if booking:
                                    new_ride = models.Ride(client_id=booking.client_id, driver_id=driver_id, start_zone=booking.start_zone, drop_zone=booking.drop_zone, is_priority=1, status=models.RideStatus.assigned)
                                    db.add(new_ride); db.flush(); clients.append(booking.client_id)
                        db.commit()
                        await manager.send_to_driver(driver_id, {"type": "pool_accepted"})
                        await manager.broadcast_to_drivers({"type": "pool_taken", "pool_id": pool_id})
                        for cid in clients: 
                            await manager.send_to_rider(cid, {"type": "driver_assigned", "driver_name": driver.name, "vehicle": driver.vehicle_number, "arrival": 5})

            except Exception as e: print(f"Driver Error: {e}")
            finally: db.close()
    except WebSocketDisconnect:
        manager.disconnect("driver", driver_id)

# --- APIs ---
@app.get("/config/locations")
def get_locs(): return ZONE_MAP
@app.get("/pooling/offers")
def list_pools(db: Session=Depends(get_db)):
    offers = db.query(models.PoolOffer).filter(models.PoolOffer.status == models.PoolOfferStatus.open).all()
    results = []
    for o in offers:
        ride_ids = json.loads(o.booking_ride_ids)
        est_val = calculate_price(o.start_zone, o.drop_zone, True) * len(ride_ids)
        results.append({"id": o.id, "from": get_location_name(o.start_zone), "to": get_location_name(o.drop_zone), "value": est_val})
    return results

# --- FIXED HISTORY ENDPOINT ---
@app.get("/rides/history/{role}/{user_id}")
def get_hist(role: str, user_id: int, db: Session=Depends(get_db)):
    query = db.query(models.Ride).filter(models.Ride.status == models.RideStatus.completed)
    if role == "rider":
        query = query.filter(models.Ride.client_id == user_id)
    elif role == "driver":
        query = query.filter(models.Ride.driver_id == user_id)
    
    # Sort by newest first
    rides = query.order_by(models.Ride.requested_at.desc()).all()
    
    return [{
        "id": r.id, 
        "date": r.requested_at.strftime("%Y-%m-%d %H:%M"), 
        "from": get_location_name(r.start_zone), 
        "to": get_location_name(r.drop_zone), 
        "price": calculate_price(r.start_zone, r.drop_zone, bool(r.is_priority))
    } for r in rides]

@app.get("/bookings/{client_id}/upcoming")
def get_upcoming(client_id: int, db: Session=Depends(get_db)):
    bookings = db.query(models.Booking).filter(models.Booking.client_id == client_id, models.Booking.status == models.BookingStatus.active).all()
    return [{"id": b.id, "route": f"{get_location_name(b.start_zone)} ➡ {get_location_name(b.drop_zone)}", "time": b.time_of_day.strftime("%H:%M"), "days": b.days_of_week} for b in bookings]
@app.get("/clients/{cid}/subscription_status")
def check_sub(cid: int, db: Session=Depends(get_db)):
    sub = db.query(models.Booking).filter(models.Booking.client_id == cid, models.Booking.status == models.BookingStatus.active).first()
    return {"is_vip": sub is not None}
@app.post("/clients/register", response_model=schemas.Client)
def rc(c: schemas.ClientCreate, db: Session=Depends(get_db)): x=models.Client(**c.dict()); db.add(x); db.commit(); db.refresh(x); return x
@app.post("/drivers/register", response_model=schemas.Driver)
def rd(d: schemas.DriverCreate, db: Session=Depends(get_db)): x=models.Driver(**d.dict()); db.add(x); db.commit(); db.refresh(x); return x
@app.post("/bookings/", response_model=schemas.BookingOut)
def rb(b: schemas.BookingCreate, db: Session=Depends(get_db)):
    days=",".join(b.days_of_week)
    mode=getattr(b, 'ride_mode', 'pool')
    x=models.Booking(client_id=b.client_id, start_zone=b.start_zone, drop_zone=b.drop_zone, days_of_week=days, time_of_day=b.time_of_day, start_date=b.start_date, ride_mode=mode, monthly_price=b.monthly_price)
    db.add(x); db.commit(); db.refresh(x); return x