#!/bin/bash

# Start Payments Service Streamlit App
echo "Starting Payments Service Streamlit App..."

# Check if Streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "Streamlit is not installed. Installing..."
    pip install streamlit
fi

# Navigate to demo directory
cd demo

# Start Streamlit app
streamlit run streamlit_payments.py --server.port 8504 --server.address 0.0.0.0

echo "Payments Service Streamlit App started on http://localhost:8504"

