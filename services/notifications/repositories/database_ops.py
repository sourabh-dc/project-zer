import json

from sqlalchemy import text


async def get_deliveries(db, tenant_id, status, channel, limit, offset):
    # Build query
    query = """
            SELECT id, \
                   tenant_id, \
                   user_id, \
                   channel, \
                   provider, \
                   status, \
                   template_id,
                   payload, \
                   error, \
                   retry_count, \
                   created_at, \
                   updated_at
            FROM notification_deliveries_new
            WHERE tenant_id = :tenant_id \
            """
    params = {"tenant_id": tenant_id}

    if status:
        query += " AND status = :status"
        params["status"] = status

    if channel:
        query += " AND channel = :channel"
        params["channel"] = channel

    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params.update({"limit": limit, "offset": offset})

    # Get deliveries
    deliveries = db.execute(text(query), params).fetchall()

    return deliveries

async def get_total_count(db, tenant_id, status, channel):
    count_query = """
                  SELECT COUNT(*) \
                  FROM notification_deliveries_new
                  WHERE tenant_id = :tenant_id \
                  """
    count_params = {"tenant_id": tenant_id}

    if status:
        count_query += " AND status = :status"
        count_params["status"] = status

    if channel:
        count_query += " AND channel = :channel"
        count_params["channel"] = channel

    total_count = db.execute(text(count_query), count_params).scalar()
    return total_count

async def get_provider(db, tenant_id, request):
    provider = db.execute(text("""
                    SELECT id
                    FROM zeroque_rails
                    WHERE tenant_id = :tenant_id
                      AND type = :type
                      AND name = :name
                    """), {
                   "tenant_id": tenant_id,
                   "type": request.type,
                   "name": request.name
               }).first()

    return provider

async def create_provider(db, tenant_id, request):
    db.execute(text("""
                    INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at)
                    VALUES (:tenant_id, :type, :name, :config, :active, NOW())
                    """), {
                   "tenant_id": tenant_id,
                   "type": request.type,
                   "name": request.name,
                   "config": json.dumps(request.config),
                   "active": request.active
               })

    db.commit()

async def update_provider(db, request, existing):
    provider = db.execute(text("""
                    UPDATE zeroque_rails
                    SET config     = :config,
                        active     = :active,
                        updated_at = NOW()
                    WHERE id = :id
                    """), {
                   "id": existing[0],
                   "config": json.dumps(request.config),
                   "active": request.active
               })
    db.commit()
