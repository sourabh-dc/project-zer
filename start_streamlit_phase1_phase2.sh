#!/bin/bash
# Start Streamlit Dashboard for Phase 1 & 2 Features

echo "Starting ZeroQue Phase 1 & 2 Features Dashboard..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Install streamlit if not installed
if ! command -v streamlit &> /dev/null; then
    echo "Installing streamlit..."
    pip install streamlit
fi

# Start Streamlit
streamlit run demo/streamlit_phase1_phase2_features.py \
    --server.port 8503 \
    --server.address 0.0.0.0 \
    --server.headless true

echo "Dashboard available at: http://localhost:8503"

