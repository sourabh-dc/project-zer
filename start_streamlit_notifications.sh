#!/bin/bash

# Start Notifications Service Streamlit App
echo "Starting Notifications Service Streamlit App..."

# Check if Streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "Streamlit is not installed. Installing..."
    pip install streamlit
fi

# Navigate to demo directory
cd demo

# Start Streamlit app
streamlit run streamlit_notifications.py --server.port 8507 --server.address 0.0.0.0

echo "Notifications Service Streamlit App started on http://localhost:8507"

