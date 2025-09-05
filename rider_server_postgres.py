from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

app = FastAPI()

# Pydantic model for incoming data
class RideRequest(BaseModel):
    user_id: str
    source_location: str
    destination_location: str

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://userA:1234567890@localhost/rider_db")

engine = None
SessionLocal = None
Base = declarative_base()

class Ride(Base):
    __tablename__ = "rides"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    source_location = Column(String)
    destination_location = Column(String)

# Initialize DB connection safely
try:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db_ready = True
except Exception as e:
    print(f"Database connection failed: {e}")
    db_ready = False

@app.post("/rides")
def create_ride(ride: RideRequest):
    if db_ready:
        # Store data in Postgres
        db = SessionLocal()
        db_ride = Ride(
            user_id=ride.user_id,
            source_location=ride.source_location,
            destination_location=ride.destination_location,
        )
        db.add(db_ride)
        db.commit()
        db.refresh(db_ride)
        db.close()
        return {"status": "stored in Postgres", "ride_id": db_ride.id}
    else:
        # Fallback: Just print and acknowledge
        print("Committed to memory (Postgres not available):")
        print(ride.dict())
        return {"status": "Postgres not available", "data_received": ride.dict()}
