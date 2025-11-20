import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, time as dt_time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_

# Import server package modules (make sure you're running from project root)
from server.database import SessionLocal
from server import models

# -----------------------
# Configuration
# -----------------------
LOG_LEVEL = logging.INFO

LOOKAHEAD_DAYS = 7              # how many days ahead to pre-generate booking occurrences
BOOKING_LEAD_MINUTES = 20       # how many minutes before scheduled time we attempt reservation
SWEEP_INTERVAL_SECONDS = 60     # how often to run the main sweep job
MIN_POOL_CANDIDATES = 2         # minimum booking occurrences to consider a pool offer

# Optional: how long to hold a reserved driver past scheduled time (minutes)
DRIVER_RESERVATION_BUFFER_MINUTES = 15

# -----------------------
# Logging
# -----------------------
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("booking-scheduler")


# -----------------------
# Helper functions
# -----------------------
def parse_days(days_str: str) -> set:
    """Convert comma separated day tokens into a set, e.g. 'mon,tue' -> {'mon','tue'}"""
    return set(d.strip().lower() for d in days_str.split(",") if d.strip())


def weekday_token(dt: datetime) -> str:
    """Map python weekday (0=mon) to token"""
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt.weekday()]


# -----------------------
# Core worker functions
# -----------------------
def create_booking_rides_for_lookahead():
    """
    Scan active bookings and create BookingRide records for dates in the lookahead window.
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        end = now + timedelta(days=LOOKAHEAD_DAYS)
        logger.info("Creating booking rides for window %s -> %s", now.isoformat(), end.isoformat())

        bookings = db.query(models.Booking).filter(models.Booking.status == models.BookingStatus.active).all()

        created = 0
        for b in bookings:
            days = parse_days(b.days_of_week)
            # start from either booking.start_date or today, whichever is later
            start_date = max(b.start_date, now.date())
            d = start_date
            last_date = end.date()

            while d <= last_date and (b.end_date is None or d <= b.end_date):
                token = weekday_token(datetime.combine(d, dt_time()))
                if token in days:
                    scheduled_dt = datetime.combine(d, b.time_of_day)
                    if scheduled_dt > now:
                        exists = db.query(models.BookingRide).filter(
                            models.BookingRide.booking_id == b.id,
                            models.BookingRide.scheduled_for == scheduled_dt
                        ).first()
                        if not exists:
                            br = models.BookingRide(
                                booking_id=b.id,
                                scheduled_for=scheduled_dt,
                                status=models.RideStatus.waiting
                            )
                            db.add(br)
                            created += 1
                d = d + timedelta(days=1)

        if created:
            db.commit()
            logger.info("Created %d BookingRide rows.", created)
        else:
            logger.debug("No new BookingRide rows created.")
    except Exception as e:
        logger.exception("Error while creating booking rides: %s", e)
        db.rollback()
    finally:
        db.close()


def create_pool_offers_from_candidates(db, candidates):
    """
    Given a list of BookingRide candidates (BookingRide objects),
    create PoolOffer rows for groups that qualify (>= MIN_POOL_CANDIDATES and same scheduled time/start/drop).
    """
    # Group by (scheduled_for iso, start_zone, drop_zone)
    groups = defaultdict(list)
    for br in candidates:
        booking = db.query(models.Booking).filter(models.Booking.id == br.booking_id).first()
        if not booking:
            continue
        key = (br.scheduled_for.isoformat(), booking.start_zone, booking.drop_zone)
        groups[key].append((br, booking))

    created_offers = 0
    for (scheduled_iso, start_zone, drop_zone), br_booking_pairs in groups.items():
        br_list = [pair[0] for pair in br_booking_pairs]
        if len(br_list) >= MIN_POOL_CANDIDATES:
            scheduled_for = br_list[0].scheduled_for
            # check if an open offer already exists
            existing = db.query(models.PoolOffer).filter(
                models.PoolOffer.scheduled_for == scheduled_for,
                models.PoolOffer.start_zone == start_zone,
                models.PoolOffer.drop_zone == drop_zone,
                models.PoolOffer.status == models.PoolOfferStatus.open
            ).first()
            if existing:
                logger.debug("PoolOffer already exists for %s zone %s->%s", scheduled_for.isoformat(), start_zone, drop_zone)
                continue

            br_ids = [br.id for br in br_list]
            offer = models.PoolOffer(
                booking_ride_ids=json.dumps(br_ids),
                start_zone=start_zone,
                drop_zone=drop_zone,
                scheduled_for=scheduled_for,
                status=models.PoolOfferStatus.open
            )
            db.add(offer)
            created_offers += 1
            logger.info("Created PoolOffer %s for %d booking rides at %s %s->%s", scheduled_for.isoformat(), len(br_ids), scheduled_for.isoformat(), start_zone, drop_zone)

    if created_offers:
        try:
            db.commit()
            logger.info("Committed %d new PoolOffer(s).", created_offers)
        except Exception:
            db.rollback()
            logger.exception("Failed to commit new pool offers.")


def attempt_reservations_for_candidates(db, candidates):
    """
    For each candidate BookingRide, try to find an available driver in the booking's start_zone
    and reserve them by creating an assigned Ride and marking driver busy/reserved.
    """
    reserved_count = 0
    for br in candidates:
        # Skip if this BookingRide already has a linked ride or was assigned
        if br.ride_id is not None or br.status != models.RideStatus.waiting:
            continue

        booking = db.query(models.Booking).filter(models.Booking.id == br.booking_id).first()
        if not booking:
            continue

        # Try to find an available driver in the same start zone who is not reserved
        driver = db.query(models.Driver).filter(
            models.Driver.status == models.DriverStatus.available,
            models.Driver.current_zone == booking.start_zone,
            models.Driver.reserved_booking_id == None
        ).first()

        if not driver:
            # no driver available now for this booking ride
            continue

        try:
            # Reserve driver and create a pre-assigned Ride
            driver.reserved_booking_id = booking.id
            driver.reserved_until = br.scheduled_for + timedelta(minutes=DRIVER_RESERVATION_BUFFER_MINUTES)
            # mark driver as busy immediately to avoid other assignments
            driver.status = models.DriverStatus.busy

            ride = models.Ride(
                client_id=booking.client_id,
                driver_id=driver.id,
                booking_id=booking.id,
                start_zone=booking.start_zone,
                drop_zone=booking.drop_zone,
                is_priority=1,
                status=models.RideStatus.assigned
            )
            db.add(ride)
            db.flush()  # to populate ride.id

            br.ride_id = ride.id
            br.status = models.RideStatus.assigned

            reserved_count += 1
            logger.info("Reserved Driver %s for BookingRide %s (Ride %s)", driver.id, br.id, ride.id)
        except Exception:
            db.rollback()
            logger.exception("Failed to reserve driver for BookingRide %s", br.id)

    if reserved_count:
        try:
            db.commit()
            logger.info("Committed reservations for %d booking rides.", reserved_count)
        except Exception:
            db.rollback()
            logger.exception("Failed to commit reservations.")


def booking_reservation_sweep():
    """
    1) Find BookingRide occurrences within the lead window and still waiting.
    2) Group them to create PoolOffer(s) where eligible.
    3) Attempt reservations for each candidate (pre-assign drivers).
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        window_start = now
        window_end = now + timedelta(minutes=BOOKING_LEAD_MINUTES)
        logger.debug("Running reservation sweep for window %s -> %s", window_start.isoformat(), window_end.isoformat())

        candidates = db.query(models.BookingRide).filter(
            and_(
                models.BookingRide.scheduled_for >= window_start,
                models.BookingRide.scheduled_for <= window_end,
                models.BookingRide.status == models.RideStatus.waiting
            )
        ).all()

        if not candidates:
            logger.debug("No booking ride candidates in lead window.")
            return

        logger.info("Found %d booking ride candidate(s) in lead window.", len(candidates))

        # 1) Create pool offers from candidates that share same scheduled_for/start_zone/drop_zone
        create_pool_offers_from_candidates(db, candidates)

        # 2) Attempt reservations for candidates (non-pooled and pooled if desired)
        attempt_reservations_for_candidates(db, candidates)

    except Exception:
        logger.exception("Error during booking_reservation_sweep")
    finally:
        db.close()


async def frequent_job():
    """
    Combines generation + reservation steps and runs them in order.
    """
    logger.debug("Starting frequent_job: create bookings and reservation sweep")
    # 1) create booking rides for LOOKAHEAD window
    create_booking_rides_for_lookahead()
    # 2) reservation & pooling sweep
    booking_reservation_sweep()


def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: asyncio.ensure_future(frequent_job()), 'interval', seconds=SWEEP_INTERVAL_SECONDS)
    scheduler.start()
    logger.info("Booking scheduler started (runs every %s seconds)", SWEEP_INTERVAL_SECONDS)
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()


# -----------------------
# CLI entrypoint
# -----------------------
if __name__ == "__main__":
    logger.info("Starting booking scheduler process")
    start_scheduler()
