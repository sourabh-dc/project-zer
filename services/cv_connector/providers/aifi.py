from .base import CVProvider, EntryVerifyResult, SyncResult
from ..config import settings
from ..util.http import client
from zeroque_common.db.session import SessionLocal
from sqlalchemy import text

def AIFI_HEADERS() -> dict:
    h = {
        "Authorization": f"Bearer {settings.AIFI_API_KEY}",
        "Content-Type": "application/json",
    }
    if settings.AIFI_LOCATION_ID:
        h["X-Location-Id"] = settings.AIFI_LOCATION_ID  # only if your tenant requires it
    return h

class AiFiProvider(CVProvider):
    name = "aifi"

    async def create_entry_code(self, payload: dict) -> dict:
        """
        Create an entry code for a registered AiFi customer (QR-ready).
        Expected payload: { "customerId": <int>, "displayable": true, ... optional body ... }
        We support resolving customerId by external mapping if only userExternalId is provided.
        """
        customer_id = payload.get("customerId")
        user_external_id = payload.get("userExternalId")
        displayable = payload.get("displayable", True)

        if not customer_id and user_external_id:
            with SessionLocal() as db:
                row = db.execute(text(
                    """
                    SELECT external_id FROM provider_mappings
                     WHERE provider='aifi' AND entity_type='user' AND local_id=:u
                     LIMIT 1
                    """
                ), {"u": user_external_id}).first()
            if not row:
                raise ValueError("aifi_customer_mapping_missing")
            customer_id = row[0]

        if not customer_id:
            raise ValueError("customerId_required")

        path = settings.AIFI_PATH_ENTRY_CODES_CREATE_TMPL.format(customerId=customer_id)
        params = {"displayable": str(displayable).lower()}
        body = payload.get("body") or {}

        async with client() as c:
            r = await c.post(
                f"{settings.AIFI_BASE_URL}{path}",
                headers=AIFI_HEADERS(), params=params, json=body
            )
        r.raise_for_status()
        return r.json()

    async def verify_entry_code(self, verification_code: str, *, store_id: int, entry_id: int,
                                group_size: int | None = None, check_in_device_id: int | None = None) -> EntryVerifyResult:
        path = settings.AIFI_PATH_ENTRY_CODES_VERIFY_TMPL.format(storeId=store_id, entryId=entry_id)
        body = {"verificationCode": verification_code}
        if group_size is not None:
            body["groupSize"] = group_size
        if check_in_device_id is not None:
            body["checkInDeviceId"] = check_in_device_id
        async with client() as c:
            r = await c.post(
                f"{settings.AIFI_BASE_URL}{path}",
                headers=AIFI_HEADERS(), json=body
            )
        r.raise_for_status()
        return EntryVerifyResult(r.json())

    async def push_customer(self, customer: dict) -> SyncResult:
        async with client() as c:
            r = await c.post(
                f"{settings.AIFI_BASE_URL}{settings.AIFI_PATH_CUSTOMERS}",
                headers=AIFI_HEADERS(), json=customer
            )
        ok = r.status_code in (200, 201)
        return SyncResult({"ok": ok, "status": r.status_code, "body": (ok and r.json()) or r.text})

    async def push_product(self, product: dict) -> SyncResult:
        async with client() as c:
            r = await c.post(
                f"{settings.AIFI_BASE_URL}{settings.AIFI_PATH_PRODUCTS_UPSERT}",
                headers=AIFI_HEADERS(), json=product
            )
        if r.status_code in (404, 405):
            async with client() as c:
                r = await c.post(
                    f"{settings.AIFI_BASE_URL}{settings.AIFI_PATH_PRODUCTS_CREATE}",
                    headers=AIFI_HEADERS(), json=product
                )
        ok = r.status_code in (200, 201)
        return SyncResult({"ok": ok, "status": r.status_code, "body": (ok and r.json()) or r.text})

    async def update_inventory(self, product_id: str, *, quantity_difference: int | None = None,
                               quantity: int | None = None) -> SyncResult:
        path = settings.AIFI_PATH_INVENTORY_UPDATE_TMPL.format(productId=product_id)
        body: dict = {}
        if quantity_difference is not None: body["quantityDifference"] = int(quantity_difference)
        if quantity is not None: body["quantity"] = int(quantity)
        params = {}
        if settings.AIFI_STORE_ID is not None: params["storeId"] = settings.AIFI_STORE_ID
        async with client() as c:
            r = await c.put(f"{settings.AIFI_BASE_URL}{path}", headers=AIFI_HEADERS(), json=body, params=params)
        ok = r.status_code in (200, 204)
        return SyncResult({"ok": ok, "status": r.status_code, "body": (ok and (r.text and r.json())) or r.text})

    # ---- adapters for inbound webhooks ----
    def adapt_entry_webhook_to_decision(self, payload: dict) -> dict:
        # Example: accept if payload.payment exists; customize for your policies
        ok = bool((payload or {}).get("payment"))
        return {"status": "OK" if ok else "FAILED", "reason": None if ok else "Payment verification failed"}

    def adapt_checkout_to_order(self, payload: dict) -> dict:
        customer = payload.get("customer") or {}
        store = payload.get("store") or {}
        cart = payload.get("cart") or []
        currency = ((payload.get("amount") or {}).get("currency") or "GBP").upper()

        items = []
        for it in cart:
            # map best-effort; cv_gateway will re-validate SKU + price internally
            sku = it.get("sku") or it.get("id") or it.get("barcode") or "UNKNOWN"
            qty = int(it.get("quantity", it.get("qty", 1)))
            # unit_price from provider not trusted; pass provider price_minor for diagnostics only
            items.append({"sku": sku, "name": it.get("name") or sku, "qty": qty, "price_minor": int(it.get("priceMinor", 0))})

        return {
            "provider_order_id": str(payload.get("orderId") or payload.get("id") or ""),
            "tenant_ext_id": None,
            "site_ext_id": None,
            "store_ext_id": str(payload.get("storeExternalId") or store.get("externalId") or ""),
            "user_ext_id": str(customer.get("externalId") or customer.get("id") or ""),

            "currency": currency,
            "items": items,
            "occurred_at": payload.get("timeOfOrigin") or payload.get("timeOfIssue"),
        }

    # ---- ensure/mapping helpers ----
    def resolve_mapping(self, entity_type: str, local_id: str) -> str | None:
        with SessionLocal() as db:
            row = db.execute(text(
                """
                SELECT external_id FROM provider_mappings
                 WHERE provider='aifi' AND entity_type=:et AND local_id=:lid
                 LIMIT 1
                """
            ), {"et": entity_type, "lid": local_id}).first()
            return row[0] if row else None

    def upsert_mapping(self, entity_type: str, local_id: str, external_id: str) -> None:
        with SessionLocal() as db:
            existing = db.execute(text(
                """
                SELECT id FROM provider_mappings
                 WHERE provider='aifi' AND entity_type=:et AND local_id=:lid
                 LIMIT 1
                """
            ), {"et": entity_type, "lid": local_id}).first()
            if existing:
                db.execute(text("UPDATE provider_mappings SET external_id=:eid WHERE id=:id"),
                           {"eid": external_id, "id": int(existing[0])})
            else:
                db.execute(text(
                    """
                    INSERT INTO provider_mappings(provider, entity_type, local_id, external_id)
                    VALUES('aifi', :et, :lid, :eid)
                    """
                ), {"et": entity_type, "lid": local_id, "eid": external_id})
            db.commit()

    async def ensure_customer(self, *, local_user_id: str, customer: dict | None = None) -> dict:
        """Ensure AiFi customer exists for our user and store mapping."""
        existing = self.resolve_mapping("user", local_user_id)
        if existing:
            return {"customerId": existing, "mapped": True}
        # create
        payload = customer or {"externalId": local_user_id}
        async with client() as c:
            r = await c.post(f"{settings.AIFI_BASE_URL}{settings.AIFI_PATH_CUSTOMERS}",
                             headers=AIFI_HEADERS(), json=payload)
        r.raise_for_status()
        body = r.json()
        cid = body.get("id") or body.get("customerId") or body.get("externalId")
        if not cid:
            raise ValueError("aifi_customer_id_missing_in_response")
        self.upsert_mapping("user", local_user_id, str(cid))
        return {"customerId": str(cid), "created": True}

    async def ensure_store(self, *, local_store_id: str, store: dict | None = None) -> dict:
        existing = self.resolve_mapping("store", local_store_id)
        if existing:
            return {"storeId": existing, "mapped": True}
        # create with thirdPartyId = our store_id so checkout webhooks include storeExternalId
        payload = store or {"thirdPartyId": local_store_id}
        async with client() as c:
            r = await c.post(f"{settings.AIFI_BASE_URL}{settings.AIFI_PATH_STORES}",
                             headers=AIFI_HEADERS(), json=payload)
        r.raise_for_status()
        body = r.json()
        sid = body.get("id") or body.get("storeId") or body.get("externalId")
        if not sid:
            raise ValueError("aifi_store_id_missing_in_response")
        self.upsert_mapping("store", local_store_id, str(sid))
        return {"storeId": str(sid), "created": True}