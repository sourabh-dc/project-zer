import httpx

AIFI_BASE_URL="https://oasis-api.27-12.oasis.aifi.com"
AIFI_API_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzaG9wIjoiY29uc3VtYWJsZXMtZ2IiLCJ0b2tlblR5cGUiOiJBRE1JTiIsImlhdCI6MTc0ODQ1MTk4Nn0.aR81DfOnjtCOIq0spJiGGj0jmj_BTUQcz3jlQy37SMc"
AIFI_STORE_ID="consumables-gb"
AIFI_LOCATION_ID="1"
# Example endpoints for AiFi API (adjust based on your actual config)
PATH_CUSTOMERS = "/api/admin/v2/customers"
PATH_PRODUCTS = "/api/admin/v2/products"
PATH_ENTRY_CODES_CREATE = "/api/admin/v2/customers/{customerId}/entry-codes"

def get_headers():
    headers = {
        "Authorization": f"Bearer {AIFI_API_KEY}",
        "Content-Type": "application/json",
    }
    if AIFI_LOCATION_ID:
        headers["X-Location-Id"] = AIFI_LOCATION_ID
    return headers

async def test_aifi_connection():
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            print("\n🔍 Testing base connectivity...")
            # Try to get customers list as a connectivity test
            r = await client.get(f"{AIFI_BASE_URL}{PATH_CUSTOMERS}", headers=get_headers())
            print("✅ Connection successful:", r.status_code)
            if r.status_code == 200:
                print("Response:", r.text[:200] if len(r.text) > 200 else r.text)
            else:
                print("Response:", r.text)
        except Exception as e:
            print("❌ Connection test failed:", str(e))

async def cv_create_customer(customer_dict):
    async with httpx.AsyncClient(timeout=15.0) as client:
        payload = {
            "externalId": customer_dict["externalId"],
            "firstName": customer_dict["firstname"],
            "lastName": customer_dict["lastname"],
            "email": customer_dict["email"]
        }
        url = f"{AIFI_BASE_URL}{PATH_CUSTOMERS}"
        r = await client.post(url, headers=get_headers(), json=payload)
        print("\n👤 Create Customer Response:", r.status_code)

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
        r = await client.post(url, headers=get_headers(), json=payload)
        print("\n📦 Create Product Response:", r.status_code)


def cv_get_products():
    products = []
    offset = 0
    count = 50  # default page size

    with httpx.Client(timeout=15.0) as client:
        while True:
            url = f"{AIFI_BASE_URL}{PATH_PRODUCTS}?offset={offset}&count={count}"
            r = client.get(url, headers=get_headers())
            r.raise_for_status()
            data = r.json()

            # Add the current batch
            products.extend(data.get("products", []))

            # Check if there's a next page
            pagination = data.get("pagination", {})
            next_page = pagination.get("next")
            if next_page:
                offset = next_page.get("offset", 0)
                count = next_page.get("count", 50)
            else:
                break
    return products

def cv_get_customers():
    with httpx.Client(timeout=15.0) as client:
        url = f"{AIFI_BASE_URL}{PATH_CUSTOMERS}"
        r = client.get(url, headers=get_headers())
        r.raise_for_status()
        data = r.json()
        return data

def cv_delete_customer(customer_id):
    with httpx.Client(timeout=15.0) as client:
        url = f"{AIFI_BASE_URL}{PATH_CUSTOMERS}/{customer_id}"
        r = client.delete(url, headers=get_headers())
        print(r.status_code)

def cv_delete_product(product_id):
    with httpx.Client(timeout=15.0) as client:
        url = f"{AIFI_BASE_URL}{PATH_PRODUCTS}/{product_id}"
        r = client.delete(url, headers=get_headers())
        print(r.status_code)

async def generate_entry_code(customer_id):
    async with httpx.AsyncClient(timeout=15.0) as client:
        url = f"{AIFI_BASE_URL}{PATH_ENTRY_CODES_CREATE.format(customerId=customer_id)}"
        r = await client.post(url, headers=get_headers(), params={"displayable": "true"})
        print("\n🔑 Create Entry Code Response:", r.status_code)
        print("Response:", r.text)
