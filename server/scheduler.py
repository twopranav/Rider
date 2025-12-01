import asyncio
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from server.database import SessionLocal
from server import models

LOG_LEVEL = logging.INFO
SWEEP_INTERVAL_SECONDS = 30
LOOKAHEAD_MINUTES = 60

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("booking-scheduler")

def get_db(): return SessionLocal()

def process_daily_subscriptions():
    db = get_db()
    try:
        now = datetime.now()
        lookahead_limit = now + timedelta(minutes=LOOKAHEAD_MINUTES)
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        current_day_token = days[now.weekday()]

        bookings = db.query(models.Booking).filter(models.Booking.status == models.BookingStatus.active).all()
        
        count = 0
        for b in bookings:
            user_days = [d.strip().lower() for d in b.days_of_week.split(",")]
            if current_day_token not in user_days: continue

            scheduled_dt = datetime.combine(now.date(), b.time_of_day)
            
            if now <= scheduled_dt <= lookahead_limit:
                exists = db.query(models.BookingRide).filter(models.BookingRide.booking_id == b.id, models.BookingRide.scheduled_for == scheduled_dt).first()
                if not exists:
                    br = models.BookingRide(booking_id=b.id, scheduled_for=scheduled_dt, status=models.RideStatus.waiting)
                    db.add(br); count += 1
                    logger.info(f"Generated Ride for User {b.client_id} at {scheduled_dt.strftime('%H:%M')}")

        if count > 0: db.commit(); logger.info(f"Injecting {count} rides.")
    except Exception: logger.exception("Error process"); db.rollback()
    finally: db.close()

def dispatch_priority_rides():
    db = get_db()
    try:
        pending = db.query(models.BookingRide).filter(models.BookingRide.status == models.RideStatus.waiting).all()
        pool_candidates = []

        for br in pending:
            booking = db.query(models.Booking).filter(models.Booking.id == br.booking_id).first()
            if not booking: continue

            if booking.ride_mode != "pool":
                ride = models.Ride(client_id=booking.client_id, start_zone=booking.start_zone, drop_zone=booking.drop_zone, is_priority=1, status=models.RideStatus.waiting)
                db.add(ride); br.status = models.RideStatus.assigned; br.ride_id = ride.id
                logger.info(f"Auto-dispatch Solo VIP: User {booking.client_id}")
            else:
                pool_candidates.append((br, booking))

        db.commit()

        groups = defaultdict(list)
        for br, booking in pool_candidates:
            key = (booking.start_zone, booking.drop_zone, booking.time_of_day)
            groups[key].append(br)

        for key, members in groups.items():
            if len(members) >= 2:
                booking_ids = [m.id for m in members]
                offer = models.PoolOffer(booking_ride_ids=json.dumps(booking_ids), start_zone=key[0], drop_zone=key[1], scheduled_for=datetime.combine(datetime.now().date(), key[2]), status=models.PoolOfferStatus.open)
                db.add(offer)
                for m in members: m.status = models.RideStatus.assigned
                logger.info(f"Created POOL OFFER #{offer.id} for {len(members)} users.")

        db.commit()
    except Exception: logger.exception("Error dispatch"); db.rollback()
    finally: db.close()

async def frequent_job(): process_daily_subscriptions(); dispatch_priority_rides()

def start_scheduler():
    try: loop = asyncio.get_event_loop()
    except RuntimeError: loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    scheduler = AsyncIOScheduler(event_loop=loop)
    scheduler.add_job(frequent_job, 'interval', seconds=SWEEP_INTERVAL_SECONDS)
    scheduler.start()
    logger.info(f"Scheduler Running (Local Time). Interval: {SWEEP_INTERVAL_SECONDS}s")
    try: loop.run_forever()
    except (KeyboardInterrupt, SystemExit): scheduler.shutdown()

if __name__ == "__main__": start_scheduler()