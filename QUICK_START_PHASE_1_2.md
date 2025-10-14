# ⚡ Quick Start - Phase 1 & 2 Features

## 🚀 3-Minute Setup

### 1. Run Database Migration

```bash
alembic upgrade head
```

### 2. Start Services

```bash
# Provisioning (already running on port 8000)
# If not: cd services/provisioning && python3 main.py &

# Start other services
cd services/identity && python3 main.py &
cd services/cv_connector && python3 main.py &
cd services/cv_gateway && python3 main.py &
```

### 3. Launch Dashboard

```bash
./start_streamlit_phase1_phase2.sh
```

**Dashboard**: http://localhost:8503

---

## ⚡ Quick Test

```bash
./tests/test_provisioning_features.sh
```

**Expected Output**:

```
✅ Tenant created
✅ Bulk import successful
✅ Site with devices created
```

---

## 🎯 What You Can Do Now

### 1. Bulk Import Users (Pro/Ent)

- Go to dashboard tab "👥 Bulk User Import"
- Add 3 users, enable API keys
- Click "Import Users"

### 2. Configure SSO (Pro/Ent)

- Go to tab "🔐 OAuth/SSO"
- Add Azure AD or Google provider
- Initiate OAuth flow

### 3. Test Entry Methods

- Go to tab "🚪 Entry Methods"
- Generate QR code
- Test card entry (RFID)
- Test biometric entry (Face)

### 4. Create Smart Site

- Go to tab "🏢 Site Registry"
- Set cameras, sensors, entry devices
- Create site

### 5. Monitor Devices

- Go to tab "📟 Device Monitoring"
- View all devices
- Update device status
- Create alerts

---

## 📚 Full Documentation

- **API Reference**: `/docs/PHASE_1_2_API_DOCUMENTATION.md`
- **Complete Guide**: `/docs/FEATURE_IMPLEMENTATION_PROGRESS.md`
- **Delivery Summary**: `/PHASE_1_2_DELIVERY_COMPLETE.md`

---

## 🎊 Ready for Phase 3!

All Phase 1 & 2 features are **production-ready**.

Next: **Phase 3 - Catalogue & Inventory** (SKU Management, Barcodes, Bundles)
