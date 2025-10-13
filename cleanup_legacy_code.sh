#!/bin/bash
# Cleanup legacy code and dependencies from all services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🧹 ZeroQue Legacy Code Cleanup${NC}"
echo -e "${BLUE}================================================${NC}"

# Function to cleanup a service
cleanup_service() {
    local service_name=$1
    local service_dir="services/$service_name"
    
    if [ -d "$service_dir" ]; then
        echo -e "${YELLOW}Cleaning up $service_name service...${NC}"
        
        # Remove old/broken files
        find "$service_dir" -name "*_old*" -type f -delete 2>/dev/null || true
        find "$service_dir" -name "*_broken*" -type f -delete 2>/dev/null || true
        find "$service_dir" -name "*_working*" -type f -delete 2>/dev/null || true
        find "$service_dir" -name "*.pyc" -type f -delete 2>/dev/null || true
        find "$service_dir" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
        
        # Remove zeroque_common references from main.py
        if [ -f "$service_dir/main.py" ]; then
            # Backup original file
            cp "$service_dir/main.py" "$service_dir/main.py.backup"
            
            # Remove zeroque_common imports and references
            sed -i '' '/zeroque_common/d' "$service_dir/main.py" 2>/dev/null || true
            sed -i '' '/sys\.path\.append.*zeroque_common/d' "$service_dir/main.py" 2>/dev/null || true
            sed -i '' '/from.*zeroque_common/d' "$service_dir/main.py" 2>/dev/null || true
            sed -i '' '/import.*zeroque_common/d' "$service_dir/main.py" 2>/dev/null || true
            
            echo -e "${GREEN}✅ Cleaned $service_name/main.py${NC}"
        fi
        
        # Ensure requirements.txt exists
        if [ ! -f "$service_dir/requirements.txt" ]; then
            cat > "$service_dir/requirements.txt" << EOF
# $service_name Service Dependencies
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
alembic==1.13.1
redis==5.0.1
celery==5.3.4
pika==1.3.2
httpx==0.25.2
prometheus-client==0.19.0
structlog==23.2.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6
tenacity==8.2.3
pybreaker==1.0.1
EOF
            echo -e "${GREEN}✅ Created $service_name/requirements.txt${NC}"
        fi
        
        # Ensure celeryconfig.py exists
        if [ ! -f "$service_dir/celeryconfig.py" ]; then
            cat > "$service_dir/celeryconfig.py" << EOF
# services/$service_name/celeryconfig.py
import os

# Celery Configuration
broker_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
result_backend = os.getenv("REDIS_URL", "redis://localhost:6379/0")
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Task Routes
task_routes = {
    '${service_name}.process_${service_name}_event': {'queue': '${service_name}_events'},
    '${service_name}.cleanup_old_${service_name}': {'queue': '${service_name}_maintenance'},
    '${service_name}.publish_outbox_events': {'queue': '${service_name}_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': '${service_name}.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-${service_name}': {
        'task': '${service_name}.cleanup_old_${service_name}',
        'schedule': 86400.0,  # Daily
    },
}

# Worker Configuration
worker_prefetch_multiplier = 4
worker_max_tasks_per_child = 1000
task_acks_late = True
task_reject_on_worker_lost = True
task_time_limit = 300
task_soft_time_limit = 240
worker_concurrency = 4

# Task Execution
task_always_eager = False
task_eager_propagates = True
task_ignore_result = False
task_store_eager_result = True

# Result Backend
result_expires = 3600
result_persistent = True
result_compression = 'gzip'

# Security
worker_hijack_root_logger = False
worker_log_color = False
EOF
            echo -e "${GREEN}✅ Created $service_name/celeryconfig.py${NC}"
        fi
        
        # Create run_worker.sh if it doesn't exist
        if [ ! -f "$service_dir/run_worker.sh" ]; then
            cat > "$service_dir/run_worker.sh" << EOF
#!/bin/bash
# Start Celery worker for $service_name Service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "\${GREEN}Starting $service_name Service Celery Worker...\${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "\${YELLOW}Creating virtual environment...\${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "\${YELLOW}Installing dependencies...\${NC}"
pip install -r requirements.txt

# Set environment variables
export CELERY_BROKER_URL=\${RABBITMQ_URL:-"amqp://guest:guest@localhost:5672//"}
export CELERY_RESULT_BACKEND=\${REDIS_URL:-"redis://localhost:6379/0"}
export SERVICE_PORT=\${SERVICE_PORT:-8000}

# Start Celery worker
echo -e "\${GREEN}Starting Celery worker for $service_name service...\${NC}"
celery -A main.celery_app worker \\
    --loglevel=info \\
    --concurrency=4 \\
    --queues=${service_name}_events,${service_name}_maintenance,${service_name}_outbox \\
    --hostname=${service_name}-worker@%h \\
    --without-gossip \\
    --without-mingle \\
    --without-heartbeat
EOF
            chmod +x "$service_dir/run_worker.sh"
            echo -e "${GREEN}✅ Created $service_name/run_worker.sh${NC}"
        fi
        
        # Create run_beat.sh if it doesn't exist
        if [ ! -f "$service_dir/run_beat.sh" ]; then
            cat > "$service_dir/run_beat.sh" << EOF
#!/bin/bash
# Start Celery Beat scheduler for $service_name Service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "\${GREEN}Starting $service_name Service Celery Beat Scheduler...\${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "\${YELLOW}Creating virtual environment...\${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "\${YELLOW}Installing dependencies...\${NC}"
pip install -r requirements.txt

# Set environment variables
export CELERY_BROKER_URL=\${RABBITMQ_URL:-"amqp://guest:guest@localhost:5672//"}
export CELERY_RESULT_BACKEND=\${REDIS_URL:-"redis://localhost:6379/0"}

# Start Celery Beat
echo -e "\${GREEN}Starting Celery Beat scheduler for $service_name service...\${NC}"
celery -A main.celery_app beat \\
    --loglevel=info \\
    --pidfile=${service_name}-beat.pid \\
    --schedule=${service_name}-beat-schedule
EOF
            chmod +x "$service_dir/run_beat.sh"
            echo -e "${GREEN}✅ Created $service_name/run_beat.sh${NC}"
        fi
        
    else
        echo -e "${RED}❌ Service directory $service_dir not found${NC}"
    fi
}

# List of services to cleanup
SERVICES=(
    "approvals"
    "billing"
    "catalog"
    "cv_connector"
    "cv_gateway"
    "entitlements"
    "entry"
    "events"
    "identity"
    "ledger"
    "monitoring"
    "notifications"
    "observability"
    "orders"
    "payments"
    "pricing"
    "provisioning"
    "reports"
    "service_registry"
    "subscriptions"
    "usage"
)

# Cleanup all services
for service in "${SERVICES[@]}"; do
    cleanup_service "$service"
done

# Remove packages/zeroque_common if it exists
if [ -d "packages/zeroque_common" ]; then
    echo -e "${YELLOW}Removing packages/zeroque_common...${NC}"
    rm -rf packages/zeroque_common
    echo -e "${GREEN}✅ Removed packages/zeroque_common${NC}"
fi

# Remove any remaining __pycache__ directories
echo -e "${YELLOW}Cleaning up __pycache__ directories...${NC}"
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -type f -delete 2>/dev/null || true

# Remove backup files
echo -e "${YELLOW}Cleaning up backup files...${NC}"
find . -name "*.backup" -type f -delete 2>/dev/null || true

echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}🎉 Legacy code cleanup completed!${NC}"
echo -e "${BLUE}================================================${NC}"

# Summary
echo -e "${YELLOW}Summary:${NC}"
echo -e "✅ Removed old/broken files"
echo -e "✅ Cleaned zeroque_common references"
echo -e "✅ Created missing requirements.txt files"
echo -e "✅ Created missing celeryconfig.py files"
echo -e "✅ Created missing run_worker.sh scripts"
echo -e "✅ Created missing run_beat.sh scripts"
echo -e "✅ Removed packages/zeroque_common"
echo -e "✅ Cleaned up __pycache__ directories"

echo -e "${GREEN}All services are now clean and optimized!${NC}"
