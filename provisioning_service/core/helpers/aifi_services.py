import httpx
from typing import Dict, List, Tuple

AIFI_BASE_URL="https://oasis-api.27-12.oasis.aifi.com"
AIFI_API_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzaG9wIjoiY29uc3VtYWJsZXMtZ2IiLCJ0b2tlblR5cGUiOiJBRE1JTiIsImlhdCI6MTc0ODQ1MTk4Nn0.aR81DfOnjtCOIq0spJiGGj0jmj_BTUQcz3jlQy37SMc"
AIFI_STORE_ID="consumables-gb"
AIFI_LOCATION_ID="1"

# Admin API endpoints
PATH_CUSTOMERS = "/api/admin/v2/customers"
PATH_PRODUCTS = "/api/admin/v2/products"
PATH_ENTRY_CODES_CREATE = "/api/admin/v2/customers/{customerId}/entry-codes"
PATH_SESSIONS = "/api/admin/v2/sessions"
PATH_ORDERS = "/api/admin/v2/orders"
PATH_ORDER_DETAIL = "/api/admin/v2/orders/{orderId}"
PATH_CHECKOUTS = "/api/aifi/checkouts"
PATH_CUSTOMERS_ENTERED = "/api/aifi/customers/entered"
PATH_CUSTOMERS_WALKED_OUT = "/api/aifi/customers/walked-out"
PATH_REGISTER_WITH_TOKEN = "/api/aifi/customers/register-with-token"
PATH_ENTRY_CODE_VERIFY = "/api/aifi/entry-codes/verify"


def _headers() -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {AIFI_API_KEY}",
        "Content-Type": "application/json",
    }
    if AIFI_LOCATION_ID:
        headers["X-Location-Id"] = AIFI_LOCATION_ID
    return headers


async def test_aifi_connection() -> Tuple[bool, str]:
    """Lightweight connectivity check against products endpoint."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{AIFI_BASE_URL}{PATH_PRODUCTS}?count=1", headers=_headers())
            if resp.status_code == 200:
                return True, "ok"
            return False, f"status={resp.status_code}, body={resp.text[:200]}"
        except Exception as exc:
            return False, str(exc)


# ---------- Products ----------
async def fetch_products() -> List[Dict]:
    """Fetch all products from AiFi (paginated)."""
    products: List[Dict] = []
    offset = 0
    count = 100
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            url = f"{AIFI_BASE_URL}{PATH_PRODUCTS}?offset={offset}&count={count}"
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
            products.extend(data.get("products", []))
            pagination = data.get("pagination", {})
            nxt = pagination.get("next")
            if nxt:
                offset = nxt.get("offset", 0)
                count = nxt.get("count", count)
            else:
                break
    return products


# ---------- Orders (Admin) ----------
async def fetch_orders(offset: int = 0, count: int = 20, status: str = None) -> Dict:
    """Fetch orders from AiFi Admin API."""
    params = {"offset": offset, "count": count}
    if status:
        params["status"] = status
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{AIFI_BASE_URL}{PATH_ORDERS}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def fetch_order_detail(order_id: str) -> Dict:
    """Fetch a single order detail from AiFi Admin API."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{AIFI_BASE_URL}{PATH_ORDER_DETAIL.format(orderId=order_id)}", headers=_headers())
        resp.raise_for_status()
        return resp.json()


def build_product_payload(product, store_prices: List[Dict] = None) -> Dict:
    """Map local product model to AiFi product payload."""
    price_minor = getattr(product, "base_price_minor", 0) or 0
    price_str = f"{price_minor/100:.2f}"
    # AiFi expects storeId numeric; until we map store IDs, send empty storePrices to avoid 422s.
    store_prices = []  # ignore incoming store_prices until mapping is defined
    return {
        "externalId": str(product.product_id),
        "name": product.name,
        "barcode": product.barcode,
        "sku": product.sku,
        "price": price_str,
        "weight": f"{float(product.weight):.3f}" if getattr(product, "weight", None) is not None else "0.00",
        "restricted": bool(getattr(product, "restricted", False)),
        "thumbnail": getattr(product, "thumbnail", None),
        "invalidThumbnail": bool(getattr(product, "invalid_thumbnail", False)),
        "storePrices": store_prices,
    }


async def create_product(payload: Dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_PRODUCTS}",
            headers=_headers(),
            params={"externalId": payload.get("externalId")},
            json=payload,
        )


