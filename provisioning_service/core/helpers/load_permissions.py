import csv

from provisioning_service.Models import Permission
from provisioning_service.core.db_config import SessionLocal

def insert_permissions_from_csv(csv_file: str):
    session = SessionLocal()
    try:
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Check if permission already exists
                existing = session.query(Permission).filter_by(code=row["code"]).first()
                if not existing:
                    perm = Permission(
                        code=row["code"],
                        description=row["description"]
                    )
                    session.add(perm)
        session.commit()
        print("Permissions inserted successfully.")
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
    finally:
        session.close()
