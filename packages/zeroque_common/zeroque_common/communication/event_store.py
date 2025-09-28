# packages/zeroque_common/zeroque_common/communication/event_store.py
"""
Event Store Implementation for ZeroQue Services

This module provides event sourcing capabilities for storing and replaying
all system events for audit trails and state reconstruction.
"""

import os
import json
import redis
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import asdict

from .service_bus import ServiceEvent, ServiceEventType

log = logging.getLogger(__name__)

class EventStore:
    """Event store for persisting and retrieving events"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:4000/0")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        
        # Event store streams
        self.main_stream = "zeroque:event_store"
        self.snapshots_stream = "zeroque:event_snapshots"
        self.index_stream = "zeroque:event_index"
        
        log.info("EventStore initialized")
    
    async def append_event(self, event: ServiceEvent) -> str:
        """Append an event to the event store"""
        try:
            # Convert event to dict for storage
            event_data = {
                "event_type": event.event_type.value,
                "service_name": event.service_name,
                "correlation_id": event.correlation_id,
                "data": json.dumps(event.data),
                "metadata": json.dumps(event.metadata),
                "timestamp": event.timestamp.isoformat(),
                "event_id": event.event_id
            }
            
            # Add to main event stream
            message_id = self.redis_client.xadd(self.main_stream, event_data)
            
            # Index by entity (if correlation_id represents an entity)
            if event.correlation_id:
                await self._index_event(event.correlation_id, message_id, event_data)
            
            # Create snapshot if needed
            if await self._should_create_snapshot(event):
                await self._create_snapshot(event.correlation_id, message_id)
            
            log.info(f"Event stored: {event.event_type.value} (ID: {message_id})")
            return message_id
            
        except Exception as e:
            log.error(f"Failed to store event {event.event_type.value}: {str(e)}")
            raise
    
    async def get_events(self, entity_id: str = None, 
                        event_type: ServiceEventType = None,
                        start_time: datetime = None,
                        end_time: datetime = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve events with optional filtering"""
        try:
            if entity_id:
                # Get events for specific entity
                events = await self._get_entity_events(entity_id, limit)
            else:
                # Get events from main stream
                events = await self._get_stream_events(
                    self.main_stream, start_time, end_time, limit
                )
            
            # Filter by event type if specified
            if event_type:
                events = [
                    event for event in events 
                    if event.get("event_type") == event_type.value
                ]
            
            return events
            
        except Exception as e:
            log.error(f"Failed to retrieve events: {str(e)}")
            raise
    
    async def replay_events(self, entity_id: str, 
                          from_snapshot: bool = True) -> List[ServiceEvent]:
        """Replay events for an entity to rebuild state"""
        try:
            events = []
            
            # Start from latest snapshot if requested
            if from_snapshot:
                snapshot = await self._get_latest_snapshot(entity_id)
                if snapshot:
                    start_id = snapshot["last_event_id"]
                    log.info(f"Replaying events for {entity_id} from snapshot {start_id}")
                else:
                    start_id = "0"
                    log.info(f"No snapshot found for {entity_id}, replaying from beginning")
            else:
                start_id = "0"
            
            # Get events from start point
            raw_events = await self._get_entity_events(entity_id, limit=1000, start_id=start_id)
            
            # Convert to ServiceEvent objects
            for event_data in raw_events:
                try:
                    event = ServiceEvent(
                        event_type=ServiceEventType(event_data["event_type"]),
                        service_name=event_data["service_name"],
                        correlation_id=event_data["correlation_id"],
                        data=json.loads(event_data["data"]),
                        metadata=json.loads(event_data["metadata"]),
                        timestamp=datetime.fromisoformat(event_data["timestamp"]),
                        event_id=event_data["event_id"]
                    )
                    events.append(event)
                except Exception as e:
                    log.warning(f"Failed to parse event: {str(e)}")
            
            log.info(f"Replayed {len(events)} events for entity {entity_id}")
            return events
            
        except Exception as e:
            log.error(f"Failed to replay events for {entity_id}: {str(e)}")
            raise
    
    async def create_snapshot(self, entity_id: str, state: Dict[str, Any]) -> str:
        """Create a snapshot of entity state"""
        try:
            # Get the latest event ID for this entity
            latest_events = await self._get_entity_events(entity_id, limit=1)
            if not latest_events:
                raise ValueError(f"No events found for entity {entity_id}")
            
            last_event_id = latest_events[0]["message_id"]
            
            snapshot_data = {
                "entity_id": entity_id,
                "state": json.dumps(state),
                "last_event_id": last_event_id,
                "created_at": datetime.now().isoformat(),
                "snapshot_id": f"snapshot_{entity_id}_{int(datetime.now().timestamp())}"
            }
            
            message_id = self.redis_client.xadd(self.snapshots_stream, snapshot_data)
            
            log.info(f"Snapshot created for entity {entity_id} (ID: {message_id})")
            return message_id
            
        except Exception as e:
            log.error(f"Failed to create snapshot for {entity_id}: {str(e)}")
            raise
    
    async def get_snapshot(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest snapshot for an entity"""
        try:
            snapshots = await self._get_entity_snapshots(entity_id, limit=1)
            if snapshots:
                snapshot = snapshots[0]
                return {
                    "entity_id": snapshot["entity_id"],
                    "state": json.loads(snapshot["state"]),
                    "last_event_id": snapshot["last_event_id"],
                    "created_at": snapshot["created_at"],
                    "snapshot_id": snapshot["snapshot_id"]
                }
            return None
            
        except Exception as e:
            log.error(f"Failed to get snapshot for {entity_id}: {str(e)}")
            return None
    
    async def _index_event(self, entity_id: str, message_id: str, event_data: Dict[str, Any]):
        """Index event by entity ID"""
        index_key = f"zeroque:entity_index:{entity_id}"
        
        # Add to entity index
        self.redis_client.xadd(index_key, {
            "message_id": message_id,
            "event_type": event_data["event_type"],
            "timestamp": event_data["timestamp"]
        })
        
        # Set expiration for index (30 days)
        self.redis_client.expire(index_key, 30 * 24 * 60 * 60)
    
    async def _get_entity_events(self, entity_id: str, limit: int = 100, 
                               start_id: str = None) -> List[Dict[str, Any]]:
        """Get events for a specific entity"""
        index_key = f"zeroque:entity_index:{entity_id}"
        
        if start_id:
            messages = self.redis_client.xrevrange(index_key, "+", start_id, count=limit)
        else:
            messages = self.redis_client.xrevrange(index_key, "+", "-", count=limit)
        
        events = []
        for message_id, fields in messages:
            # Get full event data from main stream
            main_events = self.redis_client.xrange(self.main_stream, message_id, message_id)
            if main_events:
                event_data = main_events[0][1]
                event_data["message_id"] = message_id
                events.append(event_data)
        
        return events
    
    async def _get_stream_events(self, stream_name: str, start_time: datetime = None,
                               end_time: datetime = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get events from a stream with time filtering"""
        if start_time:
            start_id = f"{int(start_time.timestamp() * 1000)}-0"
        else:
            start_id = "0"
        
        if end_time:
            end_id = f"{int(end_time.timestamp() * 1000)}-0"
        else:
            end_id = "+"
        
        messages = self.redis_client.xrange(stream_name, start_id, end_id, count=limit)
        
        events = []
        for message_id, fields in messages:
            event_data = fields.copy()
            event_data["message_id"] = message_id
            events.append(event_data)
        
        return events
    
    async def _get_entity_snapshots(self, entity_id: str, limit: int = 1) -> List[Dict[str, Any]]:
        """Get snapshots for an entity"""
        # Search for snapshots by entity_id
        messages = self.redis_client.xrevrange(self.snapshots_stream, "+", "-", count=1000)
        
        snapshots = []
        for message_id, fields in messages:
            if fields.get("entity_id") == entity_id:
                snapshot_data = fields.copy()
                snapshot_data["message_id"] = message_id
                snapshots.append(snapshot_data)
                
                if len(snapshots) >= limit:
                    break
        
        return snapshots
    
    async def _should_create_snapshot(self, event: ServiceEvent) -> bool:
        """Determine if a snapshot should be created"""
        # Create snapshot every 100 events for an entity
        entity_events = await self._get_entity_events(event.correlation_id, limit=100)
        return len(entity_events) >= 100
    
    async def _create_snapshot(self, entity_id: str, last_event_id: str):
        """Create a snapshot for an entity"""
        try:
            # This would typically involve reconstructing the current state
            # from all events and storing it as a snapshot
            log.info(f"Creating snapshot for entity {entity_id} at event {last_event_id}")
            # Implementation would depend on specific entity types
        except Exception as e:
            log.error(f"Failed to create snapshot for {entity_id}: {str(e)}")
    
    async def _get_latest_snapshot(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest snapshot for an entity"""
        snapshots = await self._get_entity_snapshots(entity_id, limit=1)
        return snapshots[0] if snapshots else None
    
    def get_event_store_metrics(self) -> Dict[str, Any]:
        """Get event store metrics"""
        try:
            main_info = self.redis_client.xinfo_stream(self.main_stream)
            snapshots_info = self.redis_client.xinfo_stream(self.snapshots_stream)
            
            return {
                "main_stream": {
                    "length": main_info.get("length", 0),
                    "first_entry": main_info.get("first-entry"),
                    "last_entry": main_info.get("last-entry")
                },
                "snapshots_stream": {
                    "length": snapshots_info.get("length", 0),
                    "first_entry": snapshots_info.get("first-entry"),
                    "last_entry": snapshots_info.get("last-entry")
                },
                "indexed_entities": len([
                    key for key in self.redis_client.keys("zeroque:entity_index:*")
                ])
            }
        except Exception as e:
            log.error(f"Failed to get event store metrics: {str(e)}")
            return {"error": str(e)}

# Global event store instance
event_store = EventStore()
