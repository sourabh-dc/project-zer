import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

_DEFAULT_DB = "postgresql+psycopg2://zeroque:zeroque@localhost:5000/zeroque_dev"

_engine: Engine | None = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL", _DEFAULT_DB)
        _engine = create_engine(db_url, pool_pre_ping=True, future=True)
        SessionLocal.configure(bind=_engine)
    return _engine

def init_db():
    # Sprint 1 + 2 models
    from zeroque_common.models import billing as _mb  # noqa
    from zeroque_common.models import entitlements as _me  # noqa
    from zeroque_common.models import provisioning as _mp  # noqa
    from zeroque_common.models import usage as _mu  # noqa
    # NEW in Sprint 3
    from zeroque_common.models import budgets as _bg  # noqa
    # from zeroque_common.models import commerce as _cm  # noqa  # Disabled - using V2 models
    from zeroque_common.models import ledger as _lg  # noqa
    from zeroque_common.models import products as _pd
    from zeroque_common.models import tenancy as _tn  # NEW
    from zeroque_common.models import notifications as _nt  # NEW
    from zeroque_common.models import approvals as _ap  # NEW
    eng = get_engine()
    Base.metadata.create_all(bind=eng)

def check_db() -> bool:
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False