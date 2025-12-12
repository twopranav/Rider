from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime, date, time
from .models import DriverStatus, RideStatus, BookingStatus
from server.models import BookingSource

# ----------------------
# Basic create/read DTOs
# ----------------------
class ClientCreate(BaseModel):
    name: str
    port: int

class DriverCreate(BaseModel):
    name: str
    vehicle_number: str
    port: int
    current_zone: int

class RideRequest(BaseModel):
    client_id: int
    start_zone: int
    drop_zone: int
    is_priority: Optional[bool] = False
    booking_source: BookingSource = BookingSource.IMMEDIATE

class Ride(BaseModel):
    id: int
    client_id: int
    driver_id: Optional[int] = None
    booking_id: Optional[int] = None
    start_zone: int
    drop_zone: int
    is_priority: int
    status: RideStatus
    requested_at: datetime
    model_config = ConfigDict(from_attributes=True)

class Client(BaseModel):
    id: int
    name: str
    port: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class Driver(BaseModel):
    id: int
    name: str
    vehicle_number: str
    port: int
    status: DriverStatus
    current_zone: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# ----------------------
# Booking DTOs
# ----------------------
class BookingCreate(BaseModel):
    client_id: int
    start_zone: int
    drop_zone: int
    days_of_week: List[str]  # e.g., ["mon","tue"]
    time_of_day: time
    start_date: date
    end_date: Optional[date] = None
    monthly_price: int

class BookingOut(BaseModel):
    id: int
    client_id: int
    start_zone: int
    drop_zone: int
    days_of_week: str
    time_of_day: time
    start_date: date
    end_date: Optional[date]
    monthly_price: int
    status: BookingStatus
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class BookingRideOut(BaseModel):
    id: int
    booking_id: int
    ride_id: Optional[int]
    scheduled_for: datetime
    status: RideStatus
    model_config = ConfigDict(from_attributes=True)

# ----------------------
# Pooling DTOs
# ----------------------
class PoolOfferOut(BaseModel):
    id: int
    booking_ride_ids: str  # JSON string of ids
    start_zone: int
    drop_zone: int
    scheduled_for: datetime
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class PoolOfferCreateResponse(BaseModel):
    id: int
    detail: str

class PoolAcceptIn(BaseModel):
    client_id: int  # who is accepting the pooling offer

class PooledRideOut(BaseModel):
    id: int
    client_ids: str
    booking_ride_ids: Optional[str]
    driver_id: Optional[int]
    start_zone: int
    drop_zone: int
    status: RideStatus
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
