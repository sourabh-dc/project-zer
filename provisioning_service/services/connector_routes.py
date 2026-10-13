# ==================================================================================
# ERP CONNECTOR ENDPOINTS — product import from client ERP systems
# Gated on the `erp.integration` plan feature (Standard Integration Pack).
# ==================================================================================
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service import Models
from provisioning_service.core.connectors.base import CANONICAL_FIELDS, ConnectorError
from provisioning_service.core.connectors.credentials import store_credentials
from provisioning_service.core.connectors.engine import build_connector, discover_and_store_schema, run_sync
from provisioning_service.core.connectors.scheduler import schedule_connection, unschedule_connection
from provisioning_service.core.db_config import SessionLocal, get_db
from provisioning_service.core.entitlement_helpers import load_tenant_features
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/v1", tags=["ERP Connectors"])


# ── Schemas ─────────────────────────────────────────────────────────

class ProviderOut(BaseModel):
    provider_code: str
    display_name: str
    auth_type: str
    config_schema: Dict[str, Any]
    default_field_map: Dict[str, Any]


class ConnectionCreate(BaseModel):
    provider_code: str
    name: str = Field(min_length=1, max_length=200)
    config: Dict[str, Any] = Field(default_factory=dict)
    credentials: Dict[str, Any] = Field(default_factory=dict)
    schedule_cron: Optional[str] = None
    field_map: Optional[Dict[str, str]] = None
    deactivate_missing: bool = False


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    credentials: Optional[Dict[str, Any]] = None   # replaces stored credentials
    schedule_cron: Optional[str] = None
    field_map: Optional[Dict[str, str]] = None
    deactivate_missing: Optional[bool] = None
    status: Optional[str] = None                    # active | disabled


class ConnectionOut(BaseModel):
    connection_id: str
    provider_code: str
    name: str
    config: Dict[str, Any]
    has_credentials: bool
    status: str
    schedule_cron: Optional[str] = None
    field_map: Optional[Dict[str, Any]] = None
    deactivate_missing: bool
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None
    has_schema: bool = False
    schema_discovered_at: Optional[str] = None


class SyncRunOut(BaseModel):
    sync_run_id: str
    connection_id: str
    trigger: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    error_summary: Optional[List[Dict[str, Any]]] = None
    warnings: Optional[List[Dict[str, Any]]] = None


class SyncRunItemOut(BaseModel):
    external_id: Optional[str] = None
    sku: Optional[str] = None
    action: str
    message: Optional[str] = None


class TestResultOut(BaseModel):
    ok: bool
    message: str


# ── Helpers ─────────────────────────────────────────────────────────

def _require_erp_feature(db: Session, tenant_id: str) -> None:
    active, _plan, _name, features = load_tenant_features(db, tenant_id)
    if not active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active subscription")
    if "erp.integration" not in features:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ERP connectors require the Standard Integration Pack add-on",
        )


def _check_tenant(ctx, tenant_id: str) -> None:
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tenant")


