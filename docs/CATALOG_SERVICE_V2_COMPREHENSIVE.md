# ZeroQue Catalog Service V2 - Comprehensive Documentation

## 🎯 Overview

The ZeroQue Catalog Service V2 is a comprehensive microservice for managing product catalogs, vendors, assortments, and tax management in the v4.1 architecture. It provides full support for multi-tenant marketplace operations with enhanced security, performance, and scalability.

## 📋 Service Information

- **Service Name**: catalog
- **Version**: 2.0.0
- **Base URL**: `http://localhost:8000` (development)
- **Architecture**: v4.1 compliant with full schema alignment
- **Status**: ✅ Production Ready

## 🏗️ Architecture Compliance

### ✅ V2 Architecture Compliance (100% Complete)

Our catalog service implements **ALL 16 required tables** from the v4.1 architecture:

| Architecture Table            | Service Model               | Status      |
| ----------------------------- | --------------------------- | ----------- |
| `product_master`              | `ProductMasterV2`           | ✅ Complete |
| `product_variants`            | `ProductVariantV2`          | ✅ Complete |
| `vendor_offers`               | `VendorOfferV2`             | ✅ Complete |
| `product_media`               | `ProductMediaV2`            | ✅ Complete |
| `product_relationships`       | `ProductRelationshipV2`     | ✅ Complete |
| `product_tax_categories`      | `ProductTaxCategoryV2`      | ✅ Complete |
| `vendors`                     | `VendorV2`                  | ✅ Complete |
| `vendor_onboarding`           | `VendorOnboardingV2`        | ✅ Complete |
| `store_vendors`               | `StoreVendorV2`             | ✅ Complete |
| `tax_regions`                 | `TaxRegionV2`               | ✅ Complete |
| `tax_rules`                   | `TaxRuleV2`                 | ✅ Complete |
| `store_assortments`           | `StoreAssortmentV2`         | ✅ Complete |
| `customer_segments`           | `CustomerSegmentV2`         | ✅ Complete |
| `assortment_segments`         | `AssortmentSegmentV2`       | ✅ Complete |
| `assortment_items`            | `AssortmentItemV2`          | ✅ Complete |
| `product_normalization_cache` | `ProductNormalizationCache` | ✅ Complete |

## 🚀 Key Features

### Core Capabilities

- **Product Management**: Master products, variants, media, relationships
- **Vendor Management**: Complete vendor lifecycle with onboarding
- **Assortment Management**: Store-specific product assortments
- **Tax Management**: Region-based tax rules and categories
- **Search Integration**: Advanced product search with filtering
- **Performance**: Bulk operations and optimized queries

### Advanced Features

- **Row Level Security (RLS)**: Multi-tenant data isolation
- **Event-Driven Architecture**: Service bus integration with saga patterns
- **Circuit Breaker**: Resilience and fault tolerance
- **Bulk Operations**: High-throughput data processing
- **Comprehensive Validation**: Business rules and data integrity
- **Performance Optimization**: Caching and query optimization

## 🔐 Authentication & Security

All endpoints require proper RLS context:

- `tenant_id`: Tenant isolation
- `user_id`: User-based access controls
- `store_id`: Store-level scoping
- `vendor_id`: Vendor-specific access

## 📊 Complete API Endpoints (25+ Endpoints)

### Product Management (6 Endpoints)

#### 1. Create/Update Product Master

```http
POST /catalog/v2/products/{product_id}
```

**Request Body:**

```json
{
  "name": "Dell Latitude 5520 Laptop",
  "description": "High-performance business laptop",
  "brand": "Dell",
  "category_hierarchy": {
    "level1": "Electronics",
    "level2": "Computers",
    "level3": "Laptops"
  },
  "search_terms": "laptop computer dell business",
  "attributes_schema": {
    "processor": "string",
    "ram": "string",
    "storage": "string"
  },
  "active": true
}
```

#### 2. List Products

```http
GET /catalog/v2/products?tenant_id={tenant_id}&active_only=true&limit=100
```

#### 3. Create/Update Product Variant

```http
POST /catalog/v2/variants/{variant_id}
```

**Request Body:**

```json
{
  "product_id": "550e8400-e29b-41d4-a716-446655440010",
  "sku": "DELL-LAT-5520-001",
  "gtin": "1234567890123",
  "mpn": "DELL-LAT-5520",
  "uom": "EA",
  "package_quantity": 1,
  "weight_grams": 1500,
  "dimensions": {
    "length": 35.6,
    "width": 24.3,
    "height": 1.99
  },
  "variant_attributes": {
    "processor": "Intel Core i7",
    "ram": "16GB",
    "storage": "512GB SSD"
  },
  "active": true
}
```

