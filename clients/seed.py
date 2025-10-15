import random
from faker import Faker
from server.database import SessionLocal
from server import models

# Initialize Faker to generate fake data
fake = Faker()

# Populates the database with a specified number of drivers and clients.
def seed_database(num_drivers: int = 100, num_clients: int = 100):
    db = SessionLocal()
    try:
        print("Seeding database with initial data...")

        # Create Drivers
        for _ in range(num_drivers):
            driver = models.Driver(
                name=fake.name(),
                current_zone=random.randint(1, 20),
                status='available'
            )
            db.add(driver)

        # Create Clients
        for _ in range(num_clients):
            client = models.Client(
                name=fake.name()
            )
            db.add(client)

        db.commit()
        print(f"Successfully added {num_drivers} drivers and {num_clients} clients to the database.")

    except Exception as e:
        print(f"An error occurred during seeding: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()