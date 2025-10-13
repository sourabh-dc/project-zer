#!/usr/bin/env python3
"""
Redis Stream consumer for ZeroQue event bus
"""
import os
import sys
import asyncio
import logging

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zeroque_common.events.bus import start_event_consumer, stop_event_consumer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    """Main event consumer loop"""
    try:
        print("Starting ZeroQue event consumer...")
        await start_event_consumer()
    except KeyboardInterrupt:
        print("Stopping event consumer...")
        stop_event_consumer()
    except Exception as e:
        print(f"Event consumer error: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
