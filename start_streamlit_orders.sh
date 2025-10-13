#!/bin/bash

# Start Orders Service Streamlit App
echo "Starting Orders Service Streamlit App..."

# Check if Streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "Streamlit is not installed. Installing..."
    pip install streamlit
fi

# Navigate to demo directory
cd demo

# Start Streamlit app
streamlit run streamlit_orders.py --server.port 8503 --server.address 0.0.0.0

echo "Orders Service Streamlit App started on http://localhost:8503"

