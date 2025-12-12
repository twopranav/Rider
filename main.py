from fastapi import FastAPI, WebSocket, Depends, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session
from collections import defaultdict
from typing import List, Optional
from server.database import engine, get_db, SessionLocal
from server import models, schemas
from server.models import BookingSource
from server.connection_manager import ConnectionManager
import json, random, asyncio
from datetime import datetime, time

# --- DB RESET ON STARTUP ---
models.Base.metadata.drop_all(bind=engine)
models.Base.metadata.create_all(bind=engine)

# --- BACKEND BLACKLIST STORAGE ---
DECLINED_RIDES = defaultdict(set) 

# --- BACKGROUND SCHEDULER ---
async def check_scheduled_rides():
    while True:
        try:
            now = datetime.now()
            current_day = now.strftime("%a").lower()
            current_hour = now.hour
            current_minute = now.minute
            db = SessionLocal()
            bookings = db.query(models.Booking).filter(models.Booking.status == "active").all()
            for b in bookings:
                if current_day in b.days_of_week.lower():
                    if b.time_of_day.hour == current_hour and b.time_of_day.minute == current_minute:
                        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        already_triggered = db.query(models.Ride).filter(
                            models.Ride.client_id == b.client_id,
                            models.Ride.source == 'scheduled',
                            models.Ride.requested_at >= start_of_day
                        ).first()

                        if not already_triggered:
                            print(f"⏰ Triggering Scheduled Ride for Client {b.client_id}")
                            is_pool = (b.ride_mode == 'pool')
                            driver_pay = calculate_price_for_driver(b.start_zone, b.drop_zone, is_pool, "scheduled")
                            
                            ride = models.Ride(
                                client_id=b.client_id,
                                start_zone=b.start_zone,
                                drop_zone=b.drop_zone,
                                is_priority=1,       # Gold Card
                                status=models.RideStatus.waiting,
                                source="scheduled",
                                price=driver_pay
                            )
                            db.add(ride)
                            db.commit()
                            db.refresh(ride)
                            await manager.broadcast_to_drivers({
                                "type": "new_ride", 
                                "ride_id": ride.id, 
                                "from": get_location_name(b.start_zone), 
                                "to": get_location_name(b.drop_zone),
                                "is_vip": True, 
                                "ride_type": b.ride_mode, 
                                "price": ride.price
                            })
        except Exception as e:
            print(f"Scheduler Error: {e}")
        finally:
            db.close()
        await asyncio.sleep(15) 

app = FastAPI(title="Namma Yatri Clone")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(check_scheduled_rides())    

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
manager = ConnectionManager()

# --- LOCATIONS ---
ZONE_MAP = {
    1: "Koramangala", 2: "Indiranagar", 3: "Jayanagar", 4: "HSR Layout", 5: "Whitefield",
    6: "Marathahalli", 7: "Electronic City", 8: "BTM Layout", 9: "Malleswaram", 10: "JP Nagar",
    11: "MG Road", 12: "Bellandur", 13: "Basavanagudi", 14: "Hebbal", 15: "Rajajinagar",
    16: "Ulsoor", 17: "Sarjapur Road", 18: "Yelahanka", 19: "Sadashivanagar", 20: "Richmond Town",
    21: "Domlur", 22: "Frazer Town", 23: "Cooke Town", 24: "Bannerghatta Road", 25: "Kalyan Nagar",
    26: "RT Nagar", 27: "Banashankari", 28: "Yeshwanthpur", 29: "CV Raman Nagar", 30: "Old Airport Road",
    31: "Kaggadasapura", 32: "KR Puram", 33: "Commercial Street", 34: "Langford Town", 35: "Shanti Nagar",
    36: "Vijayanagar", 37: "Cambridge Layout", 38: "AECS Layout", 39: "Basaveshwaranagar", 40: "Banaswadi",
    41: "Ejipura", 42: "Mahadevapura", 43: "Kammanahalli", 44: "Sanjay Nagar", 45: "Jalahalli",
    46: "Cox Town", 47: "Vasanth Nagar", 48: "Kumaraswamy Layout", 49: "Wilson Garden", 50: "Shivajinagar",
    51: "Girinagar", 52: "Peenya", 53: "Kodihalli", 54: "Hennur", 55: "Nagawara",
    56: "Kudlu Gate", 57: "Bommanahalli", 58: "Mathikere", 59: "Lalbagh West", 60: "HRBR Layout",
    61: "Varthur", 62: "Brookefield", 63: "Koramangala 5th Block", 64: "Jayanagar 4th Block", 65: "HSR Layout Sector 7",
    66: "Nagarbhavi", 67: "Seshadripuram", 68: "Dollars Colony", 69: "Padmanabhanagar", 70: "Gottigere",
    71: "Thippasandra", 72: "ISRO Layout", 73: "New BEL Road", 74: "Benson Town", 75: "Horamavu",
    76: "Ramamurthy Nagar", 77: "Vidyaranyapura", 78: "Chandra Layout", 79: "Kanakapura Road", 80: "Mysore Road",
    81: "Arekere", 82: "Uttarahalli", 83: "Kengeri", 84: "Richards Town", 85: "Vivek Nagar",
    86: "Lingarajapuram", 87: "Thanisandra", 88: "Madiwala", 89: "Tavarekere", 90: "Murugeshpalya",
    91: "Cunningham Road", 92: "Austin Town", 93: "HBR Layout", 94: "Neelasandra", 95: "Begur",
    96: "Devanahalli", 97: "Singasandra", 98: "Hosur Road", 99: "Kadugodi", 100: "Hoodi", 101: "ITPL"
}

