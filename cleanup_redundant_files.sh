#!/bin/bash

# ZeroQue Redundant Files Cleanup Script
# This script removes redundant, duplicate, and stale files

set -e

echo "🧹 Starting ZeroQue redundant files cleanup..."

# Function to safely remove files
safe_remove() {
    local file="$1"
    if [ -f "$file" ]; then
        echo "  ❌ Removing: $file"
        rm "$file"
    else
        echo "  ⚠️  Not found: $file"
    fi
}

# Function to safely remove directories
safe_remove_dir() {
    local dir="$1"
    if [ -d "$dir" ]; then
        echo "  ❌ Removing directory: $dir"
        rm -rf "$dir"
    else
        echo "  ⚠️  Directory not found: $dir"
    fi
}

echo ""
echo "📁 Cleaning up redundant startup scripts..."

# Keep only the most comprehensive startup script
safe_remove "start_all_services.sh"
safe_remove "start_all_services_final.sh"
safe_remove "start_all_services_v2.sh"
safe_remove "start_services_verified.sh"
safe_remove "start_provisioning_service.sh"

echo ""
echo "📁 Cleaning up redundant test scripts..."

# Keep only the most comprehensive test scripts
safe_remove "test_all_services.sh"
safe_remove "test_services.sh"
safe_remove "test_provisioning_curl.sh"
safe_remove "test_provisioning_imports.py"
safe_remove "test_provisioning_service.py"
safe_remove "quick_test.sh"
safe_remove "quick_curl_tests.sh"
safe_remove "check_all_services.sh"
safe_remove "restart_and_test_services.sh"

echo ""
echo "📁 Cleaning up redundant documentation files..."

# Remove duplicate or outdated documentation
safe_remove "COMPLETE_PROJECT_SUMMARY.md"
safe_remove "PRODUCTION_READY_STATUS.md"
safe_remove "SETUP_NEW_SYSTEM.md"
safe_remove "QUICK_START.md"
safe_remove "STREAMLIT_APP_GUIDE.md"
safe_remove "STREAMLIT_E2E_TESTING_GUIDE.md"

echo ""
echo "📁 Cleaning up redundant demo files..."

# Keep only the most useful demo files
safe_remove "demo/streamlit_app.py"
safe_remove "demo/streamlit_e2e.py"
safe_remove "demo/streamlit_e2e_v2.py"
safe_remove "demo/streamlit_complete_e2e_test.py"
safe_remove "demo/view.py"
safe_remove "demo/README_STREAMLIT_V2.md"

echo ""
echo "📁 Cleaning up redundant configuration files..."

# Remove old configuration files
safe_remove "streamlit_production_app.py"

echo ""
echo "📁 Cleaning up redundant database files..."

# Remove old database files
safe_remove "services/provisioning/dump.rdb"

echo ""
echo "📁 Cleaning up redundant package files..."

# Remove empty packages directory if it exists
if [ -d "packages" ] && [ -z "$(ls -A packages)" ]; then
    safe_remove_dir "packages"
fi

echo ""
echo "📁 Cleaning up cache and temporary files..."

# Remove cache directories
safe_remove_dir ".pytest_cache"
safe_remove_dir "__pycache__"

# Remove Python cache files
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "📁 Cleaning up redundant Alembic migration files..."

# Keep only the latest comprehensive migration
cd alembic/versions
for file in 0*.py; do
    if [ "$file" != "0044_comprehensive_v4_1_tables.py" ]; then
        echo "  ❌ Removing old migration: $file"
        rm "$file"
    fi
done
cd ../..

echo ""
echo "📁 Cleaning up redundant service files..."

# Remove old service files that might exist
find services -name "*.pyc" -delete 2>/dev/null || true
find services -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "✅ Cleanup completed successfully!"
echo ""
echo "📋 Summary of remaining files:"
echo "  🚀 Startup: start_all_services_with_celery.sh"
echo "  🧪 Testing: test_all_services_comprehensive.sh, test_all_services_e2e.sh"
echo "  🛑 Shutdown: stop_all_services.sh"
echo "  📊 Health: health_check_all_services.sh"
echo "  📱 Demo: streamlit_provisioning.py"
echo "  📚 Documentation: All service documentation in docs/"
echo "  🗄️  Database: Fresh Alembic migration"
echo ""
echo "🎯 The project is now clean and production-ready!"

