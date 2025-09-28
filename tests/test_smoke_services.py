import os
import requests

BASES = {
    'prov': os.getenv('PROV_BASE', 'http://localhost:8201'),
    'catalog': os.getenv('CATALOG_BASE', 'http://localhost:8202'),
    'entry': os.getenv('ENTRY_BASE', 'http://localhost:8204'),
    'orders': os.getenv('ORDERS_BASE', 'http://localhost:8208'),
    'identity': os.getenv('IDENTITY_BASE', 'http://localhost:8210'),
}

def _ok(r):
    return r.status_code < 300

def test_health_endpoints():
    for name, base in BASES.items():
        r = requests.get(f"{base}/health", timeout=5)
        assert _ok(r), f"{name} health failed: {r.status_code}"

def test_provisioning_flow_minimal():
    # tenant
    tid = 'tenant-test'
    r = requests.put(f"{BASES['prov']}/provisioning/tenants/{tid}", json={'name': 'Test'}, timeout=10)
    assert _ok(r)
    # site
    sid = 'site-test'
    r = requests.put(f"{BASES['prov']}/provisioning/sites/{sid}", json={'tenant_id': tid, 'name': 'S'}, timeout=10)
    assert _ok(r)
    # store
    stid = 'store-test'
    r = requests.put(f"{BASES['prov']}/provisioning/stores/{stid}", json={'site_id': sid, 'name': 'St'}, timeout=10)
    assert _ok(r)

def test_catalog_product_price():
    sku = 'SKU-T'
    r = requests.put(f"{BASES['catalog']}/catalog/products", json={'sku': sku, 'name': 'T'}, timeout=10)
    assert _ok(r)
    r = requests.put(f"{BASES['catalog']}/catalog/prices", json={'sku': sku, 'currency': 'GBP', 'unit_minor': 1, 'active': True}, timeout=10)
    assert _ok(r)