async def update_product(product_id: str, payload: Dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20.0) as client:
        return await client.put(
            f"{AIFI_BASE_URL}{PATH_PRODUCTS}/{product_id}",
            headers=_headers(),
            json=payload,
        )


async def delete_product(product_id: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.delete(
            f"{AIFI_BASE_URL}{PATH_PRODUCTS}/{product_id}",
            headers=_headers(),
        )


async def upsert_product(product, existing_by_external: Dict[str, Dict], store_prices: List[Dict] = None) -> Dict:
    payload = build_product_payload(product, store_prices=store_prices)
    ext = payload["externalId"]
    remote_id = getattr(product, "aifi_product_id", None)

    # Prefer stored AiFi id if present
    if remote_id:
        resp = await update_product(str(remote_id), payload)
        return {
            "externalId": ext,
            "status": "updated",
            "status_code": resp.status_code,
            "body": resp.text[:200],
            "remote_id": remote_id,
        }

    # Fallback to externalId lookup if we don't have stored id
    if ext in existing_by_external:
        remote = existing_by_external[ext]
        remote_id = remote.get("id") or remote.get("productId")
        if not remote_id:
            return {"externalId": ext, "status": "skip", "reason": "missing_remote_id"}
        resp = await update_product(str(remote_id), payload)
        return {
            "externalId": ext,
            "status": "updated",
            "status_code": resp.status_code,
            "body": resp.text[:200],
            "remote_id": remote_id,
        }
    resp = await create_product(payload)
    try:
        remote_id = resp.json().get("id")
    except Exception:
        remote_id = None
    return {
        "externalId": ext,
        "status": "created",
        "status_code": resp.status_code,
        "body": resp.text[:200],
        "remote_id": remote_id,
    }


# ---------- Customers (Users) ----------
async def fetch_customers() -> List[Dict]:
    """Fetch customers list."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{AIFI_BASE_URL}{PATH_CUSTOMERS}", headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("customers", [])
        return data


def build_customer_payload(user) -> Dict:
    phone = user.phone or "+10000000000"  # fallback valid-looking phone
    return {
        "externalId": str(user.user_id),
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "phone": phone,
        "role": "customer",
        "metadata": {},
    }


async def create_customer(payload: Dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_CUSTOMERS}",
            headers=_headers(),
            params={"externalId": payload.get("externalId")},
            json=payload,
        )


async def patch_customer(customer_id: str, payload: Dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15.0) as client:
        # externalId must not be patched per AiFi validation
        payload = {k: v for k, v in payload.items() if k != "externalId"}
        return await client.patch(
            f"{AIFI_BASE_URL}{PATH_CUSTOMERS}/{customer_id}",
            headers=_headers(),
            json=payload,
        )


async def delete_customer(customer_id: str) -> httpx.Response:
    """Best-effort delete; if endpoint not supported, caller should handle errors."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.delete(
            f"{AIFI_BASE_URL}{PATH_CUSTOMERS}/{customer_id}",
            headers=_headers(),
        )


# ---------- Sessions / Checkout ----------
async def list_sessions(offset: int = 0, count: int = 20, direction: str = "desc", order_by: str = "id") -> Dict:
    params = {"offset": offset, "count": count, "direction": direction, "orderBy": order_by}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{AIFI_BASE_URL}{PATH_SESSIONS}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def update_session(session_id: str, suspected_fraud: bool = None, metadata: Dict = None) -> httpx.Response:
    body: Dict = {}
    if suspected_fraud is not None:
        body["suspectedFraud"] = suspected_fraud
    if metadata is not None:
        body["metadata"] = metadata
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.patch(
            f"{AIFI_BASE_URL}{PATH_SESSIONS}/{session_id}",
            headers=_headers(),
            json=body,
        )


def _store_headers(store: str = None, location: str = None) -> Dict[str, str]:
    h = _headers()
    if store or AIFI_STORE_ID:
        h["X-AIFI-Store"] = store or AIFI_STORE_ID
    if location or AIFI_LOCATION_ID:
        h["X-AIFI-LocationId"] = str(location or AIFI_LOCATION_ID)
    return h


async def create_checkout(status: str, session_id: str, transaction_id: int, products: List[Dict], store: str = None, location: str = None) -> httpx.Response:
    payload = {
        "status": status,
        "sessionId": session_id,
        "transactionId": transaction_id,
        "products": products,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_CHECKOUTS}",
            headers=_store_headers(store, location),
            json=payload,
        )


