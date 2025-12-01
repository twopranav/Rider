from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, func, Time, Date, Text
import enum
from .database import Base

class DriverStatus(str, enum.Enum):
    available = "available"
    busy = "busy"

class RideStatus(str, enum.Enum):
    waiting = "waiting"
    assigned = "assigned"
    completed = "completed"

class BookingStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"
    paused = "paused"

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    port = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Driver(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    vehicle_number = Column(String(20), unique=True, nullable=False)
    current_zone = Column(Integer, nullable=False)
    port = Column(Integer, nullable=False)
    status = Column(Enum(DriverStatus), default=DriverStatus.available)
    reserved_booking_id = Column(Integer, nullable=True)
    reserved_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Ride(Base):
    __tablename__ = "rides"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    start_zone = Column(Integer, nullable=False)
    drop_zone = Column(Integer, nullable=False)
    is_priority = Column(Integer, default=0)  # stored as 1/0
    status = Column(Enum(RideStatus), default=RideStatus.waiting)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())

# In server/models.py

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    start_zone = Column(Integer, nullable=False)
    drop_zone = Column(Integer, nullable=False)
    days_of_week = Column(String(50), nullable=False)
    time_of_day = Column(Time, nullable=False)
    start_date = Column(Date, nullable=False)
    
    # NEW: Store if this subscription is for Pooling or Solo VIP
    ride_mode = Column(String(20), default="solo")  # "pool" or "solo"
    
    monthly_price = Column(Integer, nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.active)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class BookingRide(Base):
    __tablename__ = "booking_rides"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    ride_id = Column(Integer, ForeignKey("rides.id"), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(RideStatus), default=RideStatus.waiting)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# New: offers to pool a set of BookingRides
class PoolOfferStatus(str, enum.Enum):
    open = "open"
    filled = "filled"
    expired = "expired"
    cancelled = "cancelled"

class PoolOffer(Base):
    __tablename__ = "pool_offers"
    id = Column(Integer, primary_key=True, index=True)
    # JSON text storing list of booking_ride ids that are candidates for this offer
    booking_ride_ids = Column(Text, nullable=False)
    start_zone = Column(Integer, nullable=False)
    drop_zone = Column(Integer, nullable=False)  # pooling only offered when same drop_zone
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(PoolOfferStatus), default=PoolOfferStatus.open)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# New: pooled ride record (represents an assigned pooled trip)
class PooledRide(Base):
    __tablename__ = "pooled_rides"
    id = Column(Integer, primary_key=True, index=True)
    # JSON text storing list of client ids
    client_ids = Column(Text, nullable=False)
    # corresponding booking_ride ids if any
    booking_ride_ids = Column(Text, nullable=True)
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=True)
    start_zone = Column(Integer, nullable=False)
    drop_zone = Column(Integer, nullable=False)
    is_priority = Column(Integer, default=1)  # pooled bookings are priority
    status = Column(Enum(RideStatus), default=RideStatus.waiting)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
