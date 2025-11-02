# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_cv_order(self, tenant_id: str, order_data: Dict[str, Any]):
    """Process CV order asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process order logic here
            logger.info(f"Processing CV order for tenant {tenant_id}")

            # Update metrics
            cv_gateway_requests_total.labels(method="POST", endpoint="order", provider="async", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process CV order for tenant {tenant_id}: {e}")
        cv_gateway_requests_total.labels(method="POST", endpoint="order", provider="async", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_cv_session(self, tenant_id: str, session_data: Dict[str, Any]):
    """Process CV session asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process session logic here
            logger.info(f"Processing CV session for tenant {tenant_id}")

            # Update metrics
            cv_gateway_requests_total.labels(method="POST", endpoint="session", provider="async",
                                             status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process CV session for tenant {tenant_id}: {e}")
        cv_gateway_requests_total.labels(method="POST", endpoint="session", provider="async", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_site_created(self, site_id: str, site_data: Dict[str, Any]):
    """
    Phase 2: Process SITE_CREATED events from Provisioning
    Syncs devices from device_metadata to Device registry
    """
    try:
        tenant_id = site_data.get("tenant_id")
        device_metadata = site_data.get("device_metadata", {})

        logger.info(f"Processing SITE_CREATED for CV Gateway site: {site_id}, tenant: {tenant_id}")

        with SessionLocal() as db:
            if tenant_id:
                set_rls_context(db, tenant_id)

            # Sync cameras
            cameras = device_metadata.get("cameras", [])
            for camera in cameras:
                try:
                    db.execute(text("""
                                    INSERT INTO devices (device_id, tenant_id, site_id, device_type, device_name, zone,
                                                         status, device_metadata)
                                    VALUES (:device_id, :tenant_id, :site_id, 'camera', :device_name, :zone, 'online',
                                            :metadata) ON CONFLICT (device_id) DO
                                    UPDATE SET
                                        device_name = EXCLUDED.device_name,
                                        zone = EXCLUDED.zone,
                                        device_metadata = EXCLUDED.device_metadata
                                    """), {
                                   "device_id": camera.get("id"),
                                   "tenant_id": tenant_id,
                                   "site_id": site_id,
                                   "device_name": camera.get("id"),
                                   "zone": camera.get("zone"),
                                   "metadata": json.dumps(camera)
                               })
                except Exception as e:
                    logger.warning(f"Failed to sync camera {camera.get('id')}: {e}")

            # Sync sensors
            sensors = device_metadata.get("sensors", [])
            for sensor in sensors:
                try:
                    db.execute(text("""
                                    INSERT INTO devices (device_id, tenant_id, site_id, device_type, device_name, zone,
                                                         status, device_metadata)
                                    VALUES (:device_id, :tenant_id, :site_id, 'sensor', :device_name, :zone, 'online',
                                            :metadata) ON CONFLICT (device_id) DO
                                    UPDATE SET
                                        device_name = EXCLUDED.device_name,
                                        zone = EXCLUDED.zone,
                                        device_metadata = EXCLUDED.device_metadata
                                    """), {
                                   "device_id": sensor.get("id"),
                                   "tenant_id": tenant_id,
                                   "site_id": site_id,
                                   "device_name": sensor.get("id"),
                                   "zone": sensor.get("zone"),
                                   "metadata": json.dumps(sensor)
                               })
                except Exception as e:
                    logger.warning(f"Failed to sync sensor {sensor.get('id')}: {e}")

            # Sync entry devices
            entry_devices = device_metadata.get("entry_devices", [])
            for entry_device in entry_devices:
                try:
                    db.execute(text("""
                                    INSERT INTO devices (device_id, tenant_id, site_id, device_type, device_name, zone,
                                                         status, device_metadata)
                                    VALUES (:device_id, :tenant_id, :site_id, 'entry_device', :device_name, :zone,
                                            'online', :metadata) ON CONFLICT (device_id) DO
                                    UPDATE SET
                                        device_name = EXCLUDED.device_name,
                                        device_metadata = EXCLUDED.device_metadata
                                    """), {
                                   "device_id": entry_device.get("id"),
                                   "tenant_id": tenant_id,
                                   "site_id": site_id,
                                   "device_name": entry_device.get("id"),
                                   "zone": None,
                                   "metadata": json.dumps(entry_device)
                               })
                except Exception as e:
                    logger.warning(f"Failed to sync entry device {entry_device.get('id')}: {e}")

            db.commit()

            total_devices = len(cameras) + len(sensors) + len(entry_devices)
            logger.info(f"Synced {total_devices} devices for site {site_id}")

    except Exception as e:
        logger.error(f"Failed to process SITE_CREATED for CV Gateway {site_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_cv_gateway_data(self):
    """Clean up old CV gateway data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)

            # Clean up old CV orders
            order_result = db.execute(text("""
                                           DELETE
                                           FROM cv_orders_new
                                           WHERE created_at < :cutoff_date
                                             AND status IN ('completed', 'cancelled')
                                           """), {"cutoff_date": cutoff_date})

            # Clean up old CV sessions
            session_result = db.execute(text("""
                                             DELETE
                                             FROM cv_sessions_new
                                             WHERE created_at < :cutoff_date
                                               AND status IN ('completed', 'expired')
                                             """), {"cutoff_date": cutoff_date})

            # Phase 2: Clean up old device status logs
            device_log_result = db.execute(text("""
                                                DELETE
                                                FROM device_status_logs
                                                WHERE created_at < :cutoff_date
                                                """), {"cutoff_date": cutoff_date})

            # Phase 2: Clean up resolved device alerts
            alert_result = db.execute(text("""
                                           DELETE
                                           FROM device_alerts
                                           WHERE status = 'resolved'
                                             AND resolved_at < :cutoff_date
                                           """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {order_result.rowcount} old CV orders, {session_result.rowcount} old CV sessions, {device_log_result.rowcount} device logs, {alert_result.rowcount} resolved alerts")

    except Exception as e:
        logger.error(f"Failed to cleanup old CV gateway data: {e}")
        raise self.retry(exc=e, countdown=300)


# =============================================================================
# EVENT CONSUMPTION WORKERS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_tenant_created(self, tenant_id: str, tenant_data: Dict[str, Any]):
    """Process TENANT_CREATED events for CV Gateway"""
    try:
        logger.info(f"Processing TENANT_CREATED for CV Gateway tenant: {tenant_id}")

        # Create default CV provider mappings for new tenant
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Create default provider mappings
            providers = ["provider_a", "provider_b", "provider_c"]
            for provider in providers:
                # Check if mapping already exists
                existing = db.execute(text("""
                                           SELECT 1
                                           FROM provider_mappings
                                           WHERE provider = :provider
                                             AND tenant_id = :tenant_id
                                           """), {"provider": provider, "tenant_id": tenant_id}).fetchone()

                if not existing:
                    # Create new provider mapping
                    db.execute(text("""
                                    INSERT INTO provider_mappings (provider, entity_type, external_id, local_id, tenant_id)
                                    VALUES (:provider, 'provider', :provider, :local_id, :tenant_id)
                                    """), {
                                   "provider": provider,
                                   "local_id": f"{provider}_{tenant_id}",
                                   "tenant_id": tenant_id
                               })

            db.commit()
            logger.info(f"Created default provider mappings for CV Gateway tenant: {tenant_id}")

    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED for CV Gateway {tenant_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_order_completed(self, order_id: str, order_data: Dict[str, Any]):
    """Process ORDER_COMPLETED events for CV Gateway"""
    try:
        logger.info(f"Processing ORDER_COMPLETED for CV Gateway order: {order_id}")

        # Check if order needs CV processing
        with SessionLocal() as db:
            tenant_id = order_data.get("tenant_id")

            if tenant_id:
                set_rls_context(db, tenant_id)

            # Check if order has unknown items that need CV processing
            unknown_items = order_data.get("unknown_items", [])
            if unknown_items:
                # Process unknown items through CV providers
                for item in unknown_items:
                    # Create CV unknown item review for unknown item
                    cv_review = CvUnknownItemReview(
                        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                        provider="auto",
                        external_sku=item.get("sku", "unknown"),
                        name=item.get("name", "Unknown Item"),
                        qty=item.get("qty", 1),
                        price_minor=item.get("price_minor", 0),
                        payload_json={"original_order_id": order_id, "unknown_item": item},
                        status="pending"
                    )
                    db.add(cv_review)

                db.commit()
                logger.info(f"Created CV orders for unknown items in order: {order_id}")

    except Exception as e:
        logger.error(f"Failed to process ORDER_COMPLETED for CV Gateway {order_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            result = db.execute(text("""
                                     DELETE
                                     FROM outbox_events
                                     WHERE status = 'published'
                                       AND processed_at < :cutoff_date
                                     """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} old CV Gateway outbox events")

    except Exception as e:
        logger.error(f"Failed to cleanup old CV Gateway outbox events: {e}")
        raise self.retry(exc=e, countdown=300)