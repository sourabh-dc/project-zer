from typing import Dict, Any

from sqlalchemy import text

from services.reports.utils.reports_logger import logger

SERVICE_NAME = "reports"

class ReportGenerator:
    def __init__(self, db_session):
        self.db = db_session
        self.logger = logger.bind(service=SERVICE_NAME)

    async def generate_sales_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive sales analytics"""
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        tenant_id = params.get("tenant_id")
        group_by = params.get("group_by", ["day"])

        # Sales by period
        sales_query = text("""
                           SELECT
                               DATE (o.created_at) as period, COUNT (*) as order_count, SUM (o.total_minor) as revenue_minor, AVG (o.total_minor) as avg_order_value, COUNT (DISTINCT o.customer_id) as unique_customers
                           FROM orders_new o
                           WHERE o.tenant_id = :tenant_id
                             AND o.created_at BETWEEN :start_date
                             AND :end_date
                             AND o.status = 'completed'
                           GROUP BY DATE (o.created_at)
                           ORDER BY period
                           """)

        sales_data = self.db.execute(sales_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()

        # Top products
        products_query = text("""
                              SELECT oi.offer_id,
                                     SUM(oi.quantity)            as units_sold,
                                     SUM(oi.total_price_minor)   as revenue_minor,
                                     COUNT(DISTINCT oi.order_id) as order_count
                              FROM order_items_new oi
                                       JOIN orders_new o ON o.id = oi.order_id
                              WHERE o.tenant_id = :tenant_id
                                AND o.created_at BETWEEN :start_date AND :end_date
                                AND o.status = 'completed'
                              GROUP BY oi.offer_id
                              ORDER BY revenue_minor DESC LIMIT 20
                              """)

        products_data = self.db.execute(products_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()

        # Store performance
        stores_query = text("""
                            SELECT o.store_id,
                                   COUNT(*)           as order_count,
                                   SUM(o.total_minor) as revenue_minor,
                                   AVG(o.total_minor) as avg_order_value
                            FROM orders_new o
                            WHERE o.tenant_id = :tenant_id
                              AND o.created_at BETWEEN :start_date AND :end_date
                              AND o.status = 'completed'
                            GROUP BY o.store_id
                            ORDER BY revenue_minor DESC
                            """)

        stores_data = self.db.execute(stores_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()

        return {
            "sales_trends": [
                {"period": str(r[0]), "orders": r[1], "revenue": r[2], "avg_value": r[3], "customers": r[4]} for r in
                sales_data],
            "top_products": [{"offer_id": r[0], "units_sold": r[1], "revenue": r[2], "orders": r[3]} for r in
                             products_data],
            "store_performance": [{"store_id": r[0], "orders": r[1], "revenue": r[2], "avg_value": r[3]} for r in
                                  stores_data],
            "summary": {
                "total_orders": sum(r[1] for r in sales_data),
                "total_revenue": sum(r[2] for r in sales_data),
                "avg_order_value": sum(r[2] for r in sales_data) / sum(r[1] for r in sales_data) if sales_data else 0,
                "unique_customers": len(set(r[4] for r in sales_data))
            }
        }

    async def generate_inventory_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate inventory analytics and insights"""
        tenant_id = params.get("tenant_id")
        store_id = params.get("store_id")

        # Current inventory levels
        inventory_query = text("""
                               SELECT i.sku,
                                      i.quantity_on_hand,
                                      i.quantity_reserved,
                                      i.quantity_available,
                                      i.last_updated
                               FROM inventory_new i
                               WHERE i.tenant_id = :tenant_id
                               """)

        params_dict = {"tenant_id": tenant_id}
        if store_id:
            inventory_query = text("""
                                   SELECT i.sku,
                                          i.quantity_on_hand,
                                          i.quantity_reserved,
                                          i.quantity_available,
                                          i.last_updated
                                   FROM inventory_new i
                                   WHERE i.tenant_id = :tenant_id
                                     AND i.store_id = :store_id
                                   """)
            params_dict["store_id"] = store_id

        inventory_data = self.db.execute(inventory_query, params_dict).all()

        # Low stock items
        low_stock_query = text("""
                               SELECT i.sku,
                                      i.quantity_on_hand,
                                      i.quantity_available,
                                      i.store_id
                               FROM inventory_new i
                               WHERE i.tenant_id = :tenant_id
                                 AND i.quantity_available <= 10
                               ORDER BY i.quantity_available ASC
                               """)

        low_stock_data = self.db.execute(low_stock_query, {"tenant_id": tenant_id}).all()

        # Inventory movements
        movements_query = text("""
                               SELECT im.sku,
                                      im.movement_type,
                                      SUM(im.quantity_delta) as total_delta,
                                      COUNT(*)               as movement_count
                               FROM inventory_movements_new im
                               WHERE im.tenant_id = :tenant_id
                                 AND im.created_at >= NOW() - INTERVAL '30 days'
                               GROUP BY im.sku, im.movement_type
                               ORDER BY total_delta DESC
                               """)

        movements_data = self.db.execute(movements_query, {"tenant_id": tenant_id}).all()

        return {
            "current_inventory": [{"sku": r[0], "on_hand": r[1], "reserved": r[2], "available": r[3], "updated": r[4]}
                                  for r in inventory_data],
            "low_stock_alerts": [{"sku": r[0], "quantity": r[1], "available": r[2], "store_id": r[3]} for r in
                                 low_stock_data],
            "inventory_movements": [{"sku": r[0], "type": r[1], "delta": r[2], "count": r[3]} for r in movements_data],
            "summary": {
                "total_skus": len(inventory_data),
                "low_stock_items": len(low_stock_data),
                "total_value": sum(r[1] for r in inventory_data),  # Simplified calculation
                "movement_types": len(set(r[1] for r in movements_data))
            }
        }

    async def generate_customer_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate customer analytics and insights"""
        tenant_id = params.get("tenant_id")
        start_date = params.get("start_date")
        end_date = params.get("end_date")

        # Customer acquisition
        acquisition_query = text("""
                                 SELECT
                                     DATE (u.created_at) as acquisition_date, COUNT (*) as new_customers
                                 FROM users_new u
                                 WHERE u.tenant_id = :tenant_id
                                   AND u.created_at BETWEEN :start_date
                                   AND :end_date
                                 GROUP BY DATE (u.created_at)
                                 ORDER BY acquisition_date
                                 """)

        acquisition_data = self.db.execute(acquisition_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()

        # Customer lifetime value
        clv_query = text("""
                         SELECT o.customer_id,
                                COUNT(*)           as order_count,
                                SUM(o.total_minor) as total_spent,
                                AVG(o.total_minor) as avg_order_value,
                                MIN(o.created_at)  as first_order,
                                MAX(o.created_at)  as last_order
                         FROM orders_new o
                         WHERE o.tenant_id = :tenant_id
                           AND o.status = 'completed'
                         GROUP BY o.customer_id
                         ORDER BY total_spent DESC LIMIT 100
                         """)

        clv_data = self.db.execute(clv_query, {"tenant_id": tenant_id}).all()

        # Customer segments
        segments_query = text("""
                              WITH customer_metrics AS (SELECT customer_id,
                                                               COUNT(*)         as order_count,
                                                               SUM(total_minor) as total_spent,
                                                               AVG(total_minor) as avg_order_value
                                                        FROM orders_new
                                                        WHERE tenant_id = :tenant_id
                                                          AND status = 'completed'
                                                        GROUP BY customer_id)
                              SELECT CASE
                                         WHEN total_spent > 100000 THEN 'high_value'
                                         WHEN total_spent > 50000 THEN 'medium_value'
                                         ELSE 'low_value'
                                         END          as segment,
                                     COUNT(*)         as customer_count,
                                     AVG(total_spent) as avg_spent,
                                     AVG(order_count) as avg_orders
                              FROM customer_metrics
                              GROUP BY segment
                              """)

        segments_data = self.db.execute(segments_query, {"tenant_id": tenant_id}).all()

        return {
            "customer_acquisition": [{"date": str(r[0]), "new_customers": r[1]} for r in acquisition_data],
            "top_customers": [
                {"customer_id": r[0], "orders": r[1], "total_spent": r[2], "avg_value": r[3], "first_order": r[4],
                 "last_order": r[5]} for r in clv_data[:20]],
            "customer_segments": [{"segment": r[0], "count": r[1], "avg_spent": r[2], "avg_orders": r[3]} for r in
                                  segments_data],
            "summary": {
                "total_customers": len(clv_data),
                "new_customers": sum(r[1] for r in acquisition_data),
                "avg_customer_value": sum(r[2] for r in clv_data) / len(clv_data) if clv_data else 0,
                "top_spender": clv_data[0][2] if clv_data else 0
            }
        }

    async def generate_operational_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate operational analytics and KPIs"""
        tenant_id = params.get("tenant_id")
        start_date = params.get("start_date")
        end_date = params.get("end_date")

        # Order processing times
        processing_query = text("""
                                SELECT
                                    DATE (created_at) as date, AVG (EXTRACT (EPOCH FROM (updated_at - created_at))/60) as avg_processing_minutes, COUNT (*) as order_count
                                FROM orders_new
                                WHERE tenant_id = :tenant_id
                                  AND created_at BETWEEN :start_date
                                  AND :end_date
                                  AND status = 'completed'
                                GROUP BY DATE (created_at)
                                ORDER BY date
                                """)

        processing_data = self.db.execute(processing_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()

        # System performance metrics
        performance_query = text("""
                                 SELECT 'orders_per_hour' as metric,
                                        COUNT(*) /
                                        GREATEST(EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at))) / 3600,
                                                 1) as value
                                 FROM orders_new
                                 WHERE tenant_id = :tenant_id
                                   AND created_at BETWEEN :start_date
                                   AND :end_date
                                 UNION ALL
                                 SELECT 'completion_rate' as metric,
                                        COUNT(*)             FILTER (WHERE status = 'completed') * 100.0 / COUNT(*) as value
                                 FROM orders_new
                                 WHERE tenant_id = :tenant_id
                                   AND created_at BETWEEN :start_date
                                   AND :end_date
                                 """)

        performance_data = self.db.execute(performance_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()

        return {
            "processing_times": [{"date": str(r[0]), "avg_minutes": float(r[1]), "orders": r[2]} for r in
                                 processing_data],
            "performance_metrics": {r[0]: float(r[1]) for r in performance_data},
            "summary": {
                "avg_processing_time": sum(r[1] for r in processing_data) / len(
                    processing_data) if processing_data else 0,
                "total_orders_processed": sum(r[2] for r in processing_data),
                "orders_per_hour": next((r[1] for r in performance_data if r[0] == 'orders_per_hour'), 0),
                "completion_rate": next((r[1] for r in performance_data if r[0] == 'completion_rate'), 0)
            }
        }