def _prepare_credentials(provider_code: str, creds: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize credentials before storing.

    NetSuite private keys arrive from the upload button / paste box with
    literal "\\n" sequences or missing PEM armor — fix or reject here.
    """
    if provider_code == "netsuite" and creds.get("private_key"):
        key = str(creds["private_key"]).replace("\\n", "\n").strip()
        if "BEGIN" not in key or "PRIVATE KEY" not in key:
            raise HTTPException(
                status_code=400,
                detail="private_key must be a PEM block (-----BEGIN PRIVATE KEY----- ...)",
            )
        creds = {**creds, "private_key": key + "\n"}
    return creds


def _get_connection(db: Session, tenant_id: str, connection_id: str) -> Models.TenantConnection:
    conn = db.query(Models.TenantConnection).filter(
        Models.TenantConnection.connection_id == connection_id,
        Models.TenantConnection.tenant_id == tenant_id,
    ).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _conn_out(c: Models.TenantConnection) -> ConnectionOut:
    schema = c.source_schema or {}
    return ConnectionOut(
        connection_id=str(c.connection_id),
        provider_code=c.provider_code,
        name=c.name,
        config=c.config or {},
        has_credentials=bool(c.credentials_ref or c.credentials_enc),
        status=c.status,
        schedule_cron=c.schedule_cron,
        field_map=c.field_map,
        deactivate_missing=c.deactivate_missing or False,
        last_sync_at=c.last_sync_at.isoformat() if c.last_sync_at else None,
        last_sync_status=c.last_sync_status,
        has_schema=bool(schema.get("fields")),
        schema_discovered_at=schema.get("discovered_at"),
    )


def _run_out(r: Models.SyncRun) -> SyncRunOut:
    return SyncRunOut(
        sync_run_id=str(r.sync_run_id),
        connection_id=str(r.connection_id),
        trigger=r.trigger,
        status=r.status,
        started_at=r.started_at.isoformat() if r.started_at else None,
        finished_at=r.finished_at.isoformat() if r.finished_at else None,
        created_count=r.created_count,
        updated_count=r.updated_count,
        skipped_count=r.skipped_count,
        error_count=r.error_count,
        error_summary=r.error_summary,
        warnings=r.warnings,
    )


def _background_sync(connection_id: str) -> None:
    """Run a sync in a fresh session (BackgroundTasks/threadpool)."""
    db = SessionLocal()
    try:
        connection = db.query(Models.TenantConnection).filter(
            Models.TenantConnection.connection_id == uuid.UUID(connection_id)
        ).first()
        if not connection:
            logger.error(f"Background sync: connection {connection_id} not found")
            return
        run_sync(db, connection, trigger="manual")
    except Exception as e:
        logger.error(f"Background sync failed for {connection_id}: {e}")
    finally:
        db.close()


# ── Provider catalogue ──────────────────────────────────────────────

@router.get("/connector-providers", response_model=List[ProviderOut])
def list_connector_providers(db: Session = Depends(get_db)):
    """List available ERP providers with their setup-form schema."""
    providers = db.query(Models.ConnectorProvider).filter(
        Models.ConnectorProvider.is_active == True
    ).all()
    return providers


# ── Connections ─────────────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/connections", response_model=ConnectionOut, status_code=201)
def create_connection(
    tenant_id: str,
    req: ConnectionCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Create a connection, verify credentials, and (optionally) schedule it."""
    _check_tenant(ctx, tenant_id)
    _require_erp_feature(db, tenant_id)

    provider = db.query(Models.ConnectorProvider).filter(
        Models.ConnectorProvider.provider_code == req.provider_code,
        Models.ConnectorProvider.is_active == True,
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{req.provider_code}'")

    # Reconnect path: a revoked/disabled row with the same (tenant, provider, name)
    # is resurrected with fresh credentials instead of violating the unique index.
    existing = db.query(Models.TenantConnection).filter(
        Models.TenantConnection.tenant_id == tenant_id,
        Models.TenantConnection.provider_code == req.provider_code,
        Models.TenantConnection.name == req.name,
    ).first()
    if existing and existing.status in ("revoked", "disabled"):
        existing.config = req.config
        existing.field_map = req.field_map or provider.default_field_map
        existing.schedule_cron = req.schedule_cron
        existing.deactivate_missing = req.deactivate_missing
        store_credentials(existing, _prepare_credentials(req.provider_code, req.credentials))
        ok, message = build_connector(existing).test_connection()
        if not ok:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Connection test failed: {message}")
        existing.status = "active"
        db.commit()
        db.refresh(existing)
        schedule_connection(existing)
        discover_and_store_schema(db, existing)
        logger.info(f"Connection reconnected: {existing.connection_id} ({req.provider_code}) for tenant {tenant_id}")
        return _conn_out(existing)
    if existing:
        raise HTTPException(status_code=409, detail="A connection with this name already exists for this provider")

    connection = Models.TenantConnection(
        connection_id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        provider_code=req.provider_code,
        name=req.name,
        config=req.config,
        field_map=req.field_map or provider.default_field_map,
        schedule_cron=req.schedule_cron,
        deactivate_missing=req.deactivate_missing,
        status="active",
    )
    store_credentials(connection, _prepare_credentials(req.provider_code, req.credentials))

    # Verify before saving — bad credentials should fail fast
    ok, message = build_connector(connection).test_connection()
    if not ok:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {message}")

    db.add(connection)
    db.commit()
    db.refresh(connection)
    schedule_connection(connection)

    # Schema matcher: discover source fields for the mapping UI (best-effort)
    discover_and_store_schema(db, connection)

    logger.info(f"Connection created: {connection.connection_id} ({req.provider_code}) for tenant {tenant_id}")
    return _conn_out(connection)


@router.get("/tenants/{tenant_id}/connections", response_model=List[ConnectionOut])
def list_connections(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    _check_tenant(ctx, tenant_id)
    connections = db.query(Models.TenantConnection).filter(
        Models.TenantConnection.tenant_id == tenant_id,
    ).order_by(Models.TenantConnection.created_at.desc()).all()
    return [_conn_out(c) for c in connections]


@router.get("/tenants/{tenant_id}/connections/{connection_id}", response_model=ConnectionOut)
def get_connection(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    _check_tenant(ctx, tenant_id)
    return _conn_out(_get_connection(db, tenant_id, connection_id))


@router.patch("/tenants/{tenant_id}/connections/{connection_id}", response_model=ConnectionOut)
def update_connection(
    tenant_id: str,
    connection_id: str,
    req: ConnectionUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    _check_tenant(ctx, tenant_id)
    _require_erp_feature(db, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)

    if req.name is not None:
        connection.name = req.name
    if req.config is not None:
        connection.config = req.config
    if req.field_map is not None:
        connection.field_map = req.field_map
    if req.deactivate_missing is not None:
        connection.deactivate_missing = req.deactivate_missing
    if req.status is not None:
        if req.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="status must be 'active' or 'disabled'")
        connection.status = req.status
    if req.schedule_cron is not None:
        connection.schedule_cron = req.schedule_cron or None
    if req.credentials:
        store_credentials(connection, _prepare_credentials(connection.provider_code, req.credentials))

    db.commit()
    db.refresh(connection)
    schedule_connection(connection)
    return _conn_out(connection)


@router.delete("/tenants/{tenant_id}/connections/{connection_id}", status_code=204)
def delete_connection(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Disable a connection. Sync history is retained."""
    _check_tenant(ctx, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    connection.status = "disabled"
    db.commit()
    unschedule_connection(connection.connection_id)
    logger.info(f"Connection disabled: {connection_id} for tenant {tenant_id}")


@router.post("/tenants/{tenant_id}/connections/{connection_id}/test", response_model=TestResultOut)
def test_connection(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Re-test a saved connection's credentials."""
    _check_tenant(ctx, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    ok, message = build_connector(connection).test_connection()
    if not ok and connection.status == "active":
        connection.status = "error"
        db.commit()
    elif ok and connection.status in ("error", "revoked") and (connection.credentials_ref or connection.credentials_enc):
        connection.status = "active"
        db.commit()
    if ok:
        # Refresh the discovered schema while we're connected (best-effort)
        discover_and_store_schema(db, connection)
    return TestResultOut(ok=ok, message=message)


# ── Schema matcher ──────────────────────────────────────────────────

@router.get("/canonical-fields")
def list_canonical_fields(
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Canonical target fields for the mapping UI (same for all providers)."""
    return {"fields": CANONICAL_FIELDS}


@router.get("/tenants/{tenant_id}/connections/{connection_id}/schema")
def get_connection_schema(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Return the discovered source schema stored on the connection."""
    _check_tenant(ctx, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    schema = connection.source_schema
    if not schema:
        raise HTTPException(
            status_code=404,
            detail="No schema discovered yet — call schema/refresh or re-test the connection",
        )
    return schema


@router.post("/tenants/{tenant_id}/connections/{connection_id}/schema/refresh")
def refresh_connection_schema(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Re-discover the source schema live from the ERP and store it."""
    _check_tenant(ctx, tenant_id)
    _require_erp_feature(db, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    payload = discover_and_store_schema(db, connection)
    if not payload:
        raise HTTPException(status_code=502, detail="Schema discovery failed for this provider")
    return payload


# ── Table catalogue + sample preview ──────────────────────────────

@router.get("/tenants/{tenant_id}/connections/{connection_id}/tables")
def list_connection_tables(
    tenant_id: str,
    connection_id: str,
    refresh: bool = Query(False, description="Bypass the 24h cache"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Tables per page"),
    search: Optional[str] = Query(None, description="Filter by table name (case-insensitive)"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """List queryable tables/record types in the source ERP (table picker).

    The provider catalogue can be slow (NetSuite metadata catalog reads
    60s+), so a successful live result is cached on the connection for 24h.
    The full catalogue is fetched once, then paginated server-side.
    """
    _check_tenant(ctx, tenant_id)
    _require_erp_feature(db, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)

    tables: List[Dict[str, Any]] = []
    source = "live"
    cached = False

    cfg = dict(connection.config or {})
    cache = cfg.get("_tables_cache") or {}
    if not refresh and cache.get("tables") and cache.get("cached_at"):
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cache["cached_at"])
            if age < timedelta(hours=24):
                tables = cache["tables"]
                cached = True
        except (ValueError, TypeError):
            pass

    if not cached:
        try:
            tables, source = build_connector(connection).list_tables()
        except ConnectorError as e:
            raise HTTPException(status_code=502, detail=str(e))

        if source == "live":
            cfg["_tables_cache"] = {
                "tables": tables,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            connection.config = cfg
            db.commit()

    # Optional name filter, then paginate
    if search:
        needle = search.strip().lower()
        tables = [t for t in tables if needle in str(t.get("name", "")).lower()]

    total = len(tables)
    start = (page - 1) * page_size
    page_tables = tables[start:start + page_size]

    return {
        "tables": page_tables,
        "count": total,                      # total across all pages
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "returned": len(page_tables),        # rows on this page
        "source": source,
        "cached": cached,
    }


@router.get("/tenants/{tenant_id}/connections/{connection_id}/preview")
def preview_connection_table(
    tenant_id: str,
    connection_id: str,
    table: str = Query(..., description="Source table / record type, e.g. item"),
    limit: int = Query(15, ge=1, le=100),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Return up to ``limit`` sample rows from the selected table."""
    _check_tenant(ctx, tenant_id)
    _require_erp_feature(db, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    try:
        rows = build_connector(connection).preview_table(table, limit)
    except ConnectorError as e:
        msg = str(e)
        code = 400 if "Invalid table" in msg else 502
        raise HTTPException(status_code=code, detail=msg)
    return {"table": table, "rows": rows, "count": len(rows)}


# ── Sync ────────────────────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/connections/{connection_id}/sync", status_code=202)
def trigger_sync(
    tenant_id: str,
    connection_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Start a manual sync in the background. Poll sync-runs for progress."""
    _check_tenant(ctx, tenant_id)
    _require_erp_feature(db, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    if connection.status != "active":
        raise HTTPException(status_code=400, detail=f"Connection is {connection.status}")

    running = db.query(Models.SyncRun).filter(
        Models.SyncRun.connection_id == connection.connection_id,
        Models.SyncRun.status == "running",
    ).first()
    if running:
        raise HTTPException(status_code=409, detail="A sync is already running for this connection")

    background_tasks.add_task(_background_sync, connection_id)
    return {"status": "started", "connection_id": connection_id}


@router.get("/tenants/{tenant_id}/sync-runs", response_model=List[SyncRunOut])
def list_sync_runs(
    tenant_id: str,
    connection_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    _check_tenant(ctx, tenant_id)
    query = db.query(Models.SyncRun).join(
        Models.TenantConnection,
        Models.SyncRun.connection_id == Models.TenantConnection.connection_id,
    ).filter(Models.TenantConnection.tenant_id == tenant_id)
    if connection_id:
        query = query.filter(Models.SyncRun.connection_id == connection_id)
    runs = query.order_by(Models.SyncRun.started_at.desc()).limit(limit).all()
    return [_run_out(r) for r in runs]


@router.get("/tenants/{tenant_id}/sync-runs/{sync_run_id}", response_model=SyncRunOut)
def get_sync_run(
    tenant_id: str,
    sync_run_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    _check_tenant(ctx, tenant_id)
    run = db.query(Models.SyncRun).join(
        Models.TenantConnection,
        Models.SyncRun.connection_id == Models.TenantConnection.connection_id,
    ).filter(
        Models.SyncRun.sync_run_id == sync_run_id,
        Models.TenantConnection.tenant_id == tenant_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    return _run_out(run)


@router.get("/tenants/{tenant_id}/sync-runs/{sync_run_id}/items", response_model=List[SyncRunItemOut])
def get_sync_run_items(
    tenant_id: str,
    sync_run_id: str,
    action: Optional[str] = Query(None, description="Filter: created|updated|skipped|error"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    _check_tenant(ctx, tenant_id)
    run = db.query(Models.SyncRun).join(
        Models.TenantConnection,
        Models.SyncRun.connection_id == Models.TenantConnection.connection_id,
    ).filter(
        Models.SyncRun.sync_run_id == sync_run_id,
        Models.TenantConnection.tenant_id == tenant_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")

    query = db.query(Models.SyncRunItem).filter(Models.SyncRunItem.sync_run_id == sync_run_id)
    if action:
        query = query.filter(Models.SyncRunItem.action == action)
    items = query.order_by(Models.SyncRunItem.created_at).limit(500).all()
    return [
        SyncRunItemOut(external_id=i.external_id, sku=i.sku, action=i.action, message=i.message)
        for i in items
    ]


# ── Contract lifecycle: capabilities / health / revoke (deck slice 1) ──

@router.get("/tenants/{tenant_id}/connections/{connection_id}/capabilities")
def get_connection_capabilities(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Machine-readable adapter capability declaration (write gate 1 input)."""
    _check_tenant(ctx, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    return build_connector(connection).discover_capabilities()


@router.get("/tenants/{tenant_id}/connections/{connection_id}/health")
def get_connection_health(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Live adapter health: connectivity + latency + last sync outcome."""
    _check_tenant(ctx, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    health = build_connector(connection).get_health()
    last_run = db.query(Models.SyncRun).filter(
        Models.SyncRun.connection_id == connection.connection_id,
    ).order_by(Models.SyncRun.started_at.desc()).first()
    health["last_sync"] = {
        "status": last_run.status,
        "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
    } if last_run else None
    health["connection_status"] = connection.status
    return health


@router.post("/tenants/{tenant_id}/connections/{connection_id}/revoke")
def revoke_connection(
    tenant_id: str,
    connection_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("catalog.manage")),
):
    """Revoke provider credentials best-effort, then disable the connection."""
    _check_tenant(ctx, tenant_id)
    connection = _get_connection(db, tenant_id, connection_id)
    ok, message = build_connector(connection).revoke_connection()
    connection.status = "revoked"
    connection.credentials_ref = None
    connection.credentials_enc = None
    try:
        unschedule_connection(str(connection.connection_id))
    except Exception:
        pass
    db.commit()
    return {"ok": ok, "message": message, "status": "revoked"}
