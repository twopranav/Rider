from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from .models import DriverStatus, RideStatus

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

class Ride(BaseModel):
    id: int
    client_id: int
    driver_id: Optional[int] = None
    start_zone: int
    drop_zone: int
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