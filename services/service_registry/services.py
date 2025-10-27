import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

import httpx

from services.service_registry.schemas import ServiceInfo
from .utils.service_registry_logger import logger

SERVICES = {
    "cv_gateway": {"port": 8000, "health_path": "/health", "version": "4.1.0"},
    "orders": {"port": 8080, "health_path": "/health", "version": "2.0.0"},
    "identity": {"port": 8085, "health_path": "/health", "version": "4.1.0"},
    "ledger": {"port": 8086, "health_path": "/health", "version": "2.0.0"},
    "payments": {"port": 8087, "health_path": "/health", "version": "2.0.0"},
    "events": {"port": 8088, "health_path": "/events/v4/health", "version": "2.0.0"},
    "cv_connector": {"port": 8100, "health_path": "/health", "version": "4.1.0"},
    "entitlements": {"port": 8211, "health_path": "/health", "version": "2.0.0"},
    "subscriptions": {"port": 8212, "health_path": "/health", "version": "2.0.0"},
    "approvals": {"port": 8213, "health_path": "/health", "version": "2.0.0"},
    "notifications": {"port": 8300, "health_path": "/health", "version": "4.1.0"},
}

async def check_service_health(service_name: str, config: Dict[str, Any]) -> ServiceInfo:
    """Check health of a single service"""
    start_time = datetime.now()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://localhost:{config['port']}{config['health_path']}")

            response_time = (datetime.now() - start_time).total_seconds() * 1000

            if response.status_code == 200:
                data = response.json()
                status = "healthy"
                if isinstance(data, dict):
                    status = data.get("status", "healthy")

                return ServiceInfo(
                    name=service_name,
                    port=config["port"],
                    status=status,
                    version=config["version"],
                    last_check=datetime.now(timezone.utc),
                    response_time_ms=response_time
                )
            else:
                return ServiceInfo(
                    name=service_name,
                    port=config["port"],
                    status="unhealthy",
                    version=config["version"],
                    last_check=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                    error=f"HTTP {response.status_code}"
                )

    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceInfo(
            name=service_name,
            port=config["port"],
            status="unreachable",
            version=config["version"],
            last_check=datetime.now(timezone.utc),
            response_time_ms=response_time,
            error=str(e)
        )


async def update_service_registry():
    """Update the service registry with current health status"""
    global service_registry

    logger.info("Updating service registry")

    # Check all services concurrently
    tasks = []
    for service_name, config in SERVICES.items():
        task = check_service_health(service_name, config)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Update registry
    for i, result in enumerate(results):
        service_name = list(SERVICES.keys())[i]
        if isinstance(result, Exception):
            service_registry[service_name] = ServiceInfo(
                name=service_name,
                port=SERVICES[service_name]["port"],
                status="error",
                version=SERVICES[service_name]["version"],
                last_check=datetime.now(timezone.utc),
                error=str(result)
            )
        else:
            service_registry[service_name] = result

    logger.info("Service registry updated",
                total_services=len(service_registry),
                healthy_services=sum(1 for s in service_registry.values() if s.status == "healthy"))

async def periodic_registry_update():
    """Periodically update service registry"""
    while True:
        try:
            await asyncio.sleep(30)  # Update every 30 seconds
            await update_service_registry()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic registry update", error=str(e))