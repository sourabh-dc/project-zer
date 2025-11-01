from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import get_settings

DATABASE_URL = get_settings().DATABASE_URL

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)