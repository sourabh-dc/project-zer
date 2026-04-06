"""
Initialize the database — creates all tables across all services.

Usage:
    python -m shared.init_db
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.models import Base as SharedBase
from onboarding_service.models import Base as OnboardingBase
from shared.db import engine


def main():
    print(f"Creating tables in: {engine.url}")
    SharedBase.metadata.create_all(engine)
    OnboardingBase.metadata.create_all(engine)
    print("Done — tables created: outbox_events, tenants, users, roles, "
          "permissions, role_permissions, user_roles")


if __name__ == "__main__":
    main()
