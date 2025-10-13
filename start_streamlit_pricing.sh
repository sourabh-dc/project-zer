#!/bin/bash

# Start Pricing Service Streamlit App
echo "Starting Pricing Service Streamlit App..."

# Check if Streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "Streamlit is not installed. Installing..."
    pip install streamlit
fi

# Navigate to demo directory
cd demo

# Start Streamlit app
streamlit run streamlit_pricing.py --server.port 8505 --server.address 0.0.0.0

echo "Pricing Service Streamlit App started on http://localhost:8505"

