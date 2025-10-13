#!/bin/bash

# Start Billing Service Streamlit App
echo "Starting Billing Service Streamlit App..."

# Check if Streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "Streamlit is not installed. Installing..."
    pip install streamlit
fi

# Navigate to demo directory
cd demo

# Start Streamlit app
streamlit run streamlit_billing.py --server.port 8506 --server.address 0.0.0.0

echo "Billing Service Streamlit App started on http://localhost:8506"

