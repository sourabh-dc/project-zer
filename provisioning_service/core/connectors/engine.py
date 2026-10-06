"""
Sync engine — pulls CanonicalItems from a connector and upserts them
into the products table. Provider-agnostic.

Dedup order per item:
  1. (tenant_id, external_id)  → update
  2. (tenant_id, sku)          → link + update
  3. no match                  → create

One DB transaction per page: page-level atomicity, run-level partial success.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Category, Product, SyncRun, SyncRunItem, TenantConnection, Vendor,
    CanonicalSupplier, CanonicalProduct, ReviewQueueItem,
)
from provisioning_service.core.connectors.base import BaseConnector, CanonicalItem, ConnectorError
from provisioning_service.core.connectors.canonical import (
    normalize_name, match_confidence, extract_attributes, classify,
    REVIEW_THRESHOLD, AUTO_MATCH_THRESHOLD,
)
from provisioning_service.core.connectors.credentials import resolve_credentials
from provisioning_service.core.connectors.envelope import build_envelope
from provisioning_service.core.connectors.registry import get_connector_class
from provisioning_service.core.entitlement_helpers import check_feature_limit
from provisioning_service.utils.logger import logger

MAX_ITEM_LOGS = 500          # cap sync_run_items rows per run
MAX_ERROR_SUMMARY = 20       # first N errors kept on the run row
PAGE_DELAY_SECONDS = 0.2     # polite delay between provider pages


def classify_error(exc: Exception) -> str:
    """Retry classification (deck slice 2): transient | auth | permanent | data_quality."""
    msg = str(exc).lower()
    if any(k in msg for k in ("401", "403", "token rejected", "unauthorized", "forbidden", "authentication")):
        return "auth"
    if any(k in msg for k in ("timeout", "timed out", "429", "502", "503", "504", "connection", "throttl")):
        return "transient"
    if any(k in msg for k in ("normalize", "missing sku", "invalid", "malformed")):
        return "data_quality"
    return "permanent"


def build_connector(connection: TenantConnection) -> BaseConnector:
    """Instantiate the connector for a connection with resolved credentials."""
    cls = get_connector_class(connection.provider_code)
    credentials = resolve_credentials(connection)
    return cls(connection.config or {}, credentials)


def discover_and_store_schema(db: Session, connection: TenantConnection) -> Dict[str, Any]:
    """Run the connector's discover_schema() and store it on the connection.

    Best-effort: discovery failures fall back to the provider's curated
    list, and total failure leaves any existing schema untouched.
    Returns the stored payload: {"fields", "discovered_at", "source"}.
    """
    existing = connection.source_schema or {}
    try:
        fields = build_connector(connection).discover_schema()
    except Exception as e:
        logger.warning(f"Schema discovery failed for {connection.connection_id}: {e}")
        return existing

    if not fields:
        return existing

    payload = {
        "fields": fields,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "source": "live",
        "field_count": len(fields),
        "custom_count": sum(1 for f in fields if f.get("custom")),
    }
    connection.source_schema = payload
    db.commit()
    return payload


def _find_or_create_category(db: Session, tenant_id, name: str) -> Optional[uuid.UUID]:
    name = name.strip()
    if not name:
        return None
    code = name.lower().replace(" ", "_")[:100]
    cat = db.query(Category).filter(
        Category.tenant_id == tenant_id,
        Category.code == code,
    ).first()
    if cat:
        return cat.category_id
    cat = Category(
        category_id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name[:255],
        code=code,
        active=True,
    )
    db.add(cat)
    db.flush()
    return cat.category_id


def _find_or_create_vendor(db: Session, tenant_id, name: str, correlation_id: str = "") -> Optional[uuid.UUID]:
    """Canonical-aware vendor resolution (deck slice 3).

    Exact normalized match → link. High-confidence fuzzy → link + alias
    recorded. Below threshold → review queue, NO silent merge.
    """
    name = name.strip()
    if not name:
        return None
    norm = normalize_name(name)

    # 1. Existing tenant vendor by exact name (legacy fast path)
    vendor = db.query(Vendor).filter(
        Vendor.tenant_id == tenant_id,
        Vendor.name.ilike(name),
    ).first()

    # 2. Canonical supplier resolution
    canonical = db.query(CanonicalSupplier).filter(
        CanonicalSupplier.tenant_id == tenant_id,
        CanonicalSupplier.normalized_name == norm,
    ).first()

    if canonical is None:
        # Fuzzy against all canonical suppliers for this tenant
        best, best_score = None, 0
        for cs in db.query(CanonicalSupplier).filter(CanonicalSupplier.tenant_id == tenant_id).all():
            score = match_confidence(norm, cs.normalized_name)
            if score > best_score:
                best, best_score = cs, score

        if best and best_score >= AUTO_MATCH_THRESHOLD:
            canonical = best
            aliases = set(best.aliases or [])
            if name not in aliases:
                aliases.add(name)
                best.aliases = sorted(aliases)
        elif best and best_score >= REVIEW_THRESHOLD:
            # Likely duplicate — hold for human review, never auto-merge
            db.add(ReviewQueueItem(
                review_id=uuid.uuid4(),
                tenant_id=tenant_id,
                object_type="supplier",
                source_record={"name": name, "normalized": norm},
                proposed_match_id=best.canonical_supplier_id,
                proposed_match_name=best.display_name,
                confidence=best_score,
                reason=f"Possible duplicate of '{best.display_name}'",
            ))
        # Below threshold or no candidates → create new canonical identity
        if canonical is None:
            canonical = CanonicalSupplier(
                canonical_supplier_id=uuid.uuid4(),
                tenant_id=tenant_id,
                display_name=name[:255],
                normalized_name=norm[:255],
                aliases=[name],
            )
            db.add(canonical)
            db.flush()

    if vendor is None:
        vendor = Vendor(
            vendor_id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name[:255],
            status="active",
        )
        db.add(vendor)
        db.flush()
    return vendor.vendor_id


def _link_canonical_product(db: Session, tenant_id, item: CanonicalItem, payload_hash: str = "") -> None:
    """Resolve/create the canonical product identity for an ingested item.

    Deterministic attributes extracted now; AI-assist plugs into
    extract_attributes later. Low-confidence name matches go to review.
    """
    norm = normalize_name(item.name)
    if not norm:
        return
    canonical = db.query(CanonicalProduct).filter(
        CanonicalProduct.tenant_id == tenant_id,
        CanonicalProduct.normalized_name == norm,
    ).first()
    if canonical is None:
        attrs = extract_attributes(item.description or item.name)
        canonical = CanonicalProduct(
            canonical_product_id=uuid.uuid4(),
            tenant_id=tenant_id,
            display_name=item.name[:255],
            normalized_name=norm[:255],
            attributes=attrs or None,
            category_name=(item.category_name or classify(attrs, item.description or item.name) or "")[:255] or None,
        )
        db.add(canonical)
        db.flush()


def _apply_item(product: Product, item: CanonicalItem, connection: TenantConnection) -> None:
    """Copy canonical fields onto a Product row (create or update).

    Never wipes fields the provider didn't send (None = not mapped/absent).
    """
    product.display_name = item.name[:255]
    if item.description is not None:
        product.sales_description = item.description
    if item.purchase_price_minor is not None:
        product.purchase_price_minor = item.purchase_price_minor
    if item.currency:
        product.currency = item.currency[:3]
    product.active = item.is_active
    product.external_id = item.external_id
    product.source_connection_id = connection.connection_id
    if item.ean:
        product.ean = item.ean[:128]


def _log_item(
    db: Session,
    run: SyncRun,
    item: Optional[CanonicalItem],
    action: str,
    message: Optional[str],
    logged: int,
    raw_payload: Optional[dict] = None,
    payload_hash: Optional[str] = None,
) -> int:
    if logged >= MAX_ITEM_LOGS:
        return logged
    db.add(SyncRunItem(
        id=uuid.uuid4(),
        sync_run_id=run.sync_run_id,
        external_id=item.external_id if item else None,
        sku=item.sku if item else None,
        action=action,
        message=(message or "")[:500] or None,
        raw_payload=raw_payload,
        payload_hash=payload_hash,
    ))
    return logged + 1


def _validate_mappings(connection: TenantConnection, field_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Check mapped source fields against the discovered source schema.

    Returns a list of warnings (empty when no schema stored or all good).
    A missing field means the ERP likely renamed/removed it — the sync
    still runs, but the canonical field gets None for every row.
    """
    schema = connection.source_schema or {}
    known = {f.get("name") for f in schema.get("fields", []) if isinstance(f, dict)}
    if not known:
        return []
    warnings: List[Dict[str, Any]] = []
    for canonical, source_field in field_map.items():
        if not source_field:
            continue
        name = source_field.lstrip("!")
        if name not in known:
            warnings.append({
                "canonical_field": canonical,
                "source_field": name,
                "message": f"Mapped source field '{name}' not found in discovered schema — "
                           f"renamed or removed in the ERP?",
            })
    return warnings