BASE_RATE = 20.0

def get_location_name(zone_id: int):
    return ZONE_MAP.get(zone_id, f"Zone {zone_id}")

# --- PRICING ---
def calculate_price_for_driver(start: int, drop: int, is_pool: bool, source: str = "immediate") -> int:
    dist = abs(start - drop) or 1
    base = dist * BASE_RATE * 10
    multiplier = 1.0
    if is_pool:
        multiplier = 1.5
    if source in [BookingSource.SCHEDULED_MANUAL, BookingSource.AUTO_FEATURE, "scheduled", "auto_feature"]:
        multiplier *= 1.2
    return int(base * multiplier)

def calculate_price_for_user(start: int, drop: int, is_pool: bool) -> int:
    dist = abs(start - drop) or 1
    base = dist * BASE_RATE * 10
    if is_pool: return int(base * 0.7)
    return int(base)

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

@app.get("/api/client/{id}")
def get_client_info(id: int, db: Session = Depends(get_db)):
    return db.query(models.Client).filter(models.Client.id == id).first()

@app.get("/api/driver/{id}")
def get_driver_info(id: int, db: Session = Depends(get_db)):
    return db.query(models.Driver).filter(models.Driver.id == id).first()

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
                    "solo": calculate_price_for_user(s,d,False), 
                    "pool": calculate_price_for_user(s,d,True)
                })

            elif payload.get("action") == "request_ride":
                db = SessionLocal()
                try:
                    s = payload["start_zone"]
                    d = payload["drop_zone"]
                    r_type = payload.get("ride_type", "solo")
                    src_str = payload.get("source", "immediate")
                    driver_pay = calculate_price_for_driver(s, d, (r_type == "pool"), src_str)
                    is_gold_ui = (src_str == "auto_feature" or src_str == BookingSource.AUTO_FEATURE)
                    ride = models.Ride(
                        client_id=rider_id, 
                        start_zone=s, 
                        drop_zone=d, 
                        is_priority=(1 if is_gold_ui else 0),
                        status=models.RideStatus.waiting,
                        source=src_str,
                        price=driver_pay 
                    )
                    db.add(ride); db.commit(); db.refresh(ride)

                    notif = {
                        "type": "new_ride", 
                        "ride_id": ride.id, 
                        "from": get_location_name(s), 
                        "to": get_location_name(d),
                        "is_vip": is_gold_ui, 
                        "ride_type": r_type, 
                        "price": ride.price
                    }
                    await manager.broadcast_to_drivers(notif)
                    await manager.send_to_rider(rider_id, {"type": "info", "message": "Searching..."})
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
                    if ride:
                        ride.driver_id = driver_id; ride.status = models.RideStatus.assigned
                        driver.status = models.DriverStatus.busy
                        db.commit()
                        
                        eta = random.randint(2, 8)
                        
                        await manager.send_to_rider(ride.client_id, {
                            "type": "driver_assigned", "driver_name": driver.name, "vehicle": driver.vehicle_number, "arrival": eta
                        })
                        await manager.broadcast_to_drivers({"type": "queue_update", "action": "remove", "ride_id": ride.id})

                # --- DECLINE LOGIC IMPLEMENTED ---
                elif action == "decline_ride":
                    ride_id = payload.get("ride_id")
                    if ride_id:
                        DECLINED_RIDES[ride_id].add(driver_id)
                # ---------------------------------

                elif action in ["driver_arrived", "start_trip", "complete_ride"]:
                    active_rides = db.query(models.Ride).filter(
                        models.Ride.driver_id == driver_id,
                        models.Ride.status == models.RideStatus.assigned
                    ).all()

                    for r in active_rides:
                        if action == "driver_arrived":
                            await manager.send_to_rider(r.client_id, {
                                "type": "status_update", "status": "arrived", 
                                "message": "🚖 Captain Arrived!", 
                                "detail": "Waiting at pickup location."
                            })
                        
                        elif action == "start_trip":
                            dist_est = abs(r.start_zone - r.drop_zone) * 3 + 5
                            await manager.send_to_rider(r.client_id, {
                                "type": "status_update", "status": "in_progress", 
                                "message": "🚀 Trip Started", 
                                "detail": f"ETA: {dist_est} mins to destination."
                            })

                        elif action == "complete_ride":
                            r.status = models.RideStatus.completed
                            await manager.send_to_rider(r.client_id, {"type": "ride_completed"})
                    
                    if action == "complete_ride":
                        db.query(models.Driver).filter(models.Driver.id == driver_id).update({"status": models.DriverStatus.available})
                    db.commit()

                elif action == "accept_pooled":
                    pool_id = payload["pooled_id"]
                    offer = db.query(models.PoolOffer).filter(models.PoolOffer.id == pool_id).first()
                    if offer and offer.status == models.PoolOfferStatus.open:
                        offer.status = models.PoolOfferStatus.filled
                        # (omitted for brevity)
            finally:
                db.close()
    except WebSocketDisconnect:
        manager.disconnect("driver", driver_id)

