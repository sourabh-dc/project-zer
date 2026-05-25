# Provisioning Service — Local Testing Script
# Automates the full ZeroQue provisioning flow from zero to purchase request.
#
# Prerequisites:
#   - PostgreSQL running (DATABASE_URL env var or localhost:5432)
#   - OPA running at localhost:8181 (or set POLICY_ENGINE_BYPASS=true)
#   - Provisioning API:   uvicorn provisioning_service.main:app --port 8000
#   - (optional) Provisioning Worker:
#       python provisioning_service/core/helpers/outbox_worker.py
#   - (optional) Data Intelligence API:
#       uvicorn data_intelligence_service.main:app --port 8001
#   - (optional) Data Intelligence Worker:
#       python -m data_intelligence_service.workers.consumer_standalone
#   - (optional) Neo4j + PgVector (required for graph/vector verification)
#
# Usage:
#   ./test_provisioning.ps1
#   ./test_provisioning.ps1 -BaseUrl "http://localhost:8080"
#   ./test_provisioning.ps1 -SkipSeed        # Skip internal seed (already done)
#   ./test_provisioning.ps1 -SkipOnboarding  # Skip onboarding (reuse existing tenant)
#   ./test_provisioning.ps1 -TenantId "..." -Token "..."  # Use existing tenant

