# ZeroQue V2 Streamlit E2E Demo

## Overview

The ZeroQue V2 Streamlit application provides a comprehensive end-to-end testing interface for the multi-tenant marketplace platform. This interactive web application allows you to test all V2 services and their integration.

## Features

### 🏢 Tenant Management
- Create and manage tenants in the multi-tenant architecture
- Support for different tenant types (marketplace, customer, enterprise)
- Tenant listing and browsing

### 🏪 Site & Store Management
- Create and manage sites (warehouses, distribution centers, etc.)
- Create and manage stores (cashierless, traditional, kiosk, vending)
- Geographic location support with latitude/longitude

### 👥 User & Vendor Management
- User creation and management with role-based access
- Vendor onboarding and management
- Vendor rating and description management

### 📦 Product & Catalog Management
- Placeholder for future catalog service integration
- Product master and variant management (planned)
- Vendor offers and store assortments (planned)

### 💰 Pricing & Pricebooks
- Advanced pricebook creation and management
- Price resolution testing
- Price rule management
- Multi-currency support

### 🛒 Order Management
- Order creation with saga orchestration
- Sub-order management for vendor splits
- Returns and refunds processing
- Payment method support (trade, card, cash)

### 📊 Browse & Reports
- Data browsing across all services
- System health monitoring
- Session state management

## Usage

### Starting the Application

#### Option 1: Standalone
```bash
# Ensure services are running
curl http://localhost:8201/health  # Provisioning
curl http://localhost:8203/health  # Orders  
curl http://localhost:8209/health  # Pricing

# Start Streamlit app
streamlit run demo/streamlit_e2e_v2.py --server.port 8501
```

#### Option 2: Docker Compose
```bash
# Start all V2 services including Streamlit
docker-compose up provisioning orders pricing streamlit-demo-v2 -d

# Access the app
open http://localhost:8501
```

### Service Dependencies

The Streamlit app requires the following V2 services to be running:

- **Provisioning Service** (Port 8201): Tenant, site, store, user management
- **Orders Service** (Port 8203): Order processing with saga orchestration
- **Pricing Service** (Port 8209): Advanced pricing with pricebooks and rules

### Testing Workflow

1. **Health Check**: Verify all services are healthy
2. **Tenant Setup**: Create a tenant for your marketplace
3. **Infrastructure**: Create sites and stores
4. **Users & Vendors**: Set up users and onboard vendors
5. **Pricing**: Configure pricebooks and pricing rules
6. **Orders**: Test the complete order flow
7. **Browse**: Explore data and generate reports

## API Endpoints Tested

### Provisioning Service
- `PUT /provisioning/v2/tenants/{tenant_id}` - Create/update tenant
- `GET /provisioning/v2/tenants` - List tenants
- `PUT /provisioning/v2/sites/{site_id}` - Create/update site
- `GET /provisioning/v2/sites` - List sites
- `PUT /provisioning/v2/stores/{store_id}` - Create/update store
- `GET /provisioning/v2/stores` - List stores
- `PUT /provisioning/v2/users/{user_id}` - Create/update user
- `GET /provisioning/v2/users` - List users
- `PUT /provisioning/v2/vendors/{vendor_id}` - Create/update vendor
- `GET /provisioning/v2/vendors` - List vendors

### Pricing Service
- `PUT /pricing/v2/pricebooks/{pricebook_id}` - Create/update pricebook
- `GET /pricing/v2/pricebooks` - List pricebooks
- `POST /pricing/v2/resolve` - Resolve price
- `GET /pricing/v2/price-rules` - List price rules

### Orders Service
- `POST /orders/v2` - Create order
- `GET /orders/v2` - List orders
- `GET /orders/v2/{order_id}` - Get order details
- `POST /orders/v2/returns` - Create return
- `POST /orders/v2/refunds` - Create refund

## Key V2 Features Demonstrated

### Multi-Tenancy
- Complete tenant isolation with UUID-based identification
- Tenant type support (marketplace, customer, enterprise)
- Cross-tenant resource sharing

### Marketplace Model
- Vendor management and onboarding
- Product catalog with vendor-specific offers
- Store assortments and customer segmentation

### Advanced Pricing
- Hierarchical pricebook system
- Dynamic pricing rules and conditions
- Multi-currency support with exchange rates
- Price caching and versioning

### Order Processing
- Saga orchestration for distributed transactions
- Vendor-specific sub-orders
- Commission and settlement tracking
- Returns and refunds management

### Event-Driven Architecture
- Service health monitoring
- Real-time status updates
- Error handling and recovery

## Configuration

### Environment Variables
```bash
PROVISIONING_BASE=http://localhost:8201
ORDERS_BASE=http://localhost:8203
PRICING_BASE=http://localhost:8209
```

### Session State
The app maintains session state for:
- Tenant, site, store, user, and vendor IDs
- Form data and selections
- Generated UUIDs for consistency

## Troubleshooting

### Service Connection Issues
- Verify services are running: `docker-compose ps`
- Check service health: `curl http://localhost:8201/health`
- Review service logs: `docker-compose logs provisioning`

### UUID Issues
- All V2 services use UUID-based identification
- The app automatically generates UUIDs when needed
- Use the "Generate ID" buttons for proper UUID format

### Data Dependencies
- Create tenants before sites and stores
- Create users before processing orders
- Set up vendors before creating offers

### Common Errors
- **500 Internal Server Error**: Check service logs for details
- **404 Not Found**: Verify the service is running and endpoint exists
- **400 Bad Request**: Check request payload format and required fields

## Development

### Adding New Features
1. Add new UI components in the appropriate tab
2. Implement API calls using the `api_call` helper function
3. Add response handling with `show_response` and `show_curl`
4. Update session state management as needed

### Testing New Endpoints
1. Add endpoint testing to the "Browse & Reports" tab
2. Use the data browser to explore API responses
3. Test error scenarios and edge cases

## Support

- **Service Documentation**: See `services/*/API_SPECIFICATION.md`
- **Architecture**: See `README_v2.md` and `architecture_v4.1.md`
- **Setup Guide**: See `SETUP_NEW_SYSTEM.md`

---

**ZeroQue V2 Streamlit Demo** - Interactive testing for the multi-tenant marketplace platform 🚀