async def customer_entered(session_id: str, role: str = "customer", track_id: str = None, transaction_id: int = None, store: str = None, location: str = None) -> httpx.Response:
    payload = {"customer": {"sessionId": session_id, "role": role}}
    if track_id:
        payload["customer"]["trackId"] = track_id
    if transaction_id is not None:
        payload["customer"]["transactionId"] = transaction_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_CUSTOMERS_ENTERED}",
            headers=_store_headers(store, location),
            json=payload,
        )


async def customer_walked_out(session_id: str, role: str = "customer", track_id: str = None, transaction_id: int = None, store: str = None, location: str = None) -> httpx.Response:
    payload = {"customer": {"sessionId": session_id, "role": role}}
    if track_id:
        payload["customer"]["trackId"] = track_id
    if transaction_id is not None:
        payload["customer"]["transactionId"] = transaction_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_CUSTOMERS_WALKED_OUT}",
            headers=_store_headers(store, location),
            json=payload,
        )


async def register_with_token(token: str, email: str = None, first_name: str = None, last_name: str = None, zone_id: int = None, scanner_id: int = None, token_type: str = "SESSION_ID") -> httpx.Response:
    payload: Dict = {"token": token, "tokenType": token_type}
    if email:
        payload["email"] = email
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if zone_id is not None:
        payload["zoneId"] = zone_id
    if scanner_id is not None:
        payload["scannerId"] = scanner_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_REGISTER_WITH_TOKEN}",
            headers=_headers(),
            json=payload,
        )


async def verify_entry_code(code: str, store: str = None, location: str = None) -> httpx.Response:
    payload = {"code": code}
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.post(
            f"{AIFI_BASE_URL}{PATH_ENTRY_CODE_VERIFY}",
            headers=_store_headers(store, location),
            json=payload,
        )


async def upsert_customer(user, existing_by_external: Dict[str, Dict]) -> Dict:
    payload = build_customer_payload(user)
    ext = payload["externalId"]
    remote_id = getattr(user, "aifi_customer_id", None)

    # Prefer stored AiFi id if present
    if remote_id:
        resp = await patch_customer(str(remote_id), payload)
        return {
            "externalId": ext,
            "status": "updated",
            "status_code": resp.status_code,
            "body": resp.text[:200],
            "remote_id": remote_id,
        }

    # Fallback to externalId lookup if we don't have stored id
    if ext in existing_by_external:
        remote = existing_by_external[ext]
        remote_id = remote.get("id") or remote.get("customerId")
        if not remote_id:
            return {"externalId": ext, "status": "skip", "reason": "missing_remote_id"}
        resp = await patch_customer(str(remote_id), payload)
        return {
            "externalId": ext,
            "status": "updated",
            "status_code": resp.status_code,
            "body": resp.text[:200],
            "remote_id": remote_id,
        }
    resp = await create_customer(payload)
    try:
        remote_id = resp.json().get("id")
    except Exception:
        remote_id = None
    return {
        "externalId": ext,
        "status": "created",
        "status_code": resp.status_code,
        "body": resp.text[:200],
        "remote_id": remote_id,
    }


# ---------- Entry codes ----------
async def generate_entry_code(customer_id: str) -> Dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        url = f"{AIFI_BASE_URL}{PATH_ENTRY_CODES_CREATE.format(customerId=customer_id)}"
        resp = await client.post(url, headers=_headers(), params={"displayable": "true"})
        return {"status_code": resp.status_code, "body": resp.text}

async def cv_create_product(product_dict):
    async with httpx.AsyncClient(timeout=15.0) as client:
        payload = {
            "externalId": product_dict["externalId"],
            "name": product_dict["name"],
            "barcode": product_dict["barcode"],
            "price": product_dict["price"],
            "weight": product_dict["weight"],
            "thumbnail": product_dict["thumbnail"]
        }
        url = f"{AIFI_BASE_URL}{PATH_PRODUCTS}"
        r = await client.post(url, headers=_headers(), json=payload)
        return r.json()

async def cv_create_customer(customer_dict):
    async with httpx.AsyncClient(timeout=15.0) as client:
        payload = {
            "externalId": customer_dict["externalId"],
            "firstName": customer_dict["firstname"],
            "lastName": customer_dict["lastname"],
            "email": customer_dict["email"]
        }
        url = f"{AIFI_BASE_URL}{PATH_CUSTOMERS}"
        r = await client.post(url, headers=_headers(), json=payload)
        return r.json()