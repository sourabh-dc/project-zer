#!/bin/bash

# ZeroQue Migration Reset Script
# This script completely resets migrations and recreates the database schema

set -e

echo "🔄 Resetting Migrations..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Confirm before proceeding
echo "⚠️  This will completely reset your database migrations!"
echo "   All data will be lost!"
read -p "Are you sure you want to continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_warning "Migration reset cancelled."
    exit 1
fi

print_status "Dropping all tables..."
psql -U zeroque -d zeroque_dev -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO zeroque;
GRANT ALL ON SCHEMA public TO public;
"

print_status "Resetting Alembic version table..."
alembic stamp base

print_status "Running all migrations from scratch..."
alembic upgrade head

print_status "Verifying migration status..."
alembic current
alembic heads

print_success "Migration reset completed successfully!"
print_status "All tables have been recreated with the latest schema."
