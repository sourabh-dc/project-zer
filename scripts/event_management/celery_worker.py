#!/usr/bin/env python3
"""
Celery worker for ZeroQue event processing
"""
import os
import sys
import logging
from celery import Celery

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zeroque_common.events.celery_app import celery_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == '__main__':
    # Start Celery worker
    celery_app.worker_main([
        'worker',
        '--loglevel=info',
        '--concurrency=4',
        '--queues=default,orders,inventory,budget,notifications,webhooks,pricing,analytics',
        '--hostname=zeroque-worker@%h'
    ])
