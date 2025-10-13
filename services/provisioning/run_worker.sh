#!/bin/bash
# Start Celery worker for ZeroQue Provisioning Service

set -e

echo "🔧 Starting Celery Worker for Provisioning Service"
echo "=================================================="

# Set environment variables
export DATABASE_URL="${DATABASE_URL:-postgresql://zeroque:zeroque@localhost:5432/zeroque_dev}"
export RABBITMQ_URL="${RABBITMQ_URL:-amqp://guest:guest@localhost:5672//}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

echo "📋 Configuration:"
echo "  Database: $DATABASE_URL"
echo "  RabbitMQ: $RABBITMQ_URL"
echo "  Redis: $REDIS_URL"
echo ""

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from the provisioning service directory"
    exit 1
fi

# Start Celery worker
echo "🎯 Starting Celery worker..."
celery -A main.celery_app worker --loglevel=info --concurrency=4 --queues=provisioning_events,provisioning_maintenance