@app.get("/config/locations")   
def get_locs(): return ZONE_MAP

# --- QUEUE & HISTORY ---
@app.get("/rides/queue")
def get_q(driver_id: Optional[int] = None, db: Session=Depends(get_db)):
    waiting = db.query(models.Ride).filter(models.Ride.status == models.RideStatus.waiting)\
        .order_by(models.Ride.is_priority.desc(), models.Ride.requested_at.asc()).all()
    if driver_id:
        waiting = [r for r in waiting if driver_id not in DECLINED_RIDES[r.id]]
    q_data = []
    for r in waiting:
        client = db.query(models.Client).filter(models.Client.id == r.client_id).first()
        client_name = client.name if client else "Unknown User"
        r_source = getattr(r, "source", "immediate")
        ui_class = "card-gold" if r_source in ["scheduled", "auto_feature", BookingSource.AUTO_FEATURE] else "card-normal"
        final_price = r.price if r.price else 0
        q_data.append({ 
            "queue_position": r.id, 
            "client_id": r.client_id, 
            "client_name": client_name,
            "from": get_location_name(r.start_zone), 
            "to": get_location_name(r.drop_zone), 
            "vip": bool(r.is_priority), 
            "price": final_price,          # <--- CORRECT
            "ui_class": ui_class
        })
    return {"queue": q_data, "active": [], "drivers": []}

@app.get("/pooling/offers")
def list_pools(db: Session=Depends(get_db)):
    offers = db.query(models.PoolOffer).filter(models.PoolOffer.status == models.PoolOfferStatus.open).all()
    results = []
    for o in offers:
        ride_ids = json.loads(o.booking_ride_ids)
        base = calculate_price_for_driver(o.start_zone, o.drop_zone, True, True) 
        results.append({"id": o.id, "from": get_location_name(o.start_zone), "to": get_location_name(o.drop_zone), "seats_filled": len(ride_ids), "value": base})
    return results

@app.get("/rides/history/{role}/{user_id}")
def get_hist(role: str, user_id: int, db: Session=Depends(get_db)):
    return [] 
@app.get("/bookings/{client_id}/upcoming")
def get_upcoming(client_id: int, db: Session=Depends(get_db)): return []
@app.get("/clients/{cid}/subscription_status")
def check_sub(cid: int, db: Session=Depends(get_db)): 
    sub = db.query(models.Booking).filter(models.Booking.client_id == cid, models.Booking.status == models.BookingStatus.active).first()
    return {"is_vip": sub is not None}
@app.post("/pooling/{oid}/accept")
def acc_pool(oid: int, db: Session=Depends(get_db)): return {}
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