def run_sync(db: Session, connection: TenantConnection, trigger: str = "manual") -> SyncRun:
    """Execute a full sync for a connection. Returns the finished SyncRun."""
    # One running sync per connection
    running = db.query(SyncRun).filter(
        SyncRun.connection_id == connection.connection_id,
        SyncRun.status == "running",
    ).first()
    if running:
        raise ConnectorError("A sync is already running for this connection")

    run = SyncRun(
        sync_run_id=uuid.uuid4(),
        connection_id=connection.connection_id,
        trigger=trigger,
        status="running",
        correlation_id=str(uuid.uuid4()),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    tenant_id = connection.tenant_id
    field_map = dict(connection.field_map or {})
    logged = 0
    errors: List[Dict[str, Any]] = []
    seen_external_ids: set = set()

    # Resume: adopt checkpoint from the latest failed run on this connection
    resume_cursor: Optional[str] = None
    last_failed = db.query(SyncRun).filter(
        SyncRun.connection_id == connection.connection_id,
        SyncRun.status == "failed",
        SyncRun.checkpoint.isnot(None),
    ).order_by(SyncRun.started_at.desc()).first()
    if last_failed and last_failed.checkpoint:
        resume_cursor = last_failed.checkpoint
        logger.info(f"Sync run {run.sync_run_id}: resuming from checkpoint of failed run {last_failed.sync_run_id}")

    # Schema matcher: flag stale mappings before pulling any data
    warnings = _validate_mappings(connection, field_map)
    if warnings:
        run.warnings = warnings
        db.commit()
        for w in warnings:
            logger.warning(f"Sync run {run.sync_run_id}: mapping warning: {w['message']}")

    try:
        connector = build_connector(connection)
        run.adapter_version = connector.adapter_version
        db.commit()
        cursor: Optional[str] = resume_cursor

        while True:
            # ── Fetch one page (3 attempts, exponential backoff) ──
            raw_page: List[Dict[str, Any]] = []
            for attempt in range(3):
                try:
                    raw_page, cursor = connector.fetch_products(cursor)
                    break
                except ConnectorError as e:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)

            # ── Normalize + upsert page in one transaction ──
            try:
                for raw in raw_page:
                    # Source envelope: evidence for every record (deck slice 1)
                    envelope = build_envelope(
                        raw=raw,
                        object_type="product",
                        external_id=str(raw.get("id") or raw.get("external_id") or ""),
                        connection_id=str(connection.connection_id),
                        provider_code=connection.provider_code,
                        adapter_version=connector.adapter_version,
                        correlation_id=run.correlation_id,
                    )
                    try:
                        item = connector.normalize(raw, field_map)
                    except Exception as e:
                        run.error_count += 1
                        errors.append({"sku": None, "error": f"normalize: {e}", "class": "data_quality"})
                        continue

                    if not item.sku or not item.name:
                        run.skipped_count += 1
                        logged = _log_item(db, run, item, "skipped", "missing sku or name", logged,
                                           raw_payload=raw, payload_hash=envelope.payload_hash)
                        continue

                    seen_external_ids.add(item.external_id)

                    # Dedup: external_id → sku → create
                    product = None
                    if item.external_id:
                        product = db.query(Product).filter(
                            Product.tenant_id == tenant_id,
                            Product.external_id == item.external_id,
                        ).first()
                    if product is None:
                        product = db.query(Product).filter(
                            Product.tenant_id == tenant_id,
                            Product.sku == item.sku,
                        ).first()

                    if product is not None:
                        _apply_item(product, item, connection)
                        run.updated_count += 1
                        logged = _log_item(db, run, item, "updated", None, logged,
                                           raw_payload=raw, payload_hash=envelope.payload_hash)
                        continue

                    # New product — enforce catalog quota before creating
                    try:
                        check_feature_limit(db, str(tenant_id), "product.records", count=1)
                    except Exception as quota_err:
                        run.error_count += 1
                        errors.append({"sku": item.sku, "error": f"quota: {quota_err}", "class": "permanent"})
                        logged = _log_item(db, run, item, "error", "catalog quota exceeded", logged,
                                           raw_payload=raw, payload_hash=envelope.payload_hash)
                        continue

                    product = Product(
                        product_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        sku=item.sku[:100],
                        purchase_price_minor=item.purchase_price_minor or 0,
                    )
                    _apply_item(product, item, connection)

                    if item.category_name:
                        product.category_id = _find_or_create_category(db, tenant_id, item.category_name)
                    if item.vendor_name:
                        product.vendor_id = _find_or_create_vendor(
                            db, tenant_id, item.vendor_name, correlation_id=run.correlation_id)

                    # Canonical product identity + attribute extraction (slice 3)
                    _link_canonical_product(db, tenant_id, item, envelope.payload_hash)

                    db.add(product)
                    run.created_count += 1
                    logged = _log_item(db, run, item, "created", None, logged,
                                       raw_payload=raw, payload_hash=envelope.payload_hash)

                # Checkpoint: last committed page cursor survives a crash
                run.checkpoint = cursor
                db.commit()  # page-level transaction
            except Exception as page_err:
                db.rollback()
                logger.error(f"Sync run {run.sync_run_id}: page failed: {page_err}")
                errors.append({"sku": None, "error": f"page: {page_err}", "class": classify_error(page_err)})
                run.error_count += len(raw_page)

            if not cursor:
                break
            time.sleep(PAGE_DELAY_SECONDS)

        # ── Deactivate products missing from the feed (opt-in) ──
        if connection.deactivate_missing and seen_external_ids:
            stale = db.query(Product).filter(
                Product.tenant_id == tenant_id,
                Product.source_connection_id == connection.connection_id,
                Product.active == True,
                ~Product.external_id.in_(seen_external_ids),
            ).all()
            for p in stale:
                p.active = False
                run.updated_count += 1
            if stale:
                db.commit()
                logger.info(f"Sync run {run.sync_run_id}: deactivated {len(stale)} missing products")

        run.status = "success" if run.error_count == 0 else "partial"

    except Exception as e:
        db.rollback()
        logger.error(f"Sync run {run.sync_run_id} failed: {e}")
        run.status = "failed"
        errors.append({"sku": None, "error": str(e), "class": classify_error(e)})

    # ── Finalize ──
    run.finished_at = datetime.now(timezone.utc)
    run.error_summary = errors[:MAX_ERROR_SUMMARY]
    connection.last_sync_at = run.finished_at
    connection.last_sync_status = run.status
    if run.status == "failed":
        connection.status = "error"
    db.commit()
    db.refresh(run)

    logger.info(
        f"Sync run {run.sync_run_id} [{connection.provider_code}] {run.status}: "
        f"created={run.created_count} updated={run.updated_count} "
        f"skipped={run.skipped_count} errors={run.error_count}"
    )
    return run
