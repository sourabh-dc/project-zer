#!/bin/bash

# ZeroQue Migration Heads Fix Script
# This script fixes "multiple head revisions" errors

set -e

echo "🔧 Fixing Migration Heads Issue..."

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

# Check current migration status
print_status "Checking current migration status..."
alembic current

print_status "Checking migration heads..."
heads=$(alembic heads)
echo "$heads"

# Count the number of heads
head_count=$(echo "$heads" | grep -c "Rev:")

if [ "$head_count" -eq 1 ]; then
    print_success "Only one migration head found. No merge needed."
    print_status "Running upgrade..."
    alembic upgrade head
    print_success "Migrations completed successfully!"
    exit 0
fi

print_warning "Multiple migration heads detected ($head_count heads)"

# Get the head revisions
head_revisions=$(echo "$heads" | grep "Rev:" | awk '{print $2}' | tr '\n' ' ')
print_status "Head revisions: $head_revisions"

# Create a merge migration
print_status "Creating merge migration..."
alembic merge $head_revisions -m "merge_migration_heads"

# Run the upgrade
print_status "Running upgrade after merge..."
alembic upgrade head

print_success "Migration heads merged and upgrade completed!"

# Verify final state
print_status "Final migration status:"
alembic current
alembic heads
