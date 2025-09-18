from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import os

app = FastAPI()

# Pydantic model for incoming data
class RideRequest(BaseModel):
    user_id: str
    source_location: int
    destination_location: int

DATABASE_URL = "postgresql://userA:1234567890@localhost/rider_db"

engine = None
SessionLocal = None
Base = declarative_base()


## CHANGE: Added the SQLAlchemy model for the 'locations' table.
## This makes SQLAlchemy aware of the table so it can create the foreign key.
class Location(Base):
    __tablename__ = "locations"
    loc_id = Column(Integer, primary_key=True)
    loc_name = Column(String)


# --- SQLAlchemy Model for the 'rides' table ---
class Ride(Base):
    __tablename__ = "rides"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    
    source_location = Column(Integer, ForeignKey("locations.loc_id"))
    destination_location = Column(Integer, ForeignKey("locations.loc_id"))
    
    status = Column(String, nullable=False)
    pool_flag = Column(Integer, nullable=False, default=0)
    request_time = Column(DateTime, nullable=False, default=datetime.utcnow)


# Initialize DB connection safely
try:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # This command now "sees" both the Location and Ride models
    Base.metadata.create_all(bind=engine) 
    db_ready = True
except Exception as e:
    print(f"Database connection failed: {e}")
    db_ready = False

@app.post("/rides")
def create_ride(ride: RideRequest):
    if not db_ready:
        raise HTTPException(status_code=503, detail="Database not available")

    db = SessionLocal()
    try:
        db_ride = Ride(
            user_id=ride.user_id,
            source_location=ride.source_location,
            destination_location=ride.destination_location,
            status='pending',
            pool_flag=0,
            request_time=datetime.utcnow()
        )
        db.add(db_ride)
        db.commit()
        db.refresh(db_ride)
        return {"status": "stored in Postgres", "ride_id": db_ride.id}
    except Exception as e:
        db.rollback()
        # This is where your helpful error log is coming from!
        print(f"DATABASE WRITE ERROR: {e}") 
        raise HTTPException(status_code=500, detail="Database write error.")
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    # Make sure to use the correct filename here
    uvicorn.run("rider_server_postgres:app", host="127.0.0.1", port=8001, reload=True)