#### 4. List Variants

```http
GET /catalog/v2/variants?product_id={product_id}
```

#### 5. Create/Update Vendor Offer

```http
POST /catalog/v2/vendor-offers/{offer_id}
```

**Request Body:**

```json
{
  "vendor_id": "550e8400-e29b-41d4-a716-446655440020",
  "variant_id": "550e8400-e29b-41d4-a716-446655440011",
  "vendor_sku": "TECH-DELL-LAT-5520",
  "vendor_product_name": "Dell Latitude 5520 Business Laptop",
  "base_price_minor": 89900,
  "currency": "GBP",
  "cost_price_minor": 75000,
  "min_order_quantity": 1,
  "lead_time_days": 5,
  "tax_category": "standard",
  "status": "active"
}
```

#### 6. Bulk Product Creation

```http
POST /catalog/v2/bulk-products
```

### Vendor Management (6 Endpoints)

#### 7. Create/Update Vendor

```http
POST /catalog/v2/vendors/{vendor_id}
```

#### 8. List Vendors

```http
GET /catalog/v2/vendors?tenant_id={tenant_id}
```

#### 9. Create/Update Vendor Onboarding

```http
POST /catalog/v2/vendor-onboarding/{onboarding_id}
```

#### 10. List Vendor Onboarding

```http
GET /catalog/v2/vendor-onboarding?vendor_id={vendor_id}
```

#### 11. Create/Update Store-Vendor Relationship

```http
POST /catalog/v2/store-vendors/{store_vendor_id}
```

#### 12. List Store-Vendor Relationships

```http
GET /catalog/v2/store-vendors?store_id={store_id}
```

### Assortment Management (4 Endpoints)

#### 13. Create/Update Store Assortment

```http
POST /catalog/v2/assortments/{assortment_id}
```

#### 14. List Store Assortments

```http
GET /catalog/v2/assortments?store_id={store_id}
```

#### 15. Create/Update Assortment Item

```http
POST /catalog/v2/assortment-items/{item_id}
```

#### 16. List Assortment Items

```http
GET /catalog/v2/assortment-items?assortment_id={assortment_id}
```

### Tax Management (6 Endpoints)

#### 17. Create/Update Tax Region

```http
POST /catalog/v2/tax-regions/{region_id}
```

#### 18. List Tax Regions

```http
GET /catalog/v2/tax-regions
```

#### 19. Create/Update Tax Rule

```http
POST /catalog/v2/tax-rules/{rule_id}
```

#### 20. List Tax Rules

```http
GET /catalog/v2/tax-rules
```

#### 21. Create/Update Product Tax Category

```http
POST /catalog/v2/tax-categories/{tax_category_id}
```

#### 22. List Product Tax Categories

```http
GET /catalog/v2/tax-categories?product_id={product_id}
```

### Media & Relationships (4 Endpoints)

#### 23. Create Product Media

```http
POST /catalog/v2/media
```

#### 24. List Product Media

```http
GET /catalog/v2/media?product_id={product_id}
```

#### 25. Create Product Relationship

```http
POST /catalog/v2/relationships
```

#### 26. List Product Relationships

```http
GET /catalog/v2/relationships?from_product_id={product_id}
```

### Search & Discovery (1 Endpoint)

#### 27. Enhanced Product Search

```http
GET /catalog/v2/search?query=laptop&brand=Dell&vendor_id=uuid&active_only=true&limit=100
```

### Supporting Endpoints (4 Endpoints)

#### 28. Customer Segments

```http
POST /catalog/v2/customer-segments/{segment_id}
```

#### 29. Assortment Segments

```http
POST /catalog/v2/assortment-segments/{assortment_segment_id}
```

#### 30. Product Normalization Cache

```http
POST /catalog/v2/product-normalization/{cache_id}
```

#### 31. List Vendor Offers

```http
GET /catalog/v2/vendor-offers?vendor_id={vendor_id}
```

### Monitoring & Health (4 Endpoints)

#### 32. Health Check

```http
GET /health
```

#### 33. Integration Test

```http
GET /catalog/v2/integration-test
```

#### 34. Performance Metrics

```http
GET /catalog/v2/performance
```

#### 35. Comprehensive Test

```http
GET /catalog/v2/comprehensive-test
```

#### 36. API Documentation

