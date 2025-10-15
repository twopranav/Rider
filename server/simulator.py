import requests
import random
import time
from server.database import SessionLocal
from server import models

# URL of your running FastAPI server
API_URL = "http://127.0.0.1:8000"

def get_available_client_id(db):
    """
    Finds a client who does not have an active ('waiting' or 'assigned') ride.
    This is the core of the "derived status" logic for the simulation.
    """
    # 1. Get a set of all client IDs
    all_client_ids = {c.id for c in db.query(models.Client.id).all()}
    
    # 2. Get a set of IDs of clients with active rides
    active_client_ids = {
        r.client_id for r in db.query(models.Ride.client_id)
        .filter(models.Ride.status.in_(['waiting', 'assigned']))
        .all()
    }
    
    # 3. Find clients who are available by subtracting the active set from the total set
    available_ids = list(all_client_ids - active_client_ids)
    
    return random.choice(available_ids) if available_ids else None

def create_new_ride_request():
    """Simulates a rider requesting a ride, ensuring they are available."""
    # Only create a new ride on some ticks, not all (e.g.,60% chance)
    if random.random() < 0.6:
        db = SessionLocal()
        try:
            client_id = get_available_client_id(db)
            
            if not client_id:
                print("No available clients to create a ride for.")
                return

            start_zone = random.randint(1, 20)
            drop_zone = random.randint(1, 20)
            # Ensure start and drop-off are not the same
            while start_zone == drop_zone:
                drop_zone = random.randint(1, 20)
            
            ride_payload = {
                "client_id": client_id,
                "start_zone": start_zone,
                "drop_zone": drop_zone
            }
            
            response = requests.post(f"{API_URL}/rides/request_http", json=ride_payload)
            
            if response.status_code == 200:
                print(f"✅ Simulator created new ride for available client {client_id}: Zone {start_zone} -> {drop_zone}")
            else:
                print(f"❌ Failed to create ride: {response.text}")
        finally:
            db.close()


# Matchmaking logic that only assigns an available driver if they are in the same zone as the ride's starting location.
def find_and_assign_drivers():
    db = SessionLocal()
    try:
        # Get all rides that are waiting for a driver, oldest first
        waiting_rides = db.query(models.Ride).filter(models.Ride.status == 'waiting').order_by(models.Ride.requested_at).all()
        
        if not waiting_rides:
            return

        # Keep track of drivers assigned in this tick to avoid double-booking them
        assigned_driver_ids_this_tick = set()

        for ride in waiting_rides:
            # For each ride, find a driver who is available, in the correct starting zone, has not already been assigned in this same loop
            suitable_driver = db.query(models.Driver).filter(
                models.Driver.status == 'available',
                models.Driver.current_zone == ride.start_zone,
                ~models.Driver.id.in_(assigned_driver_ids_this_tick)
            ).first()

            if suitable_driver:
                print(f"🤝 Match found! Assigning Driver {suitable_driver.id} from Zone {ride.start_zone} to Ride {ride.id}.")
                
                url = f"{API_URL}/rides/{ride.id}/accept_simulated/{suitable_driver.id}"
                requests.post(url)
                
                # Add this driver to the set of those assigned in this loop
                assigned_driver_ids_this_tick.add(suitable_driver.id)

    finally:
        db.close()

def run_simulation():
    """The main simulation loop."""
    print("🚀 Starting ride-hailing simulation...")
    while True:
        print(f"\n--- Simulation Tick @ {time.ctime()} ---")
        
        # 1. Simulate new riders requesting trips
        create_new_ride_request()
        
        # 2. Run the matchmaking for any waiting rides
        find_and_assign_drivers()

        # 3. (To be implemented) Check for and complete finished trips
        # complete_finished_rides() 

        # Wait for a few seconds before the next tick
        time.sleep(5)

if __name__ == "__main__":
    run_simulation()