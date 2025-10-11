from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, func
import enum
from .database import Base

class DriverStatus(str, enum.Enum):
    available = "available"
    busy = "busy"

class RideStatus(str, enum.Enum):
    waiting = "waiting"
    assigned = "assigned"
    completed = "completed"

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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Ride(Base):
    __tablename__ = "rides"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=True)
    start_zone = Column(Integer, nullable=False)
    drop_zone = Column(Integer, nullable=False)
    status = Column(Enum(RideStatus), default=RideStatus.waiting)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())