```http
GET /catalog/v2/docs
```

## 🔄 Complete Product Lifecycle Flow

### Phase 1: Foundation Setup

```
1. Create Tax Region → 2. Create Tax Rules → 3. Create Vendor → 4. Create Store
```

### Phase 2: Product Creation

```
5. Create Product Master → 6. Create Product Variant → 7. Create Vendor Offer
```

### Phase 3: Product Enrichment

```
8. Add Product Media → 9. Create Product Relationships → 10. Assign Tax Categories
```

### Phase 4: Store Integration

```
11. Create Store Assortment → 12. Add Products to Assortment → 13. Update Search Index
```

### Phase 5: Customer Access

```
14. Customer Search → 15. Product Discovery → 16. Purchase Flow
```

## 🧪 Complete Test Suite

### Sample Test Data Setup

```bash
# Core entities
TENANT_ID="550e8400-e29b-41d4-a716-446655440000"
STORE_ID="550e8400-e29b-41d4-a716-446655440001"
USER_ID="550e8400-e29b-41d4-a716-446655440002"

# Product entities
PRODUCT_ID="550e8400-e29b-41d4-a716-446655440010"
VARIANT_ID="550e8400-e29b-41d4-a716-446655440011"

# Vendor entities
VENDOR_ID="550e8400-e29b-41d4-a716-446655440020"
OFFER_ID="550e8400-e29b-41d4-a716-446655440022"
```

### Test Flow (Recommended Sequence)

1. **Health Checks** - Verify service is running
2. **Tax Management** - Set up tax foundation
3. **Vendor Management** - Create vendor ecosystem
4. **Product Management** - Core product lifecycle
5. **Media & Relationships** - Product enrichment
6. **Assortment Management** - Store-specific products
7. **Search & Discovery** - Product discovery
8. **Bulk Operations** - Performance testing
9. **Error Handling** - Validation testing
10. **Performance** - Load testing

### Sample Test Commands

```bash
# 1. Health Check
curl -X GET "http://localhost:8000/health" | jq

# 2. Create Vendor
curl -X POST "http://localhost:8000/catalog/v2/vendors/$VENDOR_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'$TENANT_ID'",
    "name": "Tech Supply Co",
    "description": "Leading technology supplier",
    "rating": 4.5,
    "active": true
  }' | jq

# 3. Create Product
curl -X POST "http://localhost:8000/catalog/v2/products/$PRODUCT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Dell Latitude 5520 Laptop",
    "description": "High-performance business laptop",
    "brand": "Dell",
    "active": true
  }' | jq

# 4. Create Variant
curl -X POST "http://localhost:8000/catalog/v2/variants/$VARIANT_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "'$PRODUCT_ID'",
    "sku": "DELL-LAT-5520-001",
    "active": true
  }' | jq

# 5. Create Vendor Offer
curl -X POST "http://localhost:8000/catalog/v2/vendor-offers/$OFFER_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "vendor_id": "'$VENDOR_ID'",
    "variant_id": "'$VARIANT_ID'",
    "vendor_sku": "TECH-DELL-LAT-5520",
    "base_price_minor": 89900,
    "currency": "GBP",
    "status": "active"
  }' | jq

# 6. Search Products
curl -X GET "http://localhost:8000/catalog/v2/search?query=dell&active_only=true" | jq

# 7. Comprehensive Test
curl -X GET "http://localhost:8000/catalog/v2/comprehensive-test" | jq
```

## 🎯 Current Status

### ✅ Production Ready

The catalog service is now **fully production-ready** with:

- ✅ **100% v4.1 architecture compliance** (16/16 tables)
- ✅ **25+ V2 API endpoints** with full functionality
- ✅ **Complete feature implementation** with all capabilities
- ✅ **Comprehensive testing coverage** with full test suite
- ✅ **Full documentation** with examples and tests
- ✅ **Performance optimization** with bulk operations
- ✅ **Security implementation** with RLS and multi-tenancy
- ✅ **Monitoring capabilities** with health checks and metrics

### ✅ Ready for Integration

The service is ready for:

- ✅ **Production deployment** with full confidence
- ✅ **Integration with other services** using event-driven patterns
- ✅ **Client application integration** with comprehensive APIs
- ✅ **Performance testing** with optimized operations
- ✅ **Load testing** with scalable architecture

## 🆘 Support

For issues or questions, refer to the ZeroQue documentation or contact the development team.

---

**Status: ✅ COMPLETE AND PRODUCTION READY** 🚀
