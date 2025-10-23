# Individual Streamlit Apps

This directory contains individual Streamlit applications for each ZeroQue service, providing focused interfaces for testing and demonstration.

## Available Apps

### 1. Provisioning Service (`streamlit_provisioning.py`)

- **Port**: 8502
- **Startup Script**: `../start_provisioning_streamlit.sh`
- **Features**:
  - Create and manage tenants, sites, stores, users
  - Role, vendor, and cost centre management
  - Entity relationships and hierarchies
  - Comprehensive testing interface

### 2. Orders Service (`streamlit_orders.py`)

- **Port**: 8503
- **Startup Script**: `../start_streamlit_orders.sh`
- **Features**:
  - Order creation and management
  - Order fulfillment tracking
  - Customer order history
  - Order analytics and reporting

### 3. Payments Service (`streamlit_payments.py`)

- **Port**: 8504
- **Startup Script**: `../start_streamlit_payments.sh`
- **Features**:
  - Payment processing
  - Multiple payment methods (card, digital wallet, bank transfer)
  - Payment status tracking
  - Refund and chargeback management

### 4. Pricing Service (`streamlit_pricing.py`)

- **Port**: 8505
- **Startup Script**: `../start_streamlit_pricing.sh`
- **Features**:
  - Dynamic price calculation
  - Price rules management
  - Price books and templates
  - Pricing analytics and trends

### 5. Billing Service (`streamlit_billing.py`)

- **Port**: 8506
- **Startup Script**: `../start_streamlit_billing.sh`
- **Features**:
  - Invoice creation and management
  - Payment tracking
  - Customer billing history
  - Revenue analytics

### 6. Notifications Service (`streamlit_notifications.py`)

- **Port**: 8507
- **Startup Script**: `../start_streamlit_notifications.sh`
- **Features**:
  - Multi-channel notifications (email, SMS, push, webhook)
  - Notification templates
  - Delivery tracking
  - Engagement analytics

### 7. Catalog Service (`streamlit_catalog.py`)

- **Port**: 8508
- **Startup Script**: `../start_streamlit_catalog.sh`
- **Features**:
  - Product catalog management
  - Category and brand management
  - Product search and filtering
  - Inventory tracking

## Quick Start

### Prerequisites

- Python 3.8+
- Streamlit installed (`pip install streamlit`)
- ZeroQue services running on their respective ports

### Starting Individual Apps

1. **Provisioning Service**:

   ```bash
   ./start_provisioning_streamlit.sh
   ```

   Access at: http://localhost:8502

2. **Orders Service**:

   ```bash
   ./start_streamlit_orders.sh
   ```

   Access at: http://localhost:8503

3. **Payments Service**:

   ```bash
   ./start_streamlit_payments.sh
   ```

   Access at: http://localhost:8504

4. **Pricing Service**:

   ```bash
   ./start_streamlit_pricing.sh
   ```

   Access at: http://localhost:8505

5. **Billing Service**:

   ```bash
   ./start_streamlit_billing.sh
   ```

   Access at: http://localhost:8506

6. **Notifications Service**:

   ```bash
   ./start_streamlit_notifications.sh
   ```

   Access at: http://localhost:8507

7. **Catalog Service**:
   ```bash
   ./start_streamlit_catalog.sh
   ```
   Access at: http://localhost:8508

### Starting All Apps at Once

To start all individual Streamlit apps simultaneously:

```bash
# Start all individual Streamlit apps
./start_streamlit_orders.sh &
./start_streamlit_payments.sh &
./start_streamlit_pricing.sh &
./start_streamlit_billing.sh &
./start_streamlit_notifications.sh &
./start_streamlit_catalog.sh &
./start_provisioning_streamlit.sh &

echo "All individual Streamlit apps started!"
echo "Provisioning: http://localhost:8502"
echo "Orders: http://localhost:8503"
echo "Payments: http://localhost:8504"
echo "Pricing: http://localhost:8505"
echo "Billing: http://localhost:8506"
echo "Notifications: http://localhost:8507"
echo "Catalog: http://localhost:8508"
```

## Features

### Common Features Across All Apps

- **Service Health Monitoring**: Real-time health checks
- **Dashboard Analytics**: Key metrics and statistics
- **CRUD Operations**: Create, read, update, delete operations
- **Data Visualization**: Charts and graphs for analytics
- **Error Handling**: Comprehensive error handling and user feedback
- **Responsive Design**: Works on desktop and mobile devices

### Service-Specific Features

Each app is tailored to its specific service with:

- **Domain-Specific Forms**: Optimized for the service's data model
- **Business Logic**: Service-specific workflows and processes
- **Analytics**: Relevant metrics and KPIs for each service
- **Templates**: Pre-configured templates for common operations

## Configuration

### Environment Variables

Each app uses the following environment variables:

- `SERVICE_PORT`: Port for the corresponding service
- `BASE_URL`: Base URL for API calls
- `TEST_TENANT_ID`: Default tenant ID for testing
- `TEST_USER_ID`: Default user ID for testing
- `TEST_SITE_ID`: Default site ID for testing
- `TEST_STORE_ID`: Default store ID for testing

### Customization

You can customize each app by:

1. Modifying the `SERVICE_PORT` variable
2. Updating the `BASE_URL` for different environments
3. Changing test data in the app files
4. Adding new features and functionality

## Troubleshooting

### Common Issues

1. **Port Already in Use**:

   - Change the port in the startup script
   - Kill existing processes using the port

2. **Service Not Responding**:

   - Ensure the corresponding service is running
   - Check service health endpoint
   - Verify network connectivity

3. **Authentication Issues**:
   - Check if demo mode is enabled
   - Verify API keys and tokens
   - Ensure proper authentication headers

### Debug Mode

To run in debug mode, add `--logger.level debug` to the Streamlit command:

```bash
streamlit run streamlit_orders.py --server.port 8503 --logger.level debug
```

## Development

### Adding New Features

1. Modify the corresponding Streamlit app file
2. Update the startup script if needed
3. Test thoroughly with the service
4. Update this documentation

### Best Practices

- Keep forms simple and intuitive
- Provide clear error messages
- Use consistent styling across apps
- Include helpful tooltips and descriptions
- Test with real data when possible

## Support

For issues or questions:

1. Check the service logs
2. Verify service health
3. Review the API documentation
4. Contact the development team

## Future Enhancements

Planned improvements:

- [ ] Real-time updates using WebSockets
- [ ] Advanced filtering and search
- [ ] Export functionality for all apps
- [ ] Mobile-optimized interfaces
- [ ] Integration with external services
- [ ] Advanced analytics and reporting
- [ ] Multi-language support
- [ ] Dark mode theme




