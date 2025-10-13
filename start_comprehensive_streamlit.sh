#!/bin/bash

# Start Comprehensive Streamlit App
echo "Starting ZeroQue Comprehensive Streamlit App..."

# Check if Streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "Streamlit is not installed. Installing..."
    pip install streamlit plotly pandas
fi

# Navigate to demo directory
cd demo

# Start Streamlit app
streamlit run streamlit_comprehensive_app.py --server.port 8501 --server.address 0.0.0.0

echo "Comprehensive Streamlit App started on http://localhost:8501"