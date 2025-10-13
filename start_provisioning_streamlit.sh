#!/bin/bash
# Start ZeroQue Provisioning Service Streamlit Interface

set -e

echo "🚀 Starting ZeroQue Provisioning Service Streamlit Interface"
echo "============================================================="

# Check if we're in the right directory
if [ ! -f "demo/streamlit_provisioning.py" ]; then
    echo "❌ Error: Please run this script from the project root directory"
    exit 1
fi

# Set environment variables
export PROVISIONING_BASE="${PROVISIONING_BASE:-http://localhost:8000}"

echo "📋 Configuration:"
echo "  Provisioning Service: $PROVISIONING_BASE"
echo "  Streamlit Port: 8502"
echo ""

# Check if provisioning service is running
echo "🔍 Checking provisioning service..."
if curl -s "$PROVISIONING_BASE/health" > /dev/null 2>&1; then
    echo "✅ Provisioning service is running"
else
    echo "⚠️  Provisioning service is not running"
    echo "   Please start it first: ./start_provisioning_service.sh"
    echo "   Or start it manually: cd services/provisioning && python3 main.py"
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check dependencies
echo "🔍 Checking dependencies..."
python3 -c "import streamlit, requests" 2>/dev/null || {
    echo "❌ Missing dependencies. Please install:"
    echo "pip install streamlit requests"
    exit 1
}
echo "✅ Dependencies OK"
echo ""

# Start Streamlit
echo "🎯 Starting Streamlit interface..."
echo "   Access at: http://localhost:8502"
echo "   Press Ctrl+C to stop"
echo ""

cd demo
streamlit run streamlit_provisioning.py --server.port 8502 --server.address 0.0.0.0