param(
    [Parameter(Mandatory=$false)]
    [string]$BaseUrl = "http://localhost:8000",

    [Parameter(Mandatory=$false)]
    [switch]$SkipSeed,

    [Parameter(Mandatory=$false)]
    [switch]$SkipOnboarding,

    [Parameter(Mandatory=$false)]
    [string]$TenantId,

    [Parameter(Mandatory=$false)]
    [string]$Token,

    [Parameter(Mandatory=$false)]
    [switch]$StopOnFail,

    [Parameter(Mandatory=$false)]
    [string]$DataIntelUrl = "http://localhost:8001",

    [Parameter(Mandatory=$false)]
    [int]$OutboxWaitSeconds = 10,

    [Parameter(Mandatory=$false)]
    [switch]$SkipDataIntelVerify
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
function Write-Step   { Write-Host "`n============================================================" -ForegroundColor Cyan; Write-Host "STEP: $args" -ForegroundColor Cyan }
function Write-Info    { Write-Host "  [INFO] $args" -ForegroundColor Gray }
function Write-Pass    { Write-Host "  [PASS] $args" -ForegroundColor Green }
function Write-Fail    { Write-Host "  [FAIL] $args" -ForegroundColor Red; if ($StopOnFail) { throw "Test failed: $args" } }
function Write-Warn    { Write-Host "  [WARN] $args" -ForegroundColor Yellow }

# Make an API call and return parsed JSON + status code
function Invoke-Api {
    param(
        [string]$Method = "GET",
        [string]$Path,
        $Body,
        [string]$Description = "",
        [int]$ExpectedStatus = 200
    )
    $uri = "$BaseUrl$Path"
    $desc = if ($Description) { $Description } else { "$Method $Path" }

    $headers = @{ "Content-Type" = "application/json" }
    if ($script:AuthToken) {
        $headers["Authorization"] = "Bearer $script:AuthToken"
    }

    $params = @{
        Uri     = $uri
        Method  = $Method
        Headers = $headers
    }
    if ($Body) {
        $params["Body"] = if ($Body -is [string]) { $Body } else { ($Body | ConvertTo-Json -Depth 10) }
    }

    try {
        $response = Invoke-RestMethod @params -StatusCodeVariable statusCode -SkipHttpErrorCheck
        if ($statusCode -eq $ExpectedStatus -or $statusCode -eq 200 -or $statusCode -eq 201 -or $statusCode -eq 204) {
            Write-Pass "$desc  ($statusCode)"
        } else {
            Write-Fail "$desc — expected $ExpectedStatus, got $statusCode"
        }
        return @{ Body = $response; StatusCode = $statusCode }
    }
    catch {
        Write-Fail "$desc — $_"
        return $null
    }
}

# Global state
$script:AuthToken = $Token
$script:TenantId   = $TenantId
$script:AdminUserId = $null
$state = @{}   # stores IDs as we go: site_id, store_id, etc.

# ------------------------------------------------------------------
# Data Intelligence Helpers (graph/vector worker verification)
# ------------------------------------------------------------------
function Invoke-DataIntel {
    param(
        [string]$Method = "GET",
        [string]$Path,
        [string]$Description = "",
        [int]$ExpectedStatus = 200,
        [bool]$AllowNotFound = $false
    )
    $uri = "$DataIntelUrl$Path"
    $desc = if ($Description) { $Description } else { "DI $Method $Path" }

    $headers = @{ "Content-Type" = "application/json" }
    $params = @{ Uri = $uri; Method = $Method; Headers = $headers }

    try {
        $response = Invoke-RestMethod @params -StatusCodeVariable sc -SkipHttpErrorCheck
        if ($sc -eq $ExpectedStatus -or $sc -eq 200 -or $sc -eq 201 -or $sc -eq 204) {
            Write-Pass "$desc  ($sc)"
        } elseif ($AllowNotFound -and ($sc -eq 404 -or $sc -eq 503)) {
            Write-Warn "$desc — not found yet (worker may still be processing)  ($sc)"
        } else {
            Write-Fail "$desc — expected $ExpectedStatus, got $sc"
        }
        return @{ Body = $response; StatusCode = $sc }
    }
    catch {
        Write-Fail "$desc — $_"
        return $null
    }
}

function Wait-ForOutbox {
    param([string]$Label = "outbox events")
    Write-Info "Waiting ${OutboxWaitSeconds}s for $Label to be consumed by data-intelligence worker..."
    Start-Sleep -Seconds $OutboxWaitSeconds
}

function Check-DataIntelHealth {
    $r = Invoke-DataIntel -Path "/health" -Description "DI GET /health" -AllowNotFound $true
    if (-not $r -or $r.StatusCode -ne 200) {
        Write-Warn "Data Intelligence service is not reachable at $DataIntelUrl"
        Write-Warn "Start it with: uvicorn data_intelligence_service.main:app --port 8001"
        Write-Warn "And the worker with: python -m data_intelligence_service.workers.consumer_standalone"
        return $false
    }
    return $true
}

# ------------------------------------------------------------------
# 0. Health Check
# ------------------------------------------------------------------
Write-Step "0. Health Check"
$r = Invoke-Api -Path "/health" -Description "GET /health"
if (-not $r -or $r.StatusCode -ne 200) {
    Write-Fail "Provisioning service is not reachable at $BaseUrl. Start it first."
    exit 1
}

# ------------------------------------------------------------------
# 1. Seed Internal Data (Permissions, Roles, Plans, Features)
# ------------------------------------------------------------------
if (-not $SkipSeed) {
    Write-Step "1. Platform Setup (Internal)"

    Write-Info "1.1 Create Permissions"
    $perms = @(
        @{ code = "tenants.create";            description = "Permission to create tenants" },
        @{ code = "tenants.view";              description = "View tenant details" },
        @{ code = "sites.manage";              description = "Manage sites" },
        @{ code = "stores.manage";             description = "Manage stores" },
        @{ code = "users.manage";              description = "Manage users" },
        @{ code = "org_units.manage";          description = "Manage org units" },
        @{ code = "vendors.manage";            description = "Manage vendors" },
        @{ code = "cost_centres.manage";       description = "Manage cost centres" },
        @{ code = "catalog.products.view";     description = "View catalog products" },
        @{ code = "catalog.products.manage";   description = "Manage catalog products" },
        @{ code = "approved_range.create";     description = "Create approved ranges" },
        @{ code = "approved_range.update";     description = "Update approved ranges" },
        @{ code = "approved_range.delete";     description = "Delete approved ranges" },
        @{ code = "approval_policy.create";    description = "Create approval policies" },
        @{ code = "approval_policy.delete";    description = "Delete approval policies" },
        @{ code = "order.create";              description = "Create purchase orders" },
        @{ code = "purchase_request.create";   description = "Create purchase requests" },
        @{ code = "budget_change.bring_forward"; description = "Bring forward budget" },
        @{ code = "budget_change.top_up";      description = "Top-up budget" },
        @{ code = "budget_change.reallocation"; description = "Reallocate budget" },
        @{ code = "budget_change.decide";      description = "Decide on budget change" },
        @{ code = "subscriptions.manage";      description = "Manage subscriptions" }
    )
    foreach ($p in $perms) {
        Invoke-Api -Method POST -Path "/internal/permissions" -Body $p -Description "POST /internal/permissions ($($p.code))"
    }

    Write-Info "1.2 Create Global Roles"
    $roles = @(
        @{ code = "tenant_admin";       description = "Full admin access to tenant" },
        @{ code = "procurement_manager"; description = "Procurement manager role" },
        @{ code = "store_manager";      description = "Store manager role" },
        @{ code = "finance_director";   description = "Finance director role" },
        @{ code = "vendor_admin";       description = "Vendor admin role" }
    )
    foreach ($r in $roles) {
        Invoke-Api -Method POST -Path "/internal/roles" -Body $r -Description "POST /internal/roles ($($r.code))"
    }

    Write-Info "1.3 Add Permissions to tenant_admin Role"
    $allPerms = $perms | ForEach-Object { $_.code }
    foreach ($pc in $allPerms) {
        Invoke-Api -Method POST -Path "/internal/roles/tenant_admin/permissions" -Body @{ code = $pc } -Description "Add $pc to tenant_admin"
    }

    Write-Info "1.4 Create Subscription Plans"
    $plans = @(
        @{ code = "core_01";  name = "Core Plan";    description = "Basic plan";      price_monthly_minor = 9900;  currency = "GBP"; quarterly_discount_pct = 5.0;  yearly_discount_pct = 10.0 },
        @{ code = "pro_01";   name = "Pro Plan";     description = "Professional plan"; price_monthly_minor = 19900; currency = "GBP"; quarterly_discount_pct = 7.5;  yearly_discount_pct = 15.0 },
        @{ code = "basic_01"; name = "Basic Plan";   description = "Entry-level plan";  price_monthly_minor = 4900;  currency = "GBP"; quarterly_discount_pct = 3.0;  yearly_discount_pct = 5.0 }
    )
    foreach ($p in $plans) {
        Invoke-Api -Method POST -Path "/internal/plans" -Body $p -Description "POST /internal/plans ($($p.code))"
    }

    Write-Info "1.5 Create Features"
    $features = @(
        @{ code = "products";   name = "Products";      description = "Number of products allowed";   cluster = "catalog";    usage_type = "count"; max_unit = "products";   reset_period = "monthly" },
        @{ code = "catalog";    name = "Catalog";       description = "Catalog access";               cluster = "catalog";    usage_type = "flag";  max_unit = "flag";       reset_period = "never" },
        @{ code = "users";      name = "Users";         description = "Number of users allowed";      cluster = "platform";   usage_type = "count"; max_unit = "users";      reset_period = "monthly" },
        @{ code = "sites";      name = "Sites";         description = "Number of sites";              cluster = "platform";   usage_type = "count"; max_unit = "sites";      reset_period = "monthly" },
        @{ code = "stores";     name = "Stores";        description = "Number of stores";             cluster = "platform";   usage_type = "count"; max_unit = "stores";     reset_period = "monthly" },
        @{ code = "budgeting";  name = "Budgeting";     description = "Budget management features";    cluster = "financial";  usage_type = "flag";  max_unit = "flag";       reset_period = "never" },
        @{ code = "approvals";  name = "Approvals";     description = "Approval workflow";            cluster = "financial";  usage_type = "flag";  max_unit = "flag";       reset_period = "never" },
        @{ code = "reports";    name = "Reports";       description = "Reporting and analytics";      cluster = "analytics";  usage_type = "flag";  max_unit = "flag";       reset_period = "never" }
    )
    foreach ($f in $features) {
        Invoke-Api -Method POST -Path "/internal/features" -Body $f -Description "POST /internal/features ($($f.code))"
    }

    Write-Info "1.6 Map Features to Plans"
    foreach ($planCode in @("core_01", "pro_01", "basic_01")) {
        foreach ($featCode in $features.code) {
            Invoke-Api -Method PUT -Path "/internal/plans/$planCode/features/$featCode" -Description "Map $featCode → $planCode"
        }
    }

    Write-Pass "Platform setup complete"
} else {
    Write-Step "1. Platform Setup — SKIPPED (already seeded)"
}

# ------------------------------------------------------------------
# 2. Tenant Onboarding
# ------------------------------------------------------------------
if (-not $SkipOnboarding) {
    Write-Step "2. Tenant Onboarding"

    Write-Info "2.1 Register (Step 1 — create billing mandate)"
    $registerBody = @{
        email                 = "contact@testcorp.com"
        tenant_name           = "Test Corporation"
        tenant_type           = "retailer"
        admin_email           = "admin@testcorp.com"
        admin_firstname       = "Alice"
        admin_lastname        = "Admin"
        password              = "SecurePass1"
        plan_code             = "core_01"
        billing_cycle         = "monthly"
        phone                 = "+447700900001"
        default_currency      = "GBP"
        timezone              = "Europe/London"
        locale                = "en_GB"
        industry              = "Retail"
        registration_number   = "REG-2026-TEST"
        billing_address       = "1 Test Street, London, EC1A 1BB"
        primary_domain        = "testcorp.com"
        billing_email         = "billing@testcorp.com"
        tech_contact_email    = "tech@testcorp.com"
        support_contact_email = "support@testcorp.com"
    }
    $r = Invoke-Api -Method POST -Path "/onboarding/register" -Body $registerBody -Description "POST /onboarding/register"
    $mandateId = $r.Body.mandate_id
    if (-not $mandateId) { Write-Warn "No mandate_id returned — Stripe may be disabled. Trying activation anyway." }

    Write-Info "2.2 Activate (Step 2 — confirm card, create tenant)"
    $activateBody = @{ mandate_id = $mandateId }
    $r = Invoke-Api -Method POST -Path "/onboarding/activate" -Body $activateBody -Description "POST /onboarding/activate"
    $state.TenantId = $r.Body.tenant_id
    if (-not $state.TenantId) {
        Write-Warn "Tenant activation may have failed (Stripe required?). Sleeping 2s and retrying..."
        Start-Sleep -Seconds 2
        $r = Invoke-Api -Method POST -Path "/onboarding/activate" -Body $activateBody -Description "POST /onboarding/activate (retry)"
        $state.TenantId = $r.Body.tenant_id
    }
    Write-Info "Tenant ID: $($state.TenantId)"

    Write-Info "2.3 Tenant Sign-In (Login)"
    $loginBody = @{ email = "admin@testcorp.com"; password = "SecurePass1" }
    $r = Invoke-Api -Method POST -Path "/onboarding/tenant-signin" -Body $loginBody -Description "POST /onboarding/tenant-signin"
    $script:AuthToken = $r.Body.token
    $state.AdminUserId = $r.Body.user_id
    if (-not $script:AuthToken) {
        Write-Fail "No token returned — cannot continue authenticated tests"
        exit 1
    }
    Write-Info "User ID: $($state.AdminUserId)"
    Write-Pass "Tenant onboarded and logged in"
} else {
    Write-Step "2. Tenant Onboarding — SKIPPED (using existing tenant)"
    $state.TenantId = $TenantId
    $state.AdminUserId = "reuse"
    if (-not $script:AuthToken) {
        Write-Warn "No token provided — authenticated endpoints will fail"
    }
}

# Helper: build tenant query string
$tid = $state.TenantId
function q { "?tenant_id=$tid" }

# ------------------------------------------------------------------
# 3. Authentication Check
# ------------------------------------------------------------------
Write-Step "3. Authentication"
Invoke-Api -Path "/authentication/whoami" -Description "GET /authentication/whoami"
Invoke-Api -Path "/authentication/healthcheck" -Description "GET /authentication/healthcheck"

# ------------------------------------------------------------------
# 3.5 Data Intelligence — Health Check + Worker Status
# ------------------------------------------------------------------
if (-not $SkipDataIntelVerify) {
    Write-Step "3.5 Data Intelligence Layer — Health Check"
    $diAlive = Check-DataIntelHealth
    if ($diAlive) {
        Write-Info "Data Intelligence API reachable. Worker verification will run after provisioning."
    } else {
        Write-Warn "Proceeding without data-intelligence verification."
        Write-Warn "Tip: Set `-SkipDataIntelVerify` to suppress this warning."
    }
}

# ------------------------------------------------------------------
# 4. Tenant Management
# ------------------------------------------------------------------
Write-Step "4. Tenant Management"
Invoke-Api -Path "/provisioning/tenants" -Description "GET /provisioning/tenants"
Invoke-Api -Path "/provisioning/tenants/$tid" -Description "GET /provisioning/tenants/{id}"
Invoke-Api -Method PUT -Path "/provisioning/tenants/$tid" `
    -Body @{ name = "Test Corporation Ltd"; phone = "+447700900002"; active = "true" } `
    -Description "PUT /provisioning/tenants/{id}"

# ------------------------------------------------------------------
# 5. Sites
# ------------------------------------------------------------------
Write-Step "5. Sites"
$r = Invoke-Api -Method POST -Path "/provisioning/sites" -Body @{
    name             = "London Headquarters"
    type             = "campus"
    active           = $true
    currency         = "GBP"
    timezone         = "Europe/London"
    language         = "en"
    phone            = "+442071234567"
    email            = "hq@testcorp.com"
    url              = "https://testcorp.com"
    is_headquarter   = $true
    primary_billing_address  = @{ line1 = "1 Test Street"; city = "London"; postcode = "EC1A 1BB"; country = "GB" }
    primary_shipping_address = @{ line1 = "1 Test Street"; city = "London"; postcode = "EC1A 1BB"; country = "GB" }
    geo              = @{ lat = 51.5074; lng = -0.1278 }
} -Description "POST /provisioning/sites"
$state.SiteId = $r.Body.site_id

Invoke-Api -Path "/provisioning/sites$(q)" -Description "GET /provisioning/sites"
Invoke-Api -Path "/provisioning/sites/$($state.SiteId)" -Description "GET /provisioning/sites/{id}"
Invoke-Api -Method PUT -Path "/provisioning/sites/$($state.SiteId)" `
    -Body @{ name = "London HQ — Renovated"; phone = "+442071234999" } `
    -Description "PUT /provisioning/sites/{id}"

# ------------------------------------------------------------------
# 6. Stores
# ------------------------------------------------------------------
Write-Step "6. Stores"
$r = Invoke-Api -Method POST -Path "/provisioning/stores" -Body @{
    name                    = "London Flagship Store"
    store_type              = "physical"
    active                  = $true
    site_id                 = $state.SiteId
    currency                = "GBP"
    timezone                = "Europe/London"
    phone                   = "+442079876543"
    email                   = "flagship@testcorp.com"
    fulfillment_mode        = "both"
    inventory_policy        = "track_on_hand"
    primary_shipping_address= @{ line1 = "10 Oxford St"; city = "London"; postcode = "W1A 0AX"; country = "GB" }
    pickup_address          = @{ line1 = "10 Oxford St, Rear"; city = "London"; postcode = "W1A 0AX"; country = "GB" }
    geo                     = @{ lat = 51.5155; lng = -0.1419 }
} -Description "POST /provisioning/stores"
$state.StoreId = $r.Body.store_id

Invoke-Api -Path "/provisioning/stores$(q)" -Description "GET /provisioning/stores"
Invoke-Api -Path "/provisioning/stores/$($state.StoreId)" -Description "GET /provisioning/stores/{id}"
Invoke-Api -Method PUT -Path "/provisioning/stores/$($state.StoreId)" `
    -Body @{ name = "London Flagship — Renovated"; fulfillment_mode = "pickup" } `
    -Description "PUT /provisioning/stores/{id}"

# ------------------------------------------------------------------
# 7. Users
# ------------------------------------------------------------------
Write-Step "7. Users"
$r = Invoke-Api -Method POST -Path "/provisioning/users" -Body @{
    email          = "jane.doe@testcorp.com"
    password       = "UserPass1"
    first_name     = "Jane"
    last_name      = "Doe"
    phone          = "+447700900100"
    position       = "Procurement Manager"
    is_sso_enabled = $false
    home_site_id   = $state.SiteId
    home_store_id  = $state.StoreId
    all_locations  = $false
} -Description "POST /provisioning/users"
$state.UserId = $r.Body.user_id

Invoke-Api -Path "/provisioning/users$(q)" -Description "GET /provisioning/users"
Invoke-Api -Path "/provisioning/users/$($state.UserId)" -Description "GET /provisioning/users/{id}"
Invoke-Api -Method PUT -Path "/provisioning/users/$($state.UserId)" `
    -Body @{ position = "Senior Procurement Manager"; all_locations = $true; is_active = $true } `
    -Description "PUT /provisioning/users/{id}"
Invoke-Api -Path "/provisioning/users/$($state.UserId)/budget" -Description "GET /provisioning/users/{id}/budget"

# ------------------------------------------------------------------
# 8. Roles & Permissions (Tenant-Level)
# ------------------------------------------------------------------
Write-Step "8. Roles & Permissions (Tenant-Level)"
Invoke-Api -Method POST -Path "/provisioning/roles" -Body @{
    code        = "procurement_manager"
    description = "Can create purchase requests and manage budgets"
} -Description "POST /provisioning/roles"
Invoke-Api -Path "/provisioning/roles" -Description "GET /provisioning/roles"

Invoke-Api -Method POST -Path "/provisioning/roles/map-permission" -Body @{
    role_code       = "procurement_manager"
    permission_code = "catalog.products.view"
} -Description "Map catalog.products.view to procurement_manager"

Invoke-Api -Path "/provisioning/roles/procurement_manager/permissions" -Description "GET role permissions"

Invoke-Api -Method POST -Path "/provisioning/users/$($state.UserId)/roles" `
    -Body @{ role_id = "procurement_manager" } `
    -Description "Assign role to user"
Invoke-Api -Path "/provisioning/users/$($state.UserId)/roles" -Description "GET /provisioning/users/{id}/roles"

# ------------------------------------------------------------------
# 9. Org Units
# ------------------------------------------------------------------
Write-Step "9. Org Units"
$r = Invoke-Api -Method POST -Path "/provisioning/org_units" -Body @{
    name            = "Procurement Division"
    type            = "department"
    status          = "active"
    code            = "PROC-001"
    description     = "Handles all procurement activities"
    manager_user_id = $state.UserId
    path            = "/TestCorp/Procurement"
    depth           = 1
} -Description "POST /provisioning/org_units"
$state.OrgUnitId = $r.Body.org_unit_id

$r2 = Invoke-Api -Method POST -Path "/provisioning/org_units" -Body @{
    name             = "Office Supplies Team"
    type             = "team"
    status           = "active"
    parent_org_unit_id = $state.OrgUnitId
    code             = "PROC-001-OS"
    description      = "Office supplies procurement team"
    path             = "/TestCorp/Procurement/OfficeSupplies"
    depth            = 2
} -Description "POST /provisioning/org_units (child)"
$state.ChildOrgUnitId = $r2.Body.org_unit_id

Invoke-Api -Path "/provisioning/org_units$(q)" -Description "GET /provisioning/org_units"
Invoke-Api -Path "/provisioning/org_units/$($state.OrgUnitId)" -Description "GET /provisioning/org_units/{id}"

Invoke-Api -Method POST -Path "/provisioning/org_units/assignments" -Body @{
    user_id     = $state.UserId
    org_unit_id = $state.OrgUnitId
    role_id     = "procurement_manager"
    assigned_by = $state.AdminUserId
} -Description "Assign user to org unit"
Invoke-Api -Path "/provisioning/org_units/$($state.OrgUnitId)/users" -Description "GET org_unit users"
Invoke-Api -Path "/provisioning/users/$($state.UserId)/org_units" -Description "GET user org_units"

# ------------------------------------------------------------------
# 10. Vendors
# ------------------------------------------------------------------
Write-Step "10. Vendors"
$r = Invoke-Api -Method POST -Path "/provisioning/vendors" -Body @{
    name         = "OfficeMax Supplies Ltd"
    contact_email = "sales@officemax.co.uk"
    description  = "Office supplies and stationery vendor"
} -Description "POST /provisioning/vendors"
$state.VendorId = $r.Body.vendor_id

Invoke-Api -Path "/provisioning/vendors$(q)" -Description "GET /provisioning/vendors"
Invoke-Api -Path "/provisioning/vendors/$($state.VendorId)" -Description "GET /provisioning/vendors/{id}"
Invoke-Api -Method PUT -Path "/provisioning/vendors/$($state.VendorId)" -Body @{
    name               = "OfficeMax Supplies International"
    description        = "Updated vendor description"
    status             = "active"
    preferred_protocol = "api"
    api_endpoint_url   = "https://api.officemax.co.uk/orders"
    notification_email = "notifications@officemax.co.uk"
    payment_terms      = "net30"
    lead_time_days     = 3
    minimum_order_minor = 5000
} -Description "PUT /provisioning/vendors/{id}"

# Vendor user
Invoke-Api -Method POST -Path "/provisioning/vendor-user" -Body @{
    vendor_id     = $state.VendorId
    email         = "rep@officemax.co.uk"
    password_hash = "VendorPass1"
    first_name    = "Bob"
    role          = "vendor_admin"
    active        = $true
} -Description "POST /provisioning/vendor-user"

# ------------------------------------------------------------------
# 11. Cost Centres
# ------------------------------------------------------------------
Write-Step "11. Cost Centres"
$r = Invoke-Api -Method POST -Path "/provisioning/cost-centres" -Body @{
    code               = "CC-PROC-001"
    name               = "Procurement Department Budget"
    description        = "Budget for the procurement division"
    owner_user_id      = $state.UserId
    is_active          = $true
    fiscal_year        = 2026
    period_type        = "annual"
    period_number      = 1
    period_start       = "2026-01-01"
    period_end         = "2026-12-31"
    budget_amount_minor = 50000000
    created_by         = $state.UserId
} -Description "POST /provisioning/cost-centres"
$state.CostCentreId = $r.Body.cost_centre_id

Invoke-Api -Path "/provisioning/cost-centres$(q)" -Description "GET /provisioning/cost-centres"
Invoke-Api -Path "/provisioning/cost-centres/$($state.CostCentreId)" -Description "GET /provisioning/cost-centres/{id}"

Invoke-Api -Method POST -Path "/provisioning/users/$($state.UserId)/cost-centres" -Body @{
    cost_centre_id         = $state.CostCentreId
    allocated_budget_minor = 10000000
} -Description "Assign user to cost centre"

# ------------------------------------------------------------------
# 12. Catalog — Categories
# ------------------------------------------------------------------
Write-Step "12. Catalog — Categories"
$r = Invoke-Api -Method POST -Path "/catalog/categories" -Body @{
    name        = "Office Supplies"
    code        = "OFF-SUP"
    description = "General office supplies and stationery"
} -Description "POST /catalog/categories"
$state.CategoryId = $r.Body.category_id

Invoke-Api -Method POST -Path "/catalog/categories" -Body @{
    name               = "Writing Instruments"
    code               = "OFF-SUP-WI"
    description        = "Pens, pencils, markers"
    parent_category_id = $state.CategoryId
} -Description "POST /catalog/categories (sub)"
Invoke-Api -Path "/catalog/categories$(q)" -Description "GET /catalog/categories"

# ------------------------------------------------------------------
# 13. Catalog — Products
# ------------------------------------------------------------------
Write-Step "13. Catalog — Products"
$r = Invoke-Api -Method POST -Path "/catalog/products" -Body @{
    vendor_id            = $state.VendorId
    category_id          = $state.CategoryId
    sku                  = "PEN-BLU-001"
    ean                  = "5012345678901"
    display_name         = "Blue Ballpoint Pen (Pack of 50)"
    sales_description    = "Premium blue ballpoint pen, medium point, box of 50"
    purchase_description = "BPP-50-BLU bulk order"
    manufacturer         = "PenCo International"
    is_matrix_item       = $false
    matrix_type          = "standalone"
    purchase_price_minor = 1299
    currency             = "GBP"
    tax_rate             = 2000
    weight               = 0.5
    weight_unit          = "kg"
    outer_quantity       = 10
    inner_quantity       = 50
    reorder_multiple     = 5
    product_type         = "physical"
    restricted           = $false
    search_keywords      = "pen blue ballpoint writing office stationery"
    product_metadata     = @{ colour = "blue"; point_size = "medium"; material = "plastic" }
} -Description "POST /catalog/products"
$state.ProductId = $r.Body.product_id
Invoke-Api -Path "/catalog/products$(q)" -Description "GET /catalog/products"

# ------------------------------------------------------------------
# 14. Catalog — Variants
# ------------------------------------------------------------------
Write-Step "14. Catalog — Variants"
Invoke-Api -Method POST -Path "/catalog/variants" -Body @{
    product_id         = $state.ProductId
    sku                = "PEN-BLU-001-M"
    name               = "Blue Pen — Medium Point"
    attributes         = @{ colour = "blue"; point_size = "medium" }
    price_minor        = 1299
    currency           = "GBP"
    stock_quantity     = 500
    low_stock_threshold = 50
} -Description "POST /catalog/variants"

# ------------------------------------------------------------------
# 15. Catalog — Store Products
# ------------------------------------------------------------------
Write-Step "15. Catalog — Store Products"
Invoke-Api -Method POST -Path "/catalog/store-products" -Body @{
    store_id            = $state.StoreId
    product_id          = $state.ProductId
    price_minor         = 1499
    currency            = "GBP"
    is_available        = $true
    stock_quantity      = 200
    low_stock_threshold = 20
} -Description "POST /catalog/store-products"
Invoke-Api -Path "/catalog/store-products?store_id=$($state.StoreId)" -Description "GET store products"
Invoke-Api -Path "/catalog/stores/$($state.StoreId)/products" -Description "GET products for store"

# ------------------------------------------------------------------
# 16. Approved Ranges
# ------------------------------------------------------------------
Write-Step "16. Approved Ranges"
$r = Invoke-Api -Method POST -Path "/approved-ranges$(q)" -Body @{
    name         = "Office Supplies Q1 2026"
    description  = "Approved office supplies for Q1 2026"
    is_universal = $false
} -Description "POST /approved-ranges"
$state.ApprovedRangeId = $r.Body.approved_range_id

Invoke-Api -Method POST -Path "/approved-ranges/$($state.ApprovedRangeId)/org-units$(q)" `
    -Body @{ org_unit_ids = @($state.OrgUnitId) } `
    -Description "Map org units to approved range"
Invoke-Api -Method POST -Path "/approved-ranges/$($state.ApprovedRangeId)/products$(q)" `
    -Body @{ product_ids = @($state.ProductId) } `
    -Description "Add products to approved range"

Invoke-Api -Path "/approved-ranges$(q)" -Description "GET /approved-ranges"
Invoke-Api -Path "/approved-ranges/$($state.ApprovedRangeId)$(q)" -Description "GET approved range by id"
Invoke-Api -Path "/approved-ranges/$($state.ApprovedRangeId)/org-units$(q)" -Description "GET org units in range"
Invoke-Api -Path "/approved-ranges/$($state.ApprovedRangeId)/products$(q)" -Description "GET products in range"

# ------------------------------------------------------------------
# 17. Financial Calendars
# ------------------------------------------------------------------
Write-Step "17. Financial Calendars"
$r = Invoke-Api -Method POST -Path "/financial-calendars$(q)" -Body @{
    name          = "TestCorp FY2026 Calendar"
    description   = "Standard Gregorian financial calendar for FY2026"
    calendar_type = "gregorian"
    start_month   = 1
    currency      = "GBP"
    is_default    = $true
} -Description "POST /financial-calendars"
$state.CalendarId = $r.Body.calendar_id

Invoke-Api -Path "/financial-calendars$(q)" -Description "GET /financial-calendars"
Invoke-Api -Path "/financial-calendars/$($state.CalendarId)" -Description "GET calendar by id"

$r = Invoke-Api -Method POST -Path "/financial-calendars/$($state.CalendarId)/years$(q)" -Body @{
    label              = "FY2026"
    start_date         = "2026-01-01"
    end_date           = "2026-12-31"
    year_type          = "full"
    total_budget_minor = 50000000
    notes              = "Full financial year 2026"
} -Description "POST /financial-calendars/{id}/years"
$state.YearId = $r.Body.year_id

Invoke-Api -Method PUT -Path "/financial-calendars/$($state.CalendarId)/years/$($state.YearId)/activate$(q)" `
    -Description "Activate financial year"
Invoke-Api -Method POST -Path "/financial-calendars/$($state.CalendarId)/years/$($state.YearId)/generate-periods$(q)" `
    -Body @{ period_type = "month" } `
    -Description "Generate monthly periods"
Invoke-Api -Path "/financial-calendars/$($state.CalendarId)/years/$($state.YearId)/periods$(q)" -Description "List periods"

# ------------------------------------------------------------------
# 18. Budgets
# ------------------------------------------------------------------
Write-Step "18. Budgets"
$r = Invoke-Api -Method POST -Path "/budgets/company-caps$(q)" -Body @{
    year_id            = $state.YearId
    calendar_id        = $state.CalendarId
    currency           = "GBP"
    total_budget_minor = 50000000
    hard_cap           = $false
    notes              = "FY2026 company-wide budget cap"
} -Description "POST /budgets/company-caps"
$state.CapId = $r.Body.cap_id

Invoke-Api -Path "/budgets/company-caps$(q)" -Description "GET /budgets/company-caps"

$r = Invoke-Api -Method POST -Path "/budgets/cc-versions$(q)" -Body @{
    cost_centre_id  = $state.CostCentreId
    year_id         = $state.YearId
    currency        = "GBP"
    budget_minor    = 10000000
    override_reason = "Initial allocation for procurement"
} -Description "POST /budgets/cc-versions"
$state.VersionId = $r.Body.version_id

Invoke-Api -Path "/budgets/cc-versions$(q)" -Description "GET /budgets/cc-versions"
Invoke-Api -Path "/budgets/cc-versions/$($state.VersionId)$(q)" -Description "GET budget version"

# ------------------------------------------------------------------
# 19. User Budgets
# ------------------------------------------------------------------
Write-Step "19. User Budgets"
Invoke-Api -Method POST -Path "/user-budgets/assignments$(q)" -Body @{
    user_id        = $state.UserId
    cost_centre_id = $state.CostCentreId
    is_primary     = $true
    effective_from = "2026-01-01"
    effective_to   = "2026-12-31"
} -Description "POST /user-budgets/assignments"
Invoke-Api -Path "/user-budgets/assignments$(q)" -Description "GET /user-budgets/assignments"

$r = Invoke-Api -Method POST -Path "/user-budgets/limits$(q)" -Body @{
    user_id             = $state.UserId
    cost_centre_id      = $state.CostCentreId
    year_id             = $state.YearId
    limit_type          = "requester"
    window_type         = "month"
    limit_amount_minor  = 5000000
    carry_forward_enabled = $false
    window_start        = "2026-01-01"
    window_end          = "2026-12-31"
} -Description "POST /user-budgets/limits"
$state.LimitId = $r.Body.limit_id

Invoke-Api -Path "/user-budgets/limits$(q)" -Description "GET /user-budgets/limits"
Invoke-Api -Path "/user-budgets/limits/summary/$($state.UserId)$(q)" -Description "GET user budget summary"

# ------------------------------------------------------------------
# 20. Approval Policies
# ------------------------------------------------------------------
Write-Step "20. Approval Policies"
Invoke-Api -Method POST -Path "/approval-policies$(q)" -Body @{
    name                  = "Standard Procurement Approval"
    description           = "Two-stage approval for purchase requests"
    cost_centre_id        = $state.CostCentreId
    routing_mode          = "hierarchical"
    broadcast_n           = 3
    sox_sod_enforced      = $true
    partial_approval_mode = "block"
    zero_value_mode       = "auto"
    stages                = @(
        @{
            stage_order              = 1
            name                     = "Line Manager Approval"
            parallel_allowed         = $false
            min_approvers            = 1
            escalation_timeout_hours = 48
            conditions               = @(
                @{ field = "amount"; operator = "gte"; value = 100000; logic = "AND" }
            )
            approvers                = @(
                @{ approver_type = "org_unit_manager"; org_unit_id = $state.OrgUnitId }
            )
        },
        @{
            stage_order              = 2
            name                     = "Finance Director Approval"
            parallel_allowed         = $false
            min_approvers            = 1
            escalation_timeout_hours = 72
            conditions               = @(
                @{ field = "amount"; operator = "gte"; value = 500000; logic = "AND" }
            )
            approvers                = @(
                @{ approver_type = "role"; role_code = "finance_director" }
            )
        }
    )
} -Description "POST /approval-policies"
Invoke-Api -Path "/approval-policies$(q)" -Description "GET /approval-policies"

# ------------------------------------------------------------------
# 21. Purchase Requests
# ------------------------------------------------------------------
Write-Step "21. Purchase Requests"
$r = Invoke-Api -Method POST -Path "/purchase-requests$(q)" -Body @{
    cost_centre_id = $state.CostCentreId
    vendor_id      = $state.VendorId
    category_id    = $state.CategoryId
    description    = "Office stationery order for Q1"
    line_items     = @(
        @{
            product_id       = $state.ProductId
            qty              = 10
            unit_price_minor = 1299
            description      = "Blue Ballpoint Pen (Pack of 50)"
        }
    )
    amount_minor   = 12990
    currency       = "GBP"
    notes          = "Urgent — needed by end of week"
} -Description "POST /purchase-requests"
$state.PrId = $r.Body.request_id

Invoke-Api -Path "/purchase-requests$(q)" -Description "GET /purchase-requests"
Invoke-Api -Path "/purchase-requests/$($state.PrId)$(q)" -Description "GET purchase request by id"
Invoke-Api -Path "/purchase-requests/my-tasks$(q)" -Description "GET my approval tasks"

# Decide on approval task
$tasks = Invoke-Api -Path "/purchase-requests/my-tasks$(q)" -Description "Fetch tasks for decide"
if ($tasks.Body -and $tasks.Body.Count -gt 0) {
    $taskId = $tasks.Body[0].task_id
    Invoke-Api -Method POST -Path "/purchase-requests/tasks/$taskId/decide$(q)" `
        -Body @{ decision = "approve"; note = "Approved — within budget" } `
        -Description "POST decide on approval task"
}

# ------------------------------------------------------------------
# 22. Budget Change Requests
# ------------------------------------------------------------------
Write-Step "22. Budget Change Requests"
Invoke-Api -Method POST -Path "/budget-change-requests/top-up$(q)" -Body @{
    cost_centre_id      = $state.CostCentreId
    from_version_id     = $state.VersionId
    to_version_id       = $state.VersionId
    amount_minor        = 500000
    justification       = "Emergency maintenance supplies needed"
} -Description "POST /budget-change-requests/top-up"

Invoke-Api -Path "/budget-change-requests$(q)" -Description "GET /budget-change-requests"

# ------------------------------------------------------------------
# 23. Subscriptions
# ------------------------------------------------------------------
Write-Step "23. Subscriptions"
Invoke-Api -Path "/subscriptions/active$(q)" -Description "GET /subscriptions/active"
Invoke-Api -Path "/subscriptions/whoami" -Description "GET /subscriptions/whoami"

# ------------------------------------------------------------------
# 24. Data Intelligence — Graph & Vector Verification
# ------------------------------------------------------------------
if (-not $SkipDataIntelVerify) {
    Write-Step "24. Data Intelligence — Graph & Vector Verification"

    Write-Info "24.1 Waiting for outbox worker to consume provisioning events..."
    Write-Info "     (The data-intelligence-worker polls outbox_event_delivery)"
    Write-Info "     (Ensure the worker is running: python -m data_intelligence_service.workers.consumer_standalone)"
    Wait-ForOutbox -Label "tenant, site, store, user, product, vendor, org_unit, category events"

    Write-Info "24.2 Check tenant topology in Neo4j graph"
    Invoke-DataIntel -Path "/graph/tenant/$tid/topology" `
        -Description "DI GET /graph/tenant/{tenant_id}/topology" `
        -AllowNotFound $true

    if ($state.StoreId) {
        Write-Info "24.3 Check store products in Neo4j graph"
        Invoke-DataIntel -Path "/graph/store/$($state.StoreId)/products" `
            -Description "DI GET /graph/store/{store_id}/products" `
            -AllowNotFound $true
    }

    if ($state.ProductId) {
        Write-Info "24.4 Check product-store mappings in Neo4j graph"
        Invoke-DataIntel -Path "/graph/product/$($state.ProductId)/stores" `
            -Description "DI GET /graph/product/{product_id}/stores" `
            -AllowNotFound $true
    }

    if ($state.UserId) {
        Write-Info "24.5 Check user context + hierarchy in Neo4j graph"
        Invoke-DataIntel -Path "/graph/user-context/$($state.UserId)" `
            -Description "DI GET /graph/user-context/{user_id}" `
            -AllowNotFound $true
        Invoke-DataIntel -Path "/graph/user-hierarchy/$($state.UserId)" `
            -Description "DI GET /graph/user-hierarchy/{user_id}" `
            -AllowNotFound $true
    }

    if ($state.UserId) {
        Write-Info "24.6 Check approved products for user (graph + approved ranges)"
        Invoke-DataIntel -Path "/graph/approved-products/$($state.UserId)" `
            -Description "DI GET /graph/approved-products/{user_id}" `
            -AllowNotFound $true
    }

    if ($state.OrgUnitId) {
        Write-Info "24.7 Check approved products for org unit"
        Invoke-DataIntel -Path "/graph/approved-products/org-unit/$($state.OrgUnitId)" `
            -Description "DI GET /graph/approved-products/org-unit/{org_unit_id}" `
            -AllowNotFound $true
    }

    Write-Info ""
    Write-Info "NOTE: If any checks show 'not found', the data-intelligence worker"
    Write-Info "may still be processing. Increase -OutboxWaitSeconds (default 10s)"
    Write-Info "or check worker logs for errors."
}

# ------------------------------------------------------------------
# 25. Health (Final)
# ------------------------------------------------------------------
Write-Step "25. Final Health Check"
Invoke-Api -Path "/health" -Description "GET /health (provisioning)"

if (-not $SkipDataIntelVerify) {
    Invoke-DataIntel -Path "/health" -Description "DI GET /health (data-intelligence)" -AllowNotFound $true
}

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
Write-Host "`n" -NoNewline
Write-Host "============================================================" -ForegroundColor Green
Write-Host "              PROVISIONING TEST SUITE COMPLETE               " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Provisioning API:  $BaseUrl"
Write-Host "  Data Intel API:    $DataIntelUrl"
Write-Host "  Tenant ID:         $($state.TenantId)"
Write-Host "  Admin User:        $($state.AdminUserId)"
Write-Host "  Site:              $($state.SiteId)"
Write-Host "  Store:             $($state.StoreId)"
Write-Host "  User:              $($state.UserId)"
Write-Host "  Org Unit:          $($state.OrgUnitId)"
Write-Host "  Vendor:            $($state.VendorId)"
Write-Host "  Cost Centre:       $($state.CostCentreId)"
Write-Host "  Category:          $($state.CategoryId)"
Write-Host "  Product:           $($state.ProductId)"
Write-Host "  Approved Range:    $($state.ApprovedRangeId)"
Write-Host "  Calendar:          $($state.CalendarId)"
Write-Host "  Year:              $($state.YearId)"
Write-Host "  Purchase Req:      $($state.PrId)"
Write-Host ""
Write-Host "  Data Intelligence Graph Verification:"
Write-Host "    /graph/tenant/$tid/topology"
Write-Host "    /graph/store/$($state.StoreId)/products"
Write-Host "    /graph/user-context/$($state.UserId)"
Write-Host ""
Write-Host "  Re-run commands:"
Write-Host "    ./test_provisioning.ps1 -SkipSeed -SkipOnboarding -TenantId '$($state.TenantId)' -Token 'TOKEN'"
Write-Host "    ./test_provisioning.ps1 -SkipSeed -SkipOnboarding -TenantId '$($state.TenantId)' -Token 'TOKEN' -SkipDataIntelVerify"
Write-Host ""
