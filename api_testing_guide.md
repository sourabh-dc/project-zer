# ZeroQue API — Endpoint Testing Guide

> **Base URL**: `http://localhost:8001`  
> **Auth**: All endpoints except onboarding/login require `Authorization: Bearer <jwt_token>`  
> **Content-Type**: `application/json` (unless noted)

---

## Table of Contents

1. [Platform Setup (Internal)](#1-platform-setup-internal)
2. [Tenant Onboarding](#2-tenant-onboarding)
3. [Authentication](#3-authentication)
4. [Tenant Management](#4-tenant-management)
5. [Sites](#5-sites)
6. [Stores](#6-stores)
7. [Users](#7-users)
8. [Roles & Permissions](#8-roles--permissions)
9. [Tenant Roles](#9-tenant-roles)
10. [Org Units](#10-org-units)
11. [Vendors](#11-vendors)
12. [Cost Centres](#12-cost-centres)
13. [Catalog — Categories](#13-catalog--categories)
14. [Catalog — Products](#14-catalog--products)
15. [Catalog — Variants](#15-catalog--variants)
16. [Catalog — Store Products](#16-catalog--store-products)
17. [Approved Ranges](#17-approved-ranges)
18. [Financial Calendars](#18-financial-calendars)
19. [Budgets](#19-budgets)
20. [User Budgets](#20-user-budgets)
21. [Approval Policies](#21-approval-policies)
22. [Purchase Requests](#22-purchase-requests)
23. [Budget Change Requests](#23-budget-change-requests)
24. [Subscriptions](#24-subscriptions)
25. [Payments (Stripe)](#25-payments-stripe)
26. [Plans (Public)](#26-plans-public)

---

## 1. Platform Setup (Internal)

> These are **platform admin** endpoints. Run them first to seed roles, permissions, plans, and features before creating any tenant.

### 1.1 Create Permission

```
POST /internal/permissions
```
```json
{
  "code": "tenants.create",
  "name": "Create Tenants",
  "description": "Permission to create tenants"
}
```

### 1.2 List Permissions

```
GET /internal/permissions
```

### 1.3 Create Global Role

```
POST /internal/roles
```
```json
{
  "code": "tenant_admin",
  "description": "Full admin access to tenant"
}
```

### 1.4 Map Permission to Role

```
POST /internal/roles/map-permission
```
```json
{
  "role_code": "tenant_admin",
  "permission_code": "tenants.create"
}
```

### 1.5 Create Subscription Plan

```
POST /internal/plans
```
```json
{
  "code": "core_01",
  "name": "Core Plan",
  "description": "Basic plan for small businesses",
  "price_monthly_minor": 9900,
  "currency": "GBP",
  "quarterly_discount_pct": 5.0,
  "yearly_discount_pct": 10.0
}
```

### 1.6 Create Feature

```
POST /internal/features
```
```json
{
  "code": "products",
  "name": "Products",
  "description": "Number of products allowed",
  "cluster": "catalog",
  "usage_type": "count",
  "max_unit": "products",
  "reset_period": "monthly"
}
```

### 1.7 Map Feature to Plan

```
PUT /internal/plans/core_01/features/products
```
_No body required — just maps the feature to the plan._

### 1.8 List Plan Features

```
GET /internal/plans/core_01/features
```

### 1.9 List Roles

```
GET /internal/roles
```

### 1.10 Get Role Permissions

```
GET /internal/roles/tenant_admin/permissions
```

---

## 2. Tenant Onboarding

> No authentication required for these endpoints.

### 2.1 Generate OTP

```
POST /onboarding/otp/generate
```
```json
{
  "email": "admin@acmecorp.com"
}
```
_Sends a 6-digit OTP to the provided email._

### 2.2 Validate OTP

```
POST /onboarding/otp/validate
```
```json
{
  "email": "admin@acmecorp.com",
  "otp": "482917"
}
```

### 2.3 Tenant Signup

```
POST /onboarding/tenant-signup
```
```json
{
  "tenant_name": "Acme Corporation",
  "type": "customer",
  "registration_number": "REG-2026-001",
  "email": "contact@acmecorp.com",
  "billing_email": "billing@acmecorp.com",
  "admin_email": "admin@acmecorp.com",
  "admin_firstname": "John",
  "admin_lastname": "Smith",
  "password": "SecurePass1",
  "phone": "+447700900001",
  "active": true,
  "default_currency": "GBP",
  "timezone": "Europe/London",
  "locale": "en_GB",
  "billing_address": "123 Business Road, London, EC1A 1BB",
  "primary_domain": "acmecorp.com",
  "industry": "Retail",
  "tech_contact_email": "tech@acmecorp.com",
  "support_contact_email": "support@acmecorp.com"
}
```

**Response:**
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "status": "Signup initiated"
}
```

> 📌 **Save** `tenant_id` — you will need it for all subsequent requests.  
> The async worker creates the admin user, assigns `tenant_admin` role, and sends a welcome email.

### 2.4 Tenant Sign-In (Login)

```
POST /onboarding/tenant-signin
```
```json
{
  "email": "admin@acmecorp.com",
  "password": "SecurePass1"
}
```

**Response:**
```json
{
  "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "email": "admin@acmecorp.com",
  "display_name": "John Smith",
  "last_login_at": "2026-03-15T10:00:00+00:00",
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expiring_at": "2026-03-15T11:00:00+00:00",
  "refresh_token": "rt_a1b2c3d4e5f6..."
}
```

> 📌 **Save** `token` — use it as `Authorization: Bearer <token>` for all subsequent requests.  
> 📌 **Save** `refresh_token` — use it to get new tokens without re-logging in.  
> 📌 **Save** `user_id` — this is the admin user ID.

---

## 3. Authentication

### 3.1 Refresh JWT

```
POST /authentication/refresh-jwt
```
```json
{
  "user_id": "8ed16f26-80df-4028-8459-25d94f222dfb",
  "refresh_token": "rt_a1b2c3d4e5f6..."
}
```

### 3.2 Who Am I

```
GET /authentication/whoami
```
_Returns decoded JWT claims._

### 3.3 Logout

```
POST /authentication/logout
```
_No body required. Uses JWT from header._

### 3.4 Reset Password (Authenticated)

```
POST /authentication/reset-password
```
```json
{
  "current_password": "SecurePass1",
  "new_password": "NewSecurePass2"
}
```

### 3.5 Forgot Password (Request Reset Link)

```
POST /authentication/forgot-password
```
```json
{
  "email": "admin@acmecorp.com"
}
```
_Sends a password reset link to the email._

### 3.6 Confirm Password Reset

```
POST /authentication/reset-password/confirm
```
```json
{
  "token": "<reset_token_from_email>",
  "new_password": "ResetPass3"
}
```

### 3.7 Health Check

```
GET /authentication/healthcheck
```

---

## 4. Tenant Management

### 4.1 List Tenants

```
GET /provisioning/tenants
```

### 4.2 Get Tenant by ID

```
GET /provisioning/tenants/fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 4.3 Update Tenant

```
PUT /provisioning/tenants/fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "Acme Corporation Ltd",
  "type": "retailer",
  "registration_number": "REG-2026-001-A",
  "phone": "+447700900002",
  "active": "true"
}
```

### 4.4 Delete Tenant

```
DELETE /provisioning/tenants/fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 5. Sites

### 5.1 Create Site

```
POST /provisioning/sites
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "London Headquarters",
  "type": "campus",
  "active": true,
  "currency": "GBP",
  "timezone": "Europe/London",
  "language": "en",
  "phone": "+442071234567",
  "email": "hq@acmecorp.com",
  "url": "https://acmecorp.com",
  "is_headquarter": true,
  "primary_billing_address": {
    "line1": "123 Business Road",
    "city": "London",
    "postcode": "EC1A 1BB",
    "country": "GB"
  },
  "primary_shipping_address": {
    "line1": "123 Business Road",
    "city": "London",
    "postcode": "EC1A 1BB",
    "country": "GB"
  },
  "geo": {
    "lat": 51.5074,
    "lng": -0.1278
  }
}
```

> 📌 **Save** `site_id` from the response.

### 5.2 List Sites

```
GET /provisioning/sites?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 5.3 Get Site by ID

```
GET /provisioning/sites/{site_id}
```

### 5.4 Update Site

```
PUT /provisioning/sites/{site_id}
```
```json
{
  "name": "London HQ — Renovated",
  "phone": "+442071234999"
}
```

### 5.5 Delete Site (Soft)

```
DELETE /provisioning/sites/{site_id}
```

### 5.6 Map Site to Tenant

```
POST /provisioning/sites/{site_id}/tenants/fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 5.7 List Tenants for Site

```
GET /provisioning/sites/{site_id}/tenants
```

### 5.8 Unmap Site from Tenant

```
DELETE /provisioning/sites/{site_id}/tenants/fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 6. Stores

### 6.1 Create Store

```
POST /provisioning/stores
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "London Flagship Store",
  "store_type": "physical",
  "active": true,
  "site_id": "<site_id>",
  "currency": "GBP",
  "timezone": "Europe/London",
  "phone": "+442079876543",
  "email": "flagship@acmecorp.com",
  "url": "https://acmecorp.com/flagship",
  "fulfillment_mode": "both",
  "inventory_policy": "track_on_hand",
  "primary_shipping_address": {
    "line1": "456 High Street",
    "city": "London",
    "postcode": "W1A 0AX",
    "country": "GB"
  },
  "pickup_address": {
    "line1": "456 High Street, Rear Entrance",
    "city": "London",
    "postcode": "W1A 0AX",
    "country": "GB"
  },
  "geo": {
    "lat": 51.5155,
    "lng": -0.1419
  }
}
```

> 📌 **Save** `store_id` from the response.

### 6.2 List Stores

```
GET /provisioning/stores?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 6.3 Get Store by ID

```
GET /provisioning/stores/{store_id}
```

### 6.4 Update Store

```
PUT /provisioning/stores/{store_id}
```
```json
{
  "name": "London Flagship Store — Renovated",
  "fulfillment_mode": "pickup"
}
```

### 6.5 Delete Store (Soft)

```
DELETE /provisioning/stores/{store_id}
```

---

## 7. Users

### 7.1 Create User

```
POST /provisioning/users
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "email": "jane.doe@acmecorp.com",
  "password": "UserPass1",
  "first_name": "Jane",
  "last_name": "Doe",
  "phone": "+447700900100",
  "position": "Procurement Manager",
  "is_sso_enabled": false,
  "home_site_id": "<site_id>",
  "home_store_id": "<store_id>",
  "all_locations": false
}
```

> 📌 **Save** `user_id` from the response.

### 7.2 List Users

```
GET /provisioning/users?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 7.3 Get User by ID

```
GET /provisioning/users/{user_id}
```

### 7.4 Update User

```
PUT /provisioning/users/{user_id}
```
```json
{
  "position": "Senior Procurement Manager",
  "all_locations": true
}
```

### 7.5 Delete User (Soft)

```
DELETE /provisioning/users/{user_id}
```

### 7.6 Get User Budget Summary

```
GET /provisioning/users/{user_id}/budget
```

### 7.7 Get User Spending History

```
GET /provisioning/users/{user_id}/spending-history
```

### 7.8 Get User Subordinates

```
GET /provisioning/users/{user_id}/subordinates
```

---

## 8. Roles & Permissions

### 8.1 Create Role

```
POST /provisioning/roles
```
```json
{
  "code": "procurement_manager",
  "description": "Can create purchase requests and manage budgets"
}
```

> 📌 **Save** `role_id` from the response.

### 8.2 List Roles

```
GET /provisioning/roles
```

### 8.3 Map Permission to Role

```
POST /provisioning/roles/map-permission
```
```json
{
  "role_code": "procurement_manager",
  "permission_code": "catalog.products.view"
}
```

### 8.4 Remove Permission from Role

```
DELETE /provisioning/roles/delete-permission
```
```json
{
  "role_code": "procurement_manager",
  "permission_code": "catalog.products.view"
}
```

### 8.5 List Permissions

```
GET /provisioning/permissions
```

### 8.6 Get Role Permissions

```
GET /provisioning/roles/procurement_manager/permissions
```

### 8.7 Assign Role to User

```
POST /provisioning/users/{user_id}/roles
```
```json
{
  "role_id": "<role_id>"
}
```

### 8.8 List User Roles

```
GET /provisioning/users/{user_id}/roles
```

### 8.9 Remove Role from User

```
DELETE /provisioning/users/{user_id}/roles/{role_id}
```

---

## 9. Tenant Roles

> Tenant-scoped roles (custom roles per tenant, separate from global roles).

### 9.1 Create Tenant Role

```
POST /provisioning/tenant-roles
```
```json
{
  "code": "store_manager",
  "description": "Can manage store inventory and orders"
}
```

### 9.2 Add Permission to Tenant Role

```
POST /provisioning/tenant-roles/{role_id}/permissions
```
```json
{
  "permission_code": "catalog.products.manage"
}
```

### 9.3 Assign Tenant Role to User

```
POST /provisioning/users/{user_id}/tenant-roles
```
```json
{
  "role_id": "<tenant_role_id>"
}
```

### 9.4 List Tenant Roles

```
GET /provisioning/tenant-roles
```

---

## 10. Org Units

### 10.1 Create Org Unit

```
POST /provisioning/org_units
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "Procurement Division",
  "type": "department",
  "status": "active",
  "code": "PROC-001",
  "description": "Handles all procurement activities",
  "manager_user_id": "<admin_user_id>",
  "path": "/AcmeCorp/Procurement",
  "depth": 1
}
```

> 📌 **Save** `org_unit_id` from the response.

### 10.2 Create Child Org Unit

```
POST /provisioning/org_units
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "Office Supplies Team",
  "type": "team",
  "status": "active",
  "parent_org_unit_id": "<org_unit_id>",
  "code": "PROC-001-OS",
  "description": "Office supplies procurement team",
  "path": "/AcmeCorp/Procurement/OfficeSupplies",
  "depth": 2
}
```

### 10.3 List Org Units

```
GET /provisioning/org_units?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 10.4 Get Org Unit by ID

```
GET /provisioning/org_units/{org_unit_id}
```

### 10.5 Update Org Unit

```
PUT /provisioning/org_units/{org_unit_id}
```
```json
{
  "name": "Procurement & Sourcing Division",
  "description": "Updated description"
}
```

### 10.6 Delete Org Unit

```
DELETE /provisioning/org_units/{org_unit_id}
```

### 10.7 Assign User to Org Unit

```
POST /provisioning/org_units/assignments
```
```json
{
  "user_id": "<user_id>",
  "org_unit_id": "<org_unit_id>",
  "role_id": "<role_id>",
  "assigned_by": "<admin_user_id>"
}
```

### 10.8 List Users in Org Unit

```
GET /provisioning/org_units/{org_unit_id}/users
```

### 10.9 List Org Units for User

```
GET /provisioning/users/{user_id}/org_units
```

### 10.10 Remove User from Org Unit (by Assignment ID)

```
DELETE /provisioning/org_units/assignments/{assignment_id}
```

### 10.11 Remove User from Org Unit (by User + Org Unit)

```
DELETE /provisioning/org_units/{org_unit_id}/users/{user_id}
```

---

## 11. Vendors

### 11.1 Create Vendor

```
POST /provisioning/vendors
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "OfficeMax Supplies Ltd",
  "contact_email": "sales@officemax.co.uk",
  "description": "Office supplies and stationery vendor"
}
```

> 📌 **Save** `vendor_id` from the response.

### 11.2 List Vendors

```
GET /provisioning/vendors?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 11.3 Get Vendor by ID

```
GET /provisioning/vendors/{vendor_id}
```

### 11.4 Update Vendor

```
PUT /provisioning/vendors/{vendor_id}
```
```json
{
  "name": "OfficeMax Supplies International",
  "description": "Updated vendor description"
}
```

### 11.5 Delete Vendor (Soft)

```
DELETE /provisioning/vendors/{vendor_id}
```

### 11.6 Create Vendor User

```
POST /provisioning/vendor-user
```
```json
{
  "vendor_id": "<vendor_id>",
  "email": "rep@officemax.co.uk",
  "password_hash": "VendorPass1",
  "first_name": "Bob",
  "role": "vendor_admin",
  "active": true
}
```

### 11.7 List Vendor Users

```
GET /provisioning/vendor-user?vendor_id=<vendor_id>
```

---

## 12. Cost Centres

### 12.1 Create Cost Centre

```
POST /provisioning/cost-centres
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "code": "CC-PROC-001",
  "name": "Procurement Department Budget",
  "description": "Budget for the procurement division",
  "owner_user_id": "<admin_user_id>",
  "is_active": true,
  "fiscal_year": 2026,
  "period_type": "annual",
  "period_number": 1,
  "period_start": "2026-01-01",
  "period_end": "2026-12-31",
  "budget_amount_minor": 50000000,
  "created_by": "<admin_user_id>"
}
```

> 📌 **Save** `cost_centre_id` from the response.

### 12.2 List Cost Centres

```
GET /provisioning/cost-centres?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 12.3 Get Cost Centre by ID

```
GET /provisioning/cost-centres/{cost_centre_id}
```

### 12.4 Update Cost Centre

```
PUT /provisioning/cost-centres/{cost_centre_id}
```
```json
{
  "name": "Procurement Department Budget — Updated",
  "description": "Updated budget description"
}
```

### 12.5 Delete Cost Centre (Soft)

```
DELETE /provisioning/cost-centres/{cost_centre_id}
```

### 12.6 Assign User to Cost Centre

```
POST /provisioning/users/{user_id}/cost-centres
```
```json
{
  "cost_centre_id": "<cost_centre_id>",
  "allocated_budget_minor": 10000000
}
```

### 12.7 Renew User Budget

```
POST /provisioning/budgets/renew
```
```json
{
  "user_id": "<user_id>",
  "cost_centre_id": "<cost_centre_id>",
  "new_allocated_minor": 10000000
}
```

---

## 13. Catalog — Categories

### 13.1 Create Category

```
POST /catalog/categories
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "Office Supplies",
  "code": "OFF-SUP",
  "description": "General office supplies and stationery"
}
```

> 📌 **Save** `category_id` from the response.

### 13.2 Create Sub-Category

```
POST /catalog/categories
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "name": "Writing Instruments",
  "code": "OFF-SUP-WI",
  "description": "Pens, pencils, markers",
  "parent_category_id": "<category_id>"
}
```

### 13.3 List Categories

```
GET /catalog/categories?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 14. Catalog — Products

### 14.1 Create Product

```
POST /catalog/products
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "vendor_id": "<vendor_id>",
  "category_id": "<category_id>",
  "sku": "PEN-BLU-001",
  "ean": "5012345678901",
  "display_name": "Blue Ballpoint Pen (Pack of 50)",
  "sales_description": "Premium blue ballpoint pen, medium point, box of 50",
  "purchase_description": "BPP-50-BLU bulk order",
  "manufacturer": "PenCo International",
  "is_matrix_item": false,
  "matrix_type": "standalone",
  "purchase_price_minor": 1299,
  "currency": "GBP",
  "tax_rate": 2000,
  "weight": 0.5,
  "weight_unit": "kg",
  "outer_quantity": 10,
  "inner_quantity": 50,
  "reorder_multiple": 5,
  "product_type": "physical",
  "restricted": false,
  "search_keywords": "pen blue ballpoint writing office stationery",
  "product_metadata": {
    "colour": "blue",
    "point_size": "medium",
    "material": "plastic"
  }
}
```

> 📌 **Save** `product_id` from the response.

### 14.2 List Products

```
GET /catalog/products?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 14.3 Bulk Upload Products (Excel)

```
POST /catalog/products/bulk-upload
Content-Type: multipart/form-data
```
| Field | Value |
|-------|-------|
| `tenant_id` | `fd563534-0686-4afa-bdaf-b386fc33f2c2` |
| `file` | _(upload .xlsx file)_ |

---

## 15. Catalog — Variants

### 15.1 Create Variant

```
POST /catalog/variants
```
```json
{
  "product_id": "<product_id>",
  "sku": "PEN-BLU-001-M",
  "name": "Blue Pen — Medium Point",
  "attributes": {
    "colour": "blue",
    "point_size": "medium"
  },
  "price_minor": 1299,
  "currency": "GBP",
  "stock_quantity": 500,
  "low_stock_threshold": 50
}
```

---

## 16. Catalog — Store Products

### 16.1 Create Store Product

```
POST /catalog/store-products
```
```json
{
  "store_id": "<store_id>",
  "product_id": "<product_id>",
  "price_minor": 1499,
  "currency": "GBP",
  "is_available": true,
  "stock_quantity": 200,
  "low_stock_threshold": 20
}
```

### 16.2 List Store Products

```
GET /catalog/store-products?store_id=<store_id>
```

### 16.3 List Products for Store

```
GET /catalog/stores/{store_id}/products
```

---

## 17. Approved Ranges

> Approved Ranges define which products each org unit (department) can see and order.

### 17.1 Create Approved Range

```
POST /approved-ranges?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "name": "Office Supplies Q1 2026",
  "description": "Approved office supplies for Q1 2026",
  "is_universal": false
}
```

> 📌 **Save** `approved_range_id` from the response.

### 17.2 Map Approved Range to Org Unit(s)

```
POST /approved-ranges/{approved_range_id}/org-units?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "org_unit_ids": ["<org_unit_id>"]
}
```

### 17.3 Add Products to Approved Range

```
POST /approved-ranges/{approved_range_id}/products?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "product_ids": ["<product_id>"]
}
```

### 17.4 List Approved Ranges

```
GET /approved-ranges?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 17.5 Get Approved Range by ID

```
GET /approved-ranges/{approved_range_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 17.6 Update Approved Range

```
PUT /approved-ranges/{approved_range_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "name": "Office Supplies Q1-Q2 2026",
  "description": "Extended to Q2"
}
```

### 17.7 List Org Units for Range

```
GET /approved-ranges/{approved_range_id}/org-units?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 17.8 List Products in Range

```
GET /approved-ranges/{approved_range_id}/products?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 17.9 Remove Product from Range

```
DELETE /approved-ranges/{approved_range_id}/products/{product_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 17.10 Remove Org Unit from Range

```
DELETE /approved-ranges/{approved_range_id}/org-units/{org_unit_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 17.11 Delete Approved Range

```
DELETE /approved-ranges/{approved_range_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 18. Financial Calendars

### 18.1 Create Financial Calendar

```
POST /financial-calendars?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "name": "Acme FY2026 Calendar",
  "description": "Standard Gregorian financial calendar for FY2026",
  "calendar_type": "gregorian",
  "start_month": 1,
  "currency": "GBP",
  "is_default": true
}
```

> 📌 **Save** `calendar_id` from the response.

### 18.2 Create Financial Year

```
POST /financial-calendars/{calendar_id}/years?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "label": "FY2026",
  "start_date": "2026-01-01",
  "end_date": "2026-12-31",
  "year_type": "full",
  "total_budget_minor": 50000000,
  "notes": "Full financial year 2026"
}
```

> 📌 **Save** `year_id` from the response.

### 18.3 Activate Financial Year

```
PUT /financial-calendars/{calendar_id}/years/{year_id}/activate?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 18.4 Generate Periods (Auto)

```
POST /financial-calendars/{calendar_id}/years/{year_id}/generate-periods?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "period_type": "month"
}
```

### 18.5 Create Period (Manual)

```
POST /financial-calendars/{calendar_id}/years/{year_id}/periods?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "period_number": 1,
  "label": "January 2026",
  "period_type": "month",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31"
}
```

### 18.6 List Periods

```
GET /financial-calendars/{calendar_id}/years/{year_id}/periods?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 18.7 List Calendars

```
GET /financial-calendars?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 18.8 List Years

```
GET /financial-calendars/{calendar_id}/years?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 18.9 Close Financial Year

```
PUT /financial-calendars/{calendar_id}/years/{year_id}/close?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 18.10 Delete Calendar

```
DELETE /financial-calendars/{calendar_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 19. Budgets

### 19.1 Create Company Budget Cap

```
POST /budgets/company-caps?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "year_id": "<year_id>",
  "calendar_id": "<calendar_id>",
  "currency": "GBP",
  "total_budget_minor": 50000000,
  "hard_cap": false,
  "notes": "FY2026 company-wide budget cap"
}
```

> 📌 **Save** `cap_id` from the response.

### 19.2 List Company Budget Caps

```
GET /budgets/company-caps?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 19.3 Update Company Budget Cap

```
PUT /budgets/company-caps/{cap_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "total_budget_minor": 55000000,
  "notes": "Increased for Q3 expansion",
  "override_reason": "Board approved Q3 expansion budget"
}
```

### 19.4 Create Cost Centre Budget Version

```
POST /budgets/cc-versions?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "cost_centre_id": "<cost_centre_id>",
  "year_id": "<year_id>",
  "currency": "GBP",
  "budget_minor": 10000000,
  "override_reason": "Initial allocation for procurement"
}
```

> 📌 **Save** `version_id` from the response.

### 19.5 List Cost Centre Budget Versions

```
GET /budgets/cc-versions?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 19.6 Get Budget Version

```
GET /budgets/cc-versions/{version_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 19.7 Update Budget Version

```
PUT /budgets/cc-versions/{version_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "budget_minor": 12000000,
  "override_reason": "Additional allocation from surplus"
}
```

### 19.8 Budget Reallocation

```
POST /budgets/reallocate?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "source_version_id": "<source_version_id>",
  "target_version_id": "<target_version_id>",
  "amount_minor": 2000000,
  "note": "Transferring surplus from Marketing to Procurement"
}
```

### 19.9 List Budget Transactions

```
GET /budgets/transactions?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 20. User Budgets

### 20.1 Assign User to Cost Centre

```
POST /user-budgets/assignments?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "user_id": "<user_id>",
  "cost_centre_id": "<cost_centre_id>",
  "is_primary": true,
  "effective_from": "2026-01-01",
  "effective_to": "2026-12-31"
}
```

### 20.2 List User CC Assignments

```
GET /user-budgets/assignments?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 20.3 Remove User CC Assignment

```
DELETE /user-budgets/assignments/{assignment_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 20.4 Create User Budget Limit

```
POST /user-budgets/limits?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "user_id": "<user_id>",
  "cost_centre_id": "<cost_centre_id>",
  "year_id": "<year_id>",
  "limit_type": "requester",
  "window_type": "month",
  "limit_amount_minor": 5000000,
  "carry_forward_enabled": false,
  "window_start": "2026-01-01",
  "window_end": "2026-12-31"
}
```

### 20.5 List User Budget Limits

```
GET /user-budgets/limits?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 20.6 Get User Budget Limit Summary

```
GET /user-budgets/limits/summary/{user_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 20.7 Update User Budget Limit

```
PUT /user-budgets/limits/{limit_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "limit_amount_minor": 7500000,
  "carry_forward_enabled": true
}
```

### 20.8 Deactivate User Budget Limit

```
DELETE /user-budgets/limits/{limit_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 21. Approval Policies

### 21.1 Create Approval Policy (Multi-Stage)

```
POST /approval-policies?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "name": "Standard Procurement Approval",
  "description": "Two-stage approval for purchase requests > £1000",
  "cost_centre_id": "<cost_centre_id>",
  "routing_mode": "hierarchical",
  "broadcast_n": 3,
  "sox_sod_enforced": true,
  "partial_approval_mode": "block",
  "zero_value_mode": "auto",
  "stages": [
    {
      "stage_order": 1,
      "name": "Line Manager Approval",
      "parallel_allowed": false,
      "min_approvers": 1,
      "escalation_timeout_hours": 48,
      "conditions": [
        {
          "field": "amount",
          "operator": "gte",
          "value": 100000,
          "logic": "AND"
        }
      ],
      "approvers": [
        {
          "approver_type": "org_unit_manager",
          "org_unit_id": "<org_unit_id>"
        }
      ]
    },
    {
      "stage_order": 2,
      "name": "Finance Director Approval",
      "parallel_allowed": false,
      "min_approvers": 1,
      "escalation_timeout_hours": 72,
      "conditions": [
        {
          "field": "amount",
          "operator": "gte",
          "value": 500000,
          "logic": "AND"
        }
      ],
      "approvers": [
        {
          "approver_type": "role",
          "role_code": "finance_director"
        }
      ]
    }
  ]
}
```

### 21.2 Get Approval Policy

```
GET /approval-policies/{policy_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 21.3 Delete Approval Policy (Deactivate)

```
DELETE /approval-policies/{policy_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 22. Purchase Requests

### 22.1 Create Purchase Request

```
POST /purchase-requests?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "cost_centre_id": "<cost_centre_id>",
  "vendor_id": "<vendor_id>",
  "category_id": "<category_id>",
  "description": "Office stationery order for Q1",
  "line_items": [
    {
      "product_id": "<product_id>",
      "qty": 10,
      "unit_price_minor": 1299,
      "description": "Blue Ballpoint Pen (Pack of 50)"
    }
  ],
  "amount_minor": 12990,
  "currency": "GBP",
  "notes": "Urgent — needed by end of week"
}
```

### 22.2 List Purchase Requests

```
GET /purchase-requests?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 22.3 Get Purchase Request by ID

```
GET /purchase-requests/{request_id}?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 22.4 My Approval Tasks

```
GET /purchase-requests/my-tasks?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 22.5 Decide on Approval Task

```
POST /purchase-requests/tasks/{task_id}/decide?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "decision": "approve",
  "note": "Approved — within budget"
}
```

### 22.6 Issue Purchase Order

```
POST /purchase-requests/{request_id}/issue-po?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

---

## 23. Budget Change Requests

### 23.1 Bring Forward Request

```
POST /budget-change-requests/bring-forward?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "cost_centre_id": "<cost_centre_id>",
  "from_version_id": "<future_period_version_id>",
  "to_version_id": "<current_period_version_id>",
  "amount_minor": 1000000,
  "justification": "Unexpected bulk order requirement for Q1 supplies"
}
```

### 23.2 Top-Up Request

```
POST /budget-change-requests/top-up?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "cost_centre_id": "<cost_centre_id>",
  "from_version_id": "<source_version_id>",
  "to_version_id": "<target_version_id>",
  "amount_minor": 500000,
  "justification": "Emergency maintenance supplies needed"
}
```

### 23.3 Reallocation Request

```
POST /budget-change-requests/reallocation?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "cost_centre_id": "<cost_centre_id>",
  "from_version_id": "<source_version_id>",
  "to_version_id": "<target_version_id>",
  "amount_minor": 2000000,
  "justification": "Moving surplus from IT budget to procurement"
}
```

### 23.4 List Budget Change Requests

```
GET /budget-change-requests?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 23.5 Decide on Budget Change Request

```
POST /budget-change-requests/{change_req_id}/decide?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```
```json
{
  "decision": "approved",
  "note": "Approved by finance director"
}
```

---

## 24. Subscriptions

### 24.1 Check Current Subscription

```
GET /subscriptions/active?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2
```

### 24.2 Who Am I (Subscription Context)

```
GET /subscriptions/whoami
```

### 24.3 Renew Subscription

```
POST /subscriptions/renew
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "plan_code": "core_01",
  "payment_method": "card",
  "current_period_start": "2027-01-01T00:00:00Z",
  "current_period_end": "2027-12-31T23:59:59Z",
  "previous_sub_id": 1
}
```

### 24.4 Upgrade Preview

```
GET /subscriptions/upgrade-preview?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2&upgrade_plan_code=pro_01&subscription_id=1
```

### 24.5 Upgrade Subscription

```
GET /subscriptions/upgrade?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2&upgrade_plan_code=pro_01&subscription_id=1
```

### 24.6 Downgrade Subscription

```
GET /subscriptions/downgrade?tenant_id=fd563534-0686-4afa-bdaf-b386fc33f2c2&downgrade_plan_code=basic_01&subscription_id=1
```

### 24.7 Cancel Subscription

```
POST /subscriptions/cancel
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "subscription_id": 1,
  "reason": "Switching to competitor",
  "cancel_immediately": false
}
```

---

## 25. Payments (Stripe)

### 25.1 Create Checkout Session

```
POST /payments/create-checkout-session
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2",
  "plan_code": "core_01",
  "billing_cycle": "monthly",
  "currency": "usd",
  "quantity": 1,
  "mode": "subscription"
}
```

### 25.2 Create Billing Portal Session

```
POST /payments/create-portal-session
```
```json
{
  "tenant_id": "fd563534-0686-4afa-bdaf-b386fc33f2c2"
}
```

### 25.3 Stripe Webhook

```
POST /payments/webhook
```
_Called by Stripe — not for manual testing._

---

## 26. Plans (Public)

### 26.1 List All Plans with Pricing

```
GET /plans/
```
_No authentication required. Returns all active plans with monthly/quarterly/yearly pricing._

---

## Quick Setup Sequence

Follow this order to set up a fully functional tenant from scratch:

```
1.  POST /internal/permissions         ← Seed permissions (or auto-loaded from CSV)
2.  POST /internal/roles               ← Create global roles
3.  POST /internal/roles/map-permission ← Map permissions to roles
4.  POST /internal/plans               ← Create subscription plans
5.  POST /internal/features            ← Create features
6.  PUT  /internal/plans/{code}/features/{code}  ← Map features to plans
7.  POST /onboarding/otp/generate      ← Send OTP to admin email
8.  POST /onboarding/otp/validate      ← Validate OTP
9.  POST /onboarding/tenant-signup     ← Create tenant + admin user
10. POST /onboarding/tenant-signin     ← Login → get JWT token
11. POST /provisioning/sites           ← Create site
12. POST /provisioning/stores          ← Create store under site
13. POST /provisioning/users           ← Create additional users
14. POST /provisioning/roles           ← Create tenant-level roles
15. POST /provisioning/users/{id}/roles ← Assign roles to users
16. POST /provisioning/org_units       ← Create org units (departments)
17. POST /provisioning/org_units/assignments ← Assign users to org units
18. POST /provisioning/vendors         ← Create vendors
19. POST /provisioning/cost-centres    ← Create cost centres with budgets
20. POST /provisioning/users/{id}/cost-centres ← Assign users to cost centres
21. POST /catalog/categories           ← Create product categories
22. POST /catalog/products             ← Create products
23. POST /catalog/store-products       ← Link products to stores
24. POST /approved-ranges              ← Create approved ranges
25. POST /approved-ranges/{id}/org-units   ← Map ranges to org units
26. POST /approved-ranges/{id}/products    ← Add products to ranges
27. POST /financial-calendars          ← Create financial calendar
28. POST /financial-calendars/{id}/years   ← Create financial year
29. PUT  /financial-calendars/{id}/years/{id}/activate ← Activate year
30. POST /financial-calendars/{id}/years/{id}/generate-periods ← Generate periods
31. POST /budgets/company-caps         ← Set company budget cap
32. POST /budgets/cc-versions          ← Allocate budget to cost centres
33. POST /user-budgets/assignments     ← Assign users to cost centres
34. POST /user-budgets/limits          ← Set per-user spending limits
35. POST /approval-policies            ← Create approval policies
36. POST /purchase-requests            ← Create purchase request (tests full flow)
```

