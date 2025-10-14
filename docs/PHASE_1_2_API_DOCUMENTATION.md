# ZeroQue V4.1 - Phase 1 & 2 API Documentation

**Version**: 4.1  
**Last Updated**: October 14, 2025  
**Base URLs**:

- Provisioning: `http://localhost:8000`
- Identity: `http://localhost:8003`
- CV Connector: `http://localhost:8216`
- CV Gateway: `http://localhost:8215`

---

## Table of Contents

- [Authentication](#authentication)
- [Phase 1: Identity & Access APIs](#phase-1-identity--access-apis)
  - [Bulk User Import](#bulk-user-import)
  - [OAuth/SSO Management](#oauthsso-management)
  - [Entry Methods](#entry-methods)
- [Phase 2: Sites & Hardware APIs](#phase-2-sites--hardware-apis)
  - [Site Registry](#site-registry)
  - [Device Monitoring](#device-monitoring)
- [Error Codes](#error-codes)
- [Rate Limits](#rate-limits)

---

## Authentication

All API endpoints require authentication using one of the following methods:

### API Key Authentication

```http
x-api-key: your_api_key_here
```

### JWT Bearer Token

```http
Authorization: Bearer your_jwt_token_here
```

### Demo Mode (Development Only)

```http
x-api-key: zq_demo_key_for_testing
```

**Note**: Demo mode bypasses RLS and permissions. Only use in development.

---

## Phase 1: Identity & Access APIs

### Bulk User Import

**Endpoint**: `POST /provisioning/users/bulk-import`  
**Service**: Provisioning  
**Feature**: Self-Service User Provisioning (Pro/Ent)  
**Permission**: `provisioning.bulk_import`

#### Request Body

```json
{
  "tenant_id": "string (UUID)",
  "users": [
    {
      "email": "string (required)",
      "display_name": "string (required)",
      "permissions": ["string"] // optional
    }
  ],
  "auto_generate_api_keys": boolean,  // default: false
  "notify_users": boolean              // default: true
}
```

#### Response (200 OK)

```json
{
  "saga_id": "string",
  "tenant_id": "string",
  "total_requested": integer,
  "success_count": integer,
  "failed_count": integer,
  "results": {
    "success": [
      {
        "user_id": "string (UUID)",
        "email": "string",
        "api_key": "string" // if auto_generate_api_keys: true
      }
    ],
    "failed": [
      {
        "email": "string",
        "error": "string"
      }
    ]
  }
}
```

#### Example

```bash
curl -X POST http://localhost:8000/provisioning/users/bulk-import \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "users": [
      {
        "email": "alice@company.com",
        "display_name": "Alice Johnson",
        "permissions": ["catalog.view", "orders.create"]
      },
      {
        "email": "bob@company.com",
        "display_name": "Bob Smith"
      }
    ],
    "auto_generate_api_keys": true
  }'
```

#### Error Responses

- `400 Bad Request`: Invalid request body or user limit exceeded
- `403 Forbidden`: Missing `provisioning.bulk_import` permission
- `500 Internal Server Error`: Saga execution failed

---

### OAuth/SSO Management

#### Create OAuth Provider

**Endpoint**: `POST /identity/v4/oauth/providers`  
**Service**: Identity  
**Feature**: SSO/OAuth Login (Pro/Ent)  
**Permission**: `identity.oauth_admin`

##### Request Body

```json
{
  "tenant_id": "string (UUID)",
  "provider_type": "azure_ad | google | okta | auth0",
  "provider_name": "string",
  "client_id": "string",
  "client_secret": "string",
  "tenant_domain": "string", // optional, for Azure AD
  "discovery_url": "string", // optional, OIDC discovery endpoint
  "scopes": ["openid", "profile", "email"], // default
  "config_metadata": {} // optional
}
```

##### Response (200 OK)

```json
{
  "provider_id": "string (UUID)",
  "tenant_id": "string",
  "provider_type": "string",
  "provider_name": "string",
  "enabled": boolean,
  "created_at": "ISO 8601 timestamp"
}
```

##### Example

```bash
curl -X POST http://localhost:8003/identity/v4/oauth/providers \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "provider_type": "azure_ad",
    "provider_name": "Company Azure AD",
    "client_id": "azure-client-id-here",
    "client_secret": "azure-client-secret-here",
    "tenant_domain": "company.onmicrosoft.com",
    "scopes": ["openid", "profile", "email"]
  }'
```

---

#### List OAuth Providers

**Endpoint**: `GET /identity/v4/oauth/providers`  
**Service**: Identity

##### Query Parameters

- `tenant_id` (required): Tenant UUID

##### Response (200 OK)

```json
{
  "tenant_id": "string",
  "providers": [
    {
      "provider_id": "string (UUID)",
      "provider_type": "string",
      "provider_name": "string",
      "enabled": boolean,
      "created_at": "ISO 8601 timestamp"
    }
  ]
}
```

##### Example

```bash
curl -X GET "http://localhost:8003/identity/v4/oauth/providers?tenant_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "x-api-key: zq_demo_key_for_testing"
```

---

#### Initiate OAuth Flow

**Endpoint**: `POST /identity/v4/oauth/initiate`  
**Service**: Identity

##### Request Body

```json
{
  "tenant_id": "string (UUID)",
  "provider_id": "string (UUID)",
  "redirect_uri": "string" // where to redirect after auth
}
```

##### Response (200 OK)

```json
{
  "session_id": "string (UUID)",
  "authorization_url": "string", // redirect user to this URL
  "state": "string", // OAuth state parameter
  "expires_at": "ISO 8601 timestamp"
}
```

##### Example

```bash
curl -X POST http://localhost:8003/identity/v4/oauth/initiate \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "provider_id": "660e8400-e29b-41d4-a716-446655440001",
    "redirect_uri": "https://app.company.com/auth/callback"
  }'
```

---

#### OAuth Callback

**Endpoint**: `POST /identity/v4/oauth/callback`  
**Service**: Identity

##### Request Body

```json
{
  "state": "string", // from initiate response
  "code": "string", // authorization code from provider
  "error": "string", // optional, if auth failed
  "error_description": "string" // optional
}
```

##### Response (200 OK)

```json
{
  "success": boolean,
  "user_id": "string (UUID)",
  "email": "string",
  "token": "string (JWT)",
  "provider": "string"
}
```

##### Example

```bash
curl -X POST http://localhost:8003/identity/v4/oauth/callback \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "state": "oauth-state-from-initiate",
    "code": "authorization-code-from-azure"
  }'
```

---

### Entry Methods

#### QR Code Entry

**Endpoint**: `POST /cv/entry/qr`  
**Service**: CV Connector  
**Feature**: QR Entry (All Tiers)  
**Permission**: `cv.read`

##### Request Body

```json
{
  "tenant_id": "string (UUID)",
  "user_id": "string (UUID)",
  "provider": "string",        // optional, default: aifi
  "group_size": integer,       // optional, default: 1
  "displayable": boolean,      // optional, default: true
  "extra": {}                  // optional
}
```

##### Response (200 OK)

```json
{
  "qr_image": "string (base64)",
  "entry_code": {
    "code": "string",
    "id": "string",
    "expires_at": "ISO 8601 timestamp"
  },
  "expires_at": "ISO 8601 timestamp"
}
```

##### Example

```bash
curl -X POST http://localhost:8216/cv/entry/qr \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "660e8400-e29b-41d4-a716-446655440001",
    "group_size": 1,
    "displayable": true
  }'
```

---

#### Card Entry

**Endpoint**: `POST /cv/entry/card`  
**Service**: CV Connector  
**Feature**: Card Entry (All Tiers) - NEW in Phase 1.3  
**Permission**: `cv.entry`

##### Request Body

```json
{
  "tenant_id": "string (UUID)",
  "user_id": "string (UUID)",
  "store_id": "string (UUID)",
  "card_number": "string", // last 4 digits or encrypted full number
  "card_type": "rfid | nfc | magnetic",
  "device_id": "string", // optional
  "provider": "string" // optional
}
```

##### Response (200 OK)

```json
{
  "success": boolean,
  "entry_code": "string",
  "session_id": "string",
  "entry_method": "card",
  "card_type": "string",
  "expires_at": "ISO 8601 timestamp"
}
```

##### Example

```bash
curl -X POST http://localhost:8216/cv/entry/card \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "660e8400-e29b-41d4-a716-446655440001",
    "store_id": "770e8400-e29b-41d4-a716-446655440002",
    "card_number": "1234567890",
    "card_type": "rfid",
    "device_id": "entry-device-01"
  }'
```

---

#### Biometric Entry

**Endpoint**: `POST /cv/entry/biometric`  
**Service**: CV Connector  
**Feature**: Biometric Entry (All Tiers) - NEW in Phase 1.3  
**Permission**: `cv.entry`

##### Request Body

```json
{
  "tenant_id": "string (UUID)",
  "user_id": "string (UUID)",
  "store_id": "string (UUID)",
  "biometric_type": "fingerprint | face | palm | iris",
  "biometric_data": "string (base64 hash)",
  "device_id": "string",            // optional
  "confidence_score": float,        // 0.0-1.0, optional
  "provider": "string"              // optional
}
```

##### Response (200 OK)

```json
{
  "success": boolean,
  "entry_code": "string",
  "session_id": "string",
  "entry_method": "biometric",
  "biometric_type": "string",
  "confidence_score": float,
  "expires_at": "ISO 8601 timestamp"
}
```

##### Validation Rules

- `confidence_score` must be >= 0.85 (85%)
- `biometric_data` should be a hash, never full biometric template

##### Example

```bash
curl -X POST http://localhost:8216/cv/entry/biometric \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "660e8400-e29b-41d4-a716-446655440001",
    "store_id": "770e8400-e29b-41d4-a716-446655440002",
    "biometric_type": "face",
    "biometric_data": "base64_encoded_face_hash_here",
    "confidence_score": 0.95,
    "device_id": "biometric-scanner-01"
  }'
```

---

## Phase 2: Sites & Hardware APIs

### Site Registry

#### Create/Update Site with Device Metadata

**Endpoint**: `PUT /provisioning/sites/{site_id}`  
**Service**: Provisioning  
**Feature**: Site Registry with Device Metadata (All Tiers) - NEW in Phase 2.1

##### Query Parameters

- `tenant_id` (required): Tenant UUID

##### Request Body

```json
{
  "name": "string",
  "site_type": "retail | office | warehouse", // default: office
  "geo": {                                    // optional
    "lat": float,
    "lon": float
  },
  "device_metadata": {                        // NEW in Phase 2.1
    "cameras": [
      {
        "id": "string",
        "type": "string",
        "zone": "string",
        "...": "additional metadata"
      }
    ],
    "sensors": [
      {
        "id": "string",
        "type": "string",
        "zone": "string",
        "...": "additional metadata"
      }
    ],
    "entry_devices": [
      {
        "id": "string",
        "type": "string",
        "...": "additional metadata"
      }
    ]
  }
}
```

##### Response (200 OK)

```json
{
  "site_id": "string (UUID)",
  "name": "string",
  "created": boolean
}
```

##### Example

```bash
curl -X PUT "http://localhost:8000/provisioning/sites/880e8400-e29b-41d4-a716-446655440003?tenant_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Downtown Store",
    "site_type": "retail",
    "geo": {"lat": 40.7128, "lon": -74.0060},
    "device_metadata": {
      "cameras": [
        {"id": "cam-01", "type": "overhead", "zone": "checkout", "resolution": "4K"},
        {"id": "cam-02", "type": "entrance", "zone": "entry", "resolution": "1080p"}
      ],
      "sensors": [
        {"id": "sensor-01", "type": "motion", "zone": "entry"}
      ],
      "entry_devices": [
        {"id": "entry-01", "type": "rfid_reader"}
      ]
    }
  }'
```

---

### Device Monitoring

#### List Devices

**Endpoint**: `GET /devices/status`  
**Service**: CV Gateway  
**Feature**: Device Monitoring (All Tiers) - NEW in Phase 2.2

##### Query Parameters

- `tenant_id` (required): Tenant UUID
- `site_id` (optional): Filter by site
- `status` (optional): Filter by status (online, offline, error, maintenance)

##### Response (200 OK)

```json
{
  "tenant_id": "string",
  "site_id": "string or null",
  "status_filter": "string or null",
  "total_devices": integer,
  "devices": [
    {
      "device_id": "string",
      "tenant_id": "string",
      "site_id": "string or null",
      "device_type": "camera | sensor | entry_device",
      "device_name": "string",
      "zone": "string or null",
      "status": "online | offline | error | maintenance",
      "health_score": integer or null, // 0-100
      "last_heartbeat": "ISO 8601 timestamp or null",
      "device_metadata": {},
      "created_at": "ISO 8601 timestamp"
    }
  ]
}
```

##### Example

```bash
# List all devices for tenant
curl -X GET "http://localhost:8215/devices/status?tenant_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "x-api-key: zq_demo_key_for_testing"

# Filter by site and status
curl -X GET "http://localhost:8215/devices/status?tenant_id=550e8400-e29b-41d4-a716-446655440000&site_id=880e8400-e29b-41d4-a716-446655440003&status=online" \
  -H "x-api-key: zq_demo_key_for_testing"
```

---

#### Get Device Status

**Endpoint**: `GET /devices/{device_id}/status`  
**Service**: CV Gateway

##### Query Parameters

- `tenant_id` (required): Tenant UUID

##### Response (200 OK)

```json
{
  "device_id": "string",
  "tenant_id": "string",
  "site_id": "string or null",
  "device_type": "string",
  "device_name": "string",
  "zone": "string or null",
  "status": "string",
  "health_score": integer or null,
  "last_heartbeat": "ISO 8601 timestamp or null",
  "device_metadata": {},
  "recent_logs": [
    {
      "status": "string",
      "health_score": integer or null,
      "details": {},
      "created_at": "ISO 8601 timestamp"
    }
  ],
  "open_alerts": [
    {
      "alert_type": "string",
      "severity": "info | warning | critical",
      "message": "string",
      "status": "string",
      "created_at": "ISO 8601 timestamp"
    }
  ]
}
```

##### Example

```bash
curl -X GET "http://localhost:8215/devices/cam-01/status?tenant_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "x-api-key: zq_demo_key_for_testing"
```

---

#### Update Device Status

**Endpoint**: `PUT /devices/{device_id}/status`  
**Service**: CV Gateway  
**Note**: Called by devices to report health or by monitoring system

##### Query Parameters

- `tenant_id` (required): Tenant UUID

##### Request Body

```json
{
  "status": "online | offline | error | maintenance",
  "health_score": integer, // 0-100, optional
  "details": {}            // optional
}
```

##### Response (200 OK)

```json
{
  "success": boolean,
  "device_id": "string",
  "old_status": "string",
  "new_status": "string",
  "health_score": integer or null,
  "updated_at": "ISO 8601 timestamp"
}
```

##### Auto-Alert Generation

- Status changes to `offline` or `error` automatically create alerts
- Alert severity: `critical` for error, `warning` for offline

##### Example

```bash
curl -X PUT "http://localhost:8215/devices/cam-01/status?tenant_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "online",
    "health_score": 95,
    "details": {"temperature": 22.5, "uptime_hours": 168}
  }'
```

---

#### Create Device Alert

**Endpoint**: `POST /devices/{device_id}/alert`  
**Service**: CV Gateway

##### Query Parameters

- `tenant_id` (required): Tenant UUID

##### Request Body

```json
{
  "alert_type": "offline | error | low_health",
  "severity": "info | warning | critical", // default: warning
  "message": "string"
}
```

##### Response (200 OK)

```json
{
  "success": boolean,
  "device_id": "string",
  "alert_type": "string",
  "severity": "string",
  "message": "string",
  "created_at": "ISO 8601 timestamp"
}
```

##### Example

```bash
curl -X POST "http://localhost:8215/devices/cam-01/alert?tenant_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "x-api-key: zq_demo_key_for_testing" \
  -H "Content-Type: application/json" \
  -d '{
    "alert_type": "low_health",
    "severity": "warning",
    "message": "Camera health score dropped below 95%"
  }'
```

---

## Error Codes

### Standard HTTP Status Codes

| Code | Meaning               | Description                        |
| ---- | --------------------- | ---------------------------------- |
| 200  | OK                    | Request successful                 |
| 400  | Bad Request           | Invalid request body or parameters |
| 401  | Unauthorized          | Missing or invalid authentication  |
| 403  | Forbidden             | Insufficient permissions           |
| 404  | Not Found             | Resource not found                 |
| 409  | Conflict              | Resource already exists            |
| 429  | Too Many Requests     | Rate limit exceeded                |
| 500  | Internal Server Error | Server error                       |

### Error Response Format

```json
{
  "detail": "Error message describing what went wrong"
}
```

---

## Rate Limits

### Per-Tier Limits

| Tier       | Requests/Minute | Burst |
| ---------- | --------------- | ----- |
| Core       | 60              | 120   |
| Pro        | 300             | 600   |
| Enterprise | 1000            | 2000  |

### Rate Limit Headers

```http
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1697234567
```

---

## Webhooks & Events

### Event Types Published

#### Phase 1

- `USER_CREATED`: Published when users are created (bulk or single)
  - Queue: `cv_connector_events`
  - Consumer: CV Connector → syncs to AiFi

#### Phase 2

- `SITE_CREATED`: Published when sites are created with devices

  - Queue: `cv_gateway_events`
  - Consumer: CV Gateway → creates device registry

- `DEVICE_STATUS`: Published when device status changes (offline/error)
  - Queue: `notifications_events`
  - Consumer: Notifications → sends alerts

---

## SDK & Client Libraries

### Python

```python
import requests

class ZeroQueClient:
    def __init__(self, api_key, base_url="http://localhost:8000"):
        self.api_key = api_key
        self.base_url = base_url

    def bulk_import_users(self, tenant_id, users):
        response = requests.post(
            f"{self.base_url}/provisioning/users/bulk-import",
            headers={"x-api-key": self.api_key},
            json={"tenant_id": tenant_id, "users": users}
        )
        return response.json()

client = ZeroQueClient("your_api_key")
result = client.bulk_import_users("tenant-id", [...])
```

### cURL

See examples throughout this documentation.

### Postman Collection

Download: `/docs/ZeroQue_Phase1_Phase2.postman_collection.json`

---

## Support & Resources

- **Documentation**: `/docs/FEATURE_IMPLEMENTATION_PROGRESS.md`
- **Test Scripts**: `/tests/test_phase1_phase2.sh`
- **Migration Guide**: `/alembic/versions/add_phase1_phase2_features.py`
- **Health Checks**:
  - Provisioning: `http://localhost:8000/health`
  - Identity: `http://localhost:8003/health`
  - CV Connector: `http://localhost:8216/health`
  - CV Gateway: `http://localhost:8215/health`

---

**Version**: 4.1  
**Last Updated**: October 14, 2025  
**Next Update**: Phase 3 APIs
