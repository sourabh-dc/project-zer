#!/bin/bash
# Start ZeroQue Provisioning Service

set -e

echo "🚀 Starting ZeroQue Provisioning Service"
echo "========================================"

# Check if we're in the right directory
if [ ! -f "services/provisioning/main.py" ]; then
    echo "❌ Error: Please run this script from the project root directory"
    exit 1
fi

# Set environment variables
export DATABASE_URL="${DATABASE_URL:-postgresql://zeroque:zeroque@localhost:5432/zeroque_dev}"
export RABBITMQ_URL="${RABBITMQ_URL:-amqp://guest:guest@localhost:5672//}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export SUBSCRIPTIONS_SERVICE_URL="${SUBSCRIPTIONS_SERVICE_URL:-http://localhost:8010}"
export SERVICE_PORT="${SERVICE_PORT:-8000}"
export ALLOW_DEMO="${ALLOW_DEMO:-true}"

echo "📋 Configuration:"
echo "  Database: $DATABASE_URL"
echo "  RabbitMQ: $RABBITMQ_URL"
echo "  Redis: $REDIS_URL"
echo "  Subscriptions Service: $SUBSCRIPTIONS_SERVICE_URL"
echo "  Service Port: $SERVICE_PORT"
echo "  Demo Mode: $ALLOW_DEMO"
echo ""

# Check dependencies
echo "🔍 Checking Python dependencies..."
python3 -c "import fastapi, sqlalchemy, pika, celery, redis, jwt, httpx, tenacity, pybreaker" 2>/dev/null || {
    echo "❌ Missing dependencies. Please install:"
    echo "pip install -r services/provisioning/requirements.txt"
    exit 1
}
echo "✅ Dependencies OK"
echo ""

# Check database connectivity and setup RLS
echo "🔍 Checking database connectivity and RLS setup..."
python3 -c "
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
try:
    engine = sa.create_engine('$DATABASE_URL', pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    db.execute(sa.text('SELECT 1'))
    
    # Setup RLS if not exists
    try:
        # Create the RLS function if it doesn't exist
        db.execute(sa.text('''
            CREATE OR REPLACE FUNCTION app.get_tenant_id()
            RETURNS UUID AS \$\$
            BEGIN
                RETURN current_setting('app.current_tenant', true)::UUID;
            EXCEPTION
                WHEN OTHERS THEN
                    RETURN NULL;
            END;
            \$\$ LANGUAGE plpgsql;
        '''))
        
        # Create RLS policies for provisioning tables
        tables = ['tenants_new', 'sites_new', 'stores_new', 'users_new', 'roles_new', 'vendors_new', 'cost_centres']
        for table in tables:
            # Enable RLS on the table
            db.execute(sa.text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
            
            # Create policy for tenant isolation
            policy_sql = f'''
                DROP POLICY IF EXISTS \"{table}_tenant_policy\" ON {table};
                CREATE POLICY \"{table}_tenant_policy\" ON {table}
                FOR ALL USING (
                    CASE 
                        WHEN current_setting('app.current_tenant', true) IS NOT NULL 
                        THEN tenant_id::UUID = current_setting('app.current_tenant', true)::UUID
                        ELSE true
                    END
                );
            '''
            db.execute(sa.text(policy_sql))
        
        db.commit()
        print('✅ Database connected and RLS setup completed')
    except Exception as rls_error:
        print(f'⚠️  RLS setup issue (continuing): {rls_error}')
    
    db.close()
except Exception as e:
    print(f'❌ Database connection failed: {e}')
    exit(1)
"
echo ""

# Check RabbitMQ connectivity
echo "🔍 Checking RabbitMQ connectivity..."
python3 -c "
import pika
try:
    conn = pika.BlockingConnection(pika.URLParameters('$RABBITMQ_URL'))
    conn.close()
    print('✅ RabbitMQ connected successfully')
except Exception as e:
    print(f'❌ RabbitMQ connection failed: {e}')
    exit(1)
"
echo ""

# Check Redis connectivity
echo "🔍 Checking Redis connectivity..."
python3 -c "
import redis
try:
    client = redis.Redis.from_url('$REDIS_URL', decode_responses=True)
    client.ping()
    print('✅ Redis connected successfully')
except Exception as e:
    print(f'❌ Redis connection failed: {e}')
    exit(1)
"
echo ""

# Create demo user if needed
echo "🔍 Checking demo user setup..."
python3 -c "
import sys
import os
sys.path.insert(0, '.')
try:
    from create_demo_user import create_demo_user
    create_demo_user()
    print('✅ Demo user setup completed')
except ImportError as e:
    print(f'⚠️  Demo user script not found: {e}')
except Exception as e:
    print(f'⚠️  Demo user setup issue: {e}')
"
echo ""

# Start the service
echo "🎯 Starting Provisioning Service..."
echo "   Service will be available at: http://localhost:$SERVICE_PORT"
echo "   Health check: http://localhost:$SERVICE_PORT/health"
echo "   Metrics: http://localhost:$SERVICE_PORT/metrics"
echo "   Press Ctrl+C to stop"
echo ""

cd services/provisioning
python3 main.py
