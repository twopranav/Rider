from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

app = FastAPI()

# Pydantic model for incoming data
class RideRequest(BaseModel):
    user_id: str
    source_location: str
    destination_location: str

DATABASE_URL = "postgresql://userA:1234567890@localhost/rider_db"

engine = None
SessionLocal = None
Base = declarative_base()

class Ride(Base):
    __tablename__ = "rides"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    source_location = Column(String)
    destination_location = Column(String)
    status = Column(String, nullable=False)
    pool_flag = Column(Integer, nullable=False, default=0)

# Initialize DB connection safely
try:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)
    Base.metadata.create_all(bind = engine)
    db_ready = True
except Exception as e:
    print(f"Database connection failed: {e}")
    db_ready = False

@app.post("/rides")
def create_ride(ride: RideRequest):
    if not db_ready:
        # Fallback if DB is not connected
        return {"status": "Postgres not available", "data_received": ride.dict()}

    db = SessionLocal()
    try:
        # Create a new Ride object from the request.
        db_ride = Ride(
            user_id = ride.user_id,
            source_location = ride.source_location,
            destination_location = ride.destination_location,
            status = 'pending',
            pool_flag = 0
        )
        db.add(db_ride)
        db.commit()
        db.refresh(db_ride)
        return {"status": "stored in Postgres", "ride_id": db_ride.id}
    except Exception as e:
        db.rollback()
        print(f"DATABASE WRITE ERROR: {e}")
        raise HTTPException(status_code = 500, detail = "Database write error.")
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host = "127.0.0.1", port = 8001) 