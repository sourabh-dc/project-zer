# ZeroQue Provisioning Service - Streamlit Interface

## Overview

This Streamlit application provides a comprehensive web interface for managing the ZeroQue Provisioning Service. It allows you to create, view, and manage all provisioning entities including tenants, sites, stores, users, roles, vendors, and cost centres.

## Features

### 🏢 **Tenant Management**

- Create tenants with unique names and types
- List all tenants with detailed information
- UUID generation for tenant IDs
- Support for different tenant types (customer, partner, vendor)

### 🏪 **Site Management**

- Create sites within tenants
- Optional geographic coordinates (latitude/longitude)
- Different site types (office, warehouse, retail, factory)
- Hierarchical relationship with tenants

### 🏬 **Store Management**

- Create stores within sites
- Optional precise location data
- Different store types (retail, warehouse, popup, online)
- Geographic coordinates for delivery routing

### 👥 **User Management**

- Create users within tenants
- Email address generation
- API key generation option
- Display name and contact information

### 🎭 **Role Management**

- Create roles for access control
- Unique role codes
- Role descriptions and names
- Support for hierarchical role structures

### 🏪 **Vendor Management**

- Create vendors within tenants
- Contact information and descriptions
- Business relationship management
- Vendor performance tracking

### 💰 **Cost Centre Management**

- Create cost centres for budget tracking
- Budget allocation in minor units (pence)
- Spending tracking and reporting
- Tenant-specific cost centres

### 📊 **Browse & Reports**

- Browse all entities across the system
- System health monitoring
- Session state management
- Quick actions for testing

## Prerequisites

1. **Provisioning Service**: Must be running on `http://localhost:8000`
2. **Python Dependencies**: `streamlit`, `requests`
3. **Demo API Key**: Uses `zq_demo_key_for_testing` for authentication

## Installation

```bash
# Install dependencies
pip install streamlit requests

# Ensure provisioning service is running
./start_provisioning_service.sh
```

## Usage

### Quick Start

```bash
# Start the Streamlit interface
./start_provisioning_streamlit.sh

# Or manually
cd demo
streamlit run streamlit_provisioning.py --server.port 8502
```

### Access the Interface

Open your browser and navigate to: `http://localhost:8502`

### Basic Workflow

1. **Create a Tenant**: Start by creating a tenant organization
2. **Create a Site**: Add a site within the tenant
3. **Create a Store**: Add a store within the site
4. **Create Users**: Add users to the tenant
5. **Create Roles**: Define roles for access control
6. **Create Vendors**: Add vendors to the tenant
7. **Create Cost Centres**: Set up budget tracking

## Interface Layout

### Main Tabs

1. **🏢 Tenant Management**: Create and manage tenants
2. **🏪 Site Management**: Create and manage sites
3. **🏬 Store Management**: Create and manage stores
4. **👥 User Management**: Create and manage users
5. **🎭 Role Management**: Create and manage roles
6. **🏪 Vendor Management**: Create and manage vendors
7. **💰 Cost Centre Management**: Create and manage cost centres
8. **📊 Browse & Reports**: System overview and health checks

### Key Features

- **UUID Generation**: Automatic generation of unique IDs
- **Form Validation**: Real-time validation of required fields
- **Response Display**: JSON responses with success/error indicators
- **cURL Commands**: Generated cURL commands for API testing
- **Session State**: Persistent form data across page refreshes
- **Health Monitoring**: Real-time service health checks

## API Integration

The interface integrates with the ZeroQue Provisioning Service API:

- **Base URL**: `http://localhost:8000`
- **Authentication**: API Key (`zq_demo_key_for_testing`)
- **Endpoints**: All provisioning service endpoints
- **Error Handling**: Comprehensive error display and handling

## Configuration

### Environment Variables

```bash
PROVISIONING_BASE=http://localhost:8000  # Provisioning service URL
```

### Session State

The application maintains session state for:

- Entity IDs (tenant_id, site_id, store_id, etc.)
- Form data persistence
- User preferences
- Generated values

## Troubleshooting

### Common Issues

1. **Service Not Running**: Ensure provisioning service is started
2. **Connection Errors**: Check network connectivity and service URL
3. **Authentication Errors**: Verify API key configuration
4. **Form Validation**: Check required fields are filled

### Debug Mode

Enable debug mode by setting:

```bash
export STREAMLIT_LOGGER_LEVEL=debug
```

### Health Checks

The interface includes built-in health checks:

- Service connectivity
- API endpoint availability
- Response validation
- Error reporting

## Development

### Code Structure

```
demo/
├── streamlit_provisioning.py          # Main Streamlit application
├── README_PROVISIONING_STREAMLIT.md   # This documentation
└── start_provisioning_streamlit.sh    # Startup script
```

### Key Components

- **API Helper Functions**: `api_call()`, `show_response()`, `show_curl()`
- **Session State Management**: Persistent form data
- **UI Components**: Tabs, forms, expandable sections
- **Error Handling**: Comprehensive error display
- **Health Monitoring**: Service status checks

### Customization

To customize the interface:

1. **Modify Forms**: Update form fields in each tab
2. **Add Endpoints**: Extend API integration for new endpoints
3. **Change Styling**: Modify Streamlit components and layout
4. **Add Features**: Implement new functionality as needed

## Security Notes

- **Demo Mode**: Uses demo API key for testing
- **Production**: Replace with proper authentication
- **Validation**: Client-side validation only
- **Server-side**: All validation handled by provisioning service

## Support

For issues and questions:

1. Check service health status in the interface
2. Verify provisioning service is running
3. Check API key configuration
4. Review error messages in the interface
5. Check service logs for detailed information

## Version History

### v1.0.0 (Current)

- Complete CRUD interface for all provisioning entities
- Health monitoring and system status
- Session state management
- Comprehensive error handling
- cURL command generation
- Responsive design with tabs and expandable sections

The ZeroQue Provisioning Service Streamlit interface provides a user-friendly way to manage all provisioning entities with real-time feedback and comprehensive error handling.
