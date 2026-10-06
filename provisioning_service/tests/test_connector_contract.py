"""
Behavioural contract suite — runs against MockERP (deck slice 1).

Proves the adapter contract without a live vendor account:
  - paging walks every record exactly once (no dupes, no gaps)
  - changesSince returns only records after the watermark
  - capabilities have the declared shape
  - envelope hash is stable for the same raw payload
  - createPurchaseOrder is idempotent under retry
  - injected failures surface as ConnectorError with a retry class
"""
from __future__ import annotations

import pytest

from provisioning_service.core.connectors.base import ConnectorError
from provisioning_service.core.connectors.engine import classify_error
from provisioning_service.core.connectors.envelope import build_envelope, content_hash
from provisioning_service.core.connectors.mock_erp import MockERPConnector, PAGE_SIZE, _DEFAULT_PRODUCTS
from provisioning_service.core.connectors.registry import get_connector_class


def make_connector(**config) -> MockERPConnector:
    return MockERPConnector(config, {})


# ── Registry ────────────────────────────────────────────────────────

def test_mockerp_registered():
    assert get_connector_class("mockerp") is MockERPConnector


def test_unknown_provider_raises():
    with pytest.raises(KeyError):
        get_connector_class("not_a_real_erp")


# ── Paging: no dupes, no gaps ───────────────────────────────────────

def test_paging_walks_all_records_exactly_once():
    conn = make_connector()
    seen, cursor, pages = [], None, 0
    while True:
        page, cursor = conn.fetch_products(cursor)
        pages += 1
        seen.extend(r["sku"] for r in page)
        if not cursor:
            break
        assert pages < 100, "runaway pagination"
    assert len(seen) == len(_DEFAULT_PRODUCTS)
    assert len(set(seen)) == len(seen), "duplicate records across pages"
    assert pages == (len(_DEFAULT_PRODUCTS) + PAGE_SIZE - 1) // PAGE_SIZE


def test_paging_empty_source():
    conn = make_connector(products=[])
    page, cursor = conn.fetch_products(None)
    assert page == [] and cursor is None


# ── changesSince ────────────────────────────────────────────────────

def test_changes_since_filters_by_watermark():
    conn = make_connector()
    changed, cursor = conn.read_changes_since("product", "2026-01-03T00:00:00", None)
    skus = {r["sku"] for r in changed}
    while cursor:
        page, cursor = conn.read_changes_since("product", "2026-01-03T00:00:00", cursor)
        skus |= {r["sku"] for r in page}
    assert "GLV-NIT-L" not in skus   # 2026-01-01 — before watermark
    assert "PPR-A4-80" not in skus   # 2026-01-02 — before watermark
    assert "TWL-HND" in skus         # 2026-01-05 — after watermark


def test_changes_since_unsupported_type_raises():
    conn = make_connector()
    with pytest.raises(ConnectorError):
        conn.read_changes_since("invoice", "2026-01-01T00:00:00", None)


# ── Capabilities shape ──────────────────────────────────────────────

def test_capabilities_shape():
    caps = make_connector().discover_capabilities()
    assert caps["provider_code"] == "mockerp"
    assert caps["adapter_version"]
    for key in ("products", "suppliers", "org_dimensions", "locations", "supplier_product", "changes_since"):
        assert isinstance(caps["reads"][key], bool)
    assert caps["writes"]["create_purchase_order"] is True


def test_base_connector_defaults_are_conservative():
    """A connector that doesn't override capabilities declares reads.products only."""
    from provisioning_service.core.connectors.base import BaseConnector

    class Minimal(BaseConnector):
        provider_code = "minimal"
        def test_connection(self):
            return True, "ok"
        def fetch_products(self, cursor):
            return [], None

    caps = Minimal({}, {}).discover_capabilities()
    assert caps["writes"]["create_purchase_order"] is False
    assert caps["reads"]["products"] is True
    assert caps["reads"]["suppliers"] is False


# ── Envelope evidence ───────────────────────────────────────────────

def test_envelope_hash_stable():
    raw = {"sku": "GLV-NIT-L", "price": 8.5, "nested": {"a": 1, "b": [2, 3]}}
    assert content_hash(raw) == content_hash(dict(raw))
    # Key order must not matter
    reordered = {"nested": {"b": [2, 3], "a": 1}, "price": 8.5, "sku": "GLV-NIT-L"}
    assert content_hash(raw) == content_hash(reordered)


def test_envelope_fields():
    raw = {"id": "42", "sku": "X"}
    env = build_envelope(
        raw=raw, object_type="product", external_id="42",
        connection_id="conn-1", provider_code="mockerp",
        adapter_version="1.0.0", correlation_id="corr-1",
    )
    assert env.payload_hash == content_hash(raw)
    assert env.raw_payload == raw
    assert env.correlation_id == "corr-1"
    assert env.envelope_id


# ── Governed write idempotency ──────────────────────────────────────

def test_create_po_idempotent_under_retry():
    conn = make_connector()
    po = {"order_id": "PO-1", "lines": [{"sku": "GLV-NIT-L", "quantity": 2, "unit_price_minor": 850}]}
    first = conn.create_purchase_order(po, idempotency_key="key-123")
    second = conn.create_purchase_order(po, idempotency_key="key-123")
    assert first["mock_id"] == second["mock_id"]
    assert second["idempotent_replay"] is True
    assert len(conn.config["_po_store"]) == 1


def test_create_po_requires_key():
    with pytest.raises(ConnectorError):
        make_connector().create_purchase_order({}, idempotency_key="")


# ── Failure injection + retry classification ────────────────────────

def test_injected_page_failure_raises():
    conn = make_connector(fail_on_page=2)
    page, cursor = conn.fetch_products(None)
    assert len(page) == PAGE_SIZE
    with pytest.raises(ConnectorError):
        conn.fetch_products(cursor)


def test_auth_failure():
    ok, msg = make_connector(fail_auth=True).test_connection()
    assert not ok and "authentication" in msg.lower()


def test_classify_error():
    assert classify_error(Exception("401 Unauthorized")) == "auth"
    assert classify_error(Exception("token rejected by provider")) == "auth"
    assert classify_error(Exception("request timed out")) == "transient"
    assert classify_error(Exception("HTTP 503 Service Unavailable")) == "transient"
    assert classify_error(Exception("normalize: missing sku")) == "data_quality"
    assert classify_error(Exception("something else entirely")) == "permanent"
