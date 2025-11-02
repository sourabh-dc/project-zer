from datetime import datetime, timezone

from sqlalchemy import text

from services.cv_gateway.main import _apply_inventory_decrements


class CvOrderSaga:
    """Saga for CV order processing with compensation"""

    def __init__(self, db: Session, order_data: dict):
        self.db = db
        self.order_data = order_data
        self.compensation_steps = []

    async def execute(self) -> dict:
        """Execute the saga steps"""
        try:
            # Step 1: Resolve IDs
            cv_saga_steps_total.labels(step="resolve_ids", provider=self.order_data["provider"], status="started").inc()
            resolved_ids = await self._resolve_ids()
            cv_saga_steps_total.labels(step="resolve_ids", provider=self.order_data["provider"], status="success").inc()

            # Step 2: Validate items
            validation_result = await self._validate_items(resolved_ids)
            if not validation_result["valid"]:
                # Update metrics for unknown items
                cv_unknown_items_total.labels(
                    provider=self.order_data["provider"],
                    tenant_id=resolved_ids["tenant_id"]
                ).inc(len(validation_result.get("unknown_items", [])))
                return validation_result

            # Step 3: Check budgets/approvals
            budget_result = await self._check_budget_approvals(resolved_ids)
            if not budget_result["approved"]:
                return budget_result

            # Step 4: Create order
            order_result = await self._create_order(resolved_ids, validation_result["validated_items"])

            # Step 5: Update inventory
            await self._update_inventory(resolved_ids, validation_result["validated_items"])

            # Step 6: Create ledger entries
            await self._create_ledger_entries(resolved_ids, order_result["total_minor"])

            # Step 7: Update budget
            await self._update_budget(resolved_ids, order_result["total_minor"])

            # Step 8: Record usage metrics
            await self._record_usage_metrics(resolved_ids)

            # Step 9: Create trade invoice
            await self._create_trade_invoice(resolved_ids, order_result)

            # Step 10: Send notifications
            await self._send_notifications(resolved_ids, order_result)

            # Step 11: Publish events
            await self._publish_events(resolved_ids, order_result)

            # Commit transaction
            self.db.commit()

            return {
                "ok": True,
                "order_id": order_result["order_id"],
                "total_minor": order_result["total_minor"],
                "currency": self.order_data["currency"]
            }

        except Exception as e:
            # Execute compensation steps
            await self._compensate()
            raise e

    async def _resolve_ids(self) -> dict:
        """Resolve external IDs to local IDs"""
        provider = self.order_data["provider"]

        tenant_id = (self.order_data.get("tenant_id") or
                     (self.order_data.get("tenant_ext_id") and
                      await _map_provider(self.db, provider, "tenant", self.order_data["tenant_ext_id"])))

        site_id = (self.order_data.get("site_id") or
                   (self.order_data.get("site_ext_id") and
                    await _map_provider(self.db, provider, "site", self.order_data["site_ext_id"])))

        store_id = (self.order_data.get("store_id") or
                    (self.order_data.get("store_ext_id") and
                     await _map_provider(self.db, provider, "store", self.order_data["store_ext_id"])))

        shopper_id = (self.order_data.get("shopper_id") or
                      (self.order_data.get("user_ext_id") and
                       await _map_provider(self.db, provider, "user", self.order_data["user_ext_id"])))

        if not all([tenant_id, site_id, store_id, shopper_id]):
            raise HTTPException(
                status_code=400,
                detail="Mapping failed (tenant/site/store/user). Provide local IDs or external IDs + provider_mappings."
            )

        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "store_id": store_id,
            "shopper_id": shopper_id
        }

    async def _validate_items(self, resolved_ids: dict) -> dict:
        """Validate items and check for unknowns"""
        unknown_items = []
        validated_items = []

        for item in self.order_data["items"]:
            # Check if product exists
            prod = self.db.execute(text("SELECT 1 FROM product_master WHERE sku=:s AND active=TRUE"),
                                   {"s": item.sku}).first()

            # Check if price exists
            price = self.db.execute(text("""
                                         SELECT unit_minor
                                         FROM prices
                                         WHERE sku = :s
                                           AND currency = :c
                                           AND active = TRUE
                                         """), {"s": item.sku, "c": self.order_data["currency"]}).first()

            if not prod or not price:
                unknown_items.append({
                    "sku": item.sku,
                    "name": item.name,
                    "qty": item.qty,
                    "price_minor": item.price_minor
                })

                # Record for review
                await _review_unknown_item(
                    self.db, self.order_data["provider"], resolved_ids["tenant_id"],
                    resolved_ids["site_id"], resolved_ids["store_id"],
                    item.sku, item.name, item.qty, item.price_minor,
                    {"sku": item.sku, "name": item.name, "qty": item.qty, "price_minor": item.price_minor}
                )
                continue

            validated_items.append({
                "sku": item.sku,
                "qty": int(item.qty),
                "unit_minor": int(price[0])
            })

        if unknown_items:
            return {
                "valid": False,
                "status": 202,
                "reason": "reconciliation_required",
                "unknown_count": len(unknown_items),
                "items": unknown_items
            }

        return {
            "valid": True,
            "validated_items": validated_items
        }

    async def _check_budget_approvals(self, resolved_ids: dict) -> dict:
        """Check budget and approval coverage"""
        # Get shopper cost centre
        cc_row = self.db.execute(text("""
                                      SELECT cost_centre_id
                                      FROM user_cost_centres
                                      WHERE user_id = :u
                                      ORDER BY id ASC LIMIT 1
                                      """), {"u": resolved_ids["shopper_id"]}).first()

        cost_centre_id = cc_row[0] if cc_row else None

        if not cost_centre_id:
            return {"approved": True}  # No budget constraints

        # Check budget
        budget = self.db.execute(text("""
                                      SELECT limit_minor, spent_minor
                                      FROM budgets_new
                                      WHERE cost_centre_id = :cc
                                      ORDER BY budget_id DESC LIMIT 1
                                      """), {"cc": cost_centre_id}).first()

        if budget:
            remaining = int(budget[0]) - int(budget[1])
            total_minor = sum(item["qty"] * item["unit_minor"] for item in self.order_data["items"])

            if remaining < total_minor:
                need = total_minor - max(0, remaining)
                if not await _approval_cover_and_consume(self.db, cost_centre_id, resolved_ids["shopper_id"], need):
                    return {
                        "approved": False,
                        "status": 403,
                        "detail": "Budget would overspend (hard block); no approval cover"
                    }

        return {"approved": True, "cost_centre_id": cost_centre_id}

    async def _create_order(self, resolved_ids: dict, validated_items: list) -> dict:
        """Create order and line items"""
        total_minor = sum(item["qty"] * item["unit_minor"] for item in validated_items)

        # Create order
        self.db.execute(text("""
                             INSERT INTO orders_new(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                                                    provider, provider_order_id, total_minor, currency, status,
                                                    occurred_at)
                             VALUES (:t, :si, :st, :u, :cc, :p, :po, :tot, :cur, 'completed', :occ)
                             """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
                                    "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"],
                                    "cc": resolved_ids.get("cost_centre_id"), "p": self.order_data["provider"],
                                    "po": self.order_data["provider_order_id"], "tot": total_minor,
                                    "cur": self.order_data["currency"],
                                    "occ": self.order_data.get("occurred_at", datetime.now(timezone.utc))})

        order_id = self.db.execute(text("SELECT currval(pg_get_serial_sequence('orders_new','order_id'))")).scalar()

        # Create order items
        for item in validated_items:
            self.db.execute(text("""
                                 INSERT INTO order_items_new(order_id, sku, name, qty, price_minor)
                                 VALUES (:oid, :sku, :name, :qty, :price)
                                 """), {"oid": order_id, "sku": item["sku"], "name": item["sku"],
                                        "qty": item["qty"], "price": item["unit_minor"]})

        # Add compensation step
        self.compensation_steps.append(("delete_order", {"order_id": order_id}))

        return {"order_id": order_id, "total_minor": total_minor}

    async def _update_inventory(self, resolved_ids: dict, validated_items: list):
        """Update inventory levels"""
        await _apply_inventory_decrements(resolved_ids["store_id"], validated_items)

        # Add compensation step
        self.compensation_steps.append(("restore_inventory", {
            "store_id": resolved_ids["store_id"],
            "items": validated_items
        }))

    async def _create_ledger_entries(self, resolved_ids: dict, total_minor: int):
        """Create ledger entries"""
        # Debit cost centre spend
        self.db.execute(text("""
                             INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                                            cost_centre_id, site_id, store_id,
                                                            reference_type, reference_id, description)
                             VALUES (:t, 'CostCentreSpend', 'debit', :amt, :cur, :cc, :si, :st, 'cv_order', :ref,
                                     'CV order')
                             """),
                        {"t": resolved_ids["tenant_id"], "amt": total_minor, "cur": self.order_data["currency"],
                         "cc": resolved_ids.get("cost_centre_id"), "si": resolved_ids["site_id"],
                         "st": resolved_ids["store_id"], "ref": str(resolved_ids.get("order_id"))})

        # Credit tenant clearing
        self.db.execute(text("""
                             INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                                            cost_centre_id, site_id, store_id,
                                                            reference_type, reference_id, description)
                             VALUES (:t, 'TenantClearing', 'credit', :amt, :cur, :cc, :si, :st, 'cv_order', :ref,
                                     'CV order')
                             """),
                        {"t": resolved_ids["tenant_id"], "amt": total_minor, "cur": self.order_data["currency"],
                         "cc": resolved_ids.get("cost_centre_id"), "si": resolved_ids["site_id"],
                         "st": resolved_ids["store_id"], "ref": str(resolved_ids.get("order_id"))})

    async def _update_budget(self, resolved_ids: dict, total_minor: int):
        """Update budget spent amount"""
        if resolved_ids.get("cost_centre_id"):
            self.db.execute(text("""
                                 UPDATE budgets_new
                                 SET spent_minor = spent_minor + :amt
                                 WHERE cost_centre_id = :cc
                                 """), {"amt": total_minor, "cc": resolved_ids["cost_centre_id"]})

    async def _record_usage_metrics(self, resolved_ids: dict):
        """Record usage metrics"""
        when = self.order_data.get("occurred_at", datetime.now(timezone.utc))

        # Record order event
        self.db.execute(text("""
                             INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value,
                                                      occurred_at)
                             VALUES (:t, :si, :st, 'orders', :u, 1, :occ)
                             """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
                                    "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "occ": when})

        await _update_daily(self.db, when, resolved_ids["tenant_id"], resolved_ids["site_id"],
                            resolved_ids["store_id"], "orders", 1)

        # Check for unique shoppers
        exist = self.db.execute(text("""
                                     SELECT 1
                                     FROM usage_events
                                     WHERE meter_code = 'unique_shoppers'
                                       AND tenant_id = :t
                                       AND COALESCE(site_id, '') = COALESCE(:si, '')
                                       AND COALESCE(store_id, '') = COALESCE(:st, '')
                                       AND subject_id = :u
                                       AND occurred_at::date = :d
             LIMIT 1
                                     """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
                                            "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"],
                                            "d": when.date()}).first()

        if not exist:
            self.db.execute(text("""
                                 INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value,
                                                          occurred_at)
                                 VALUES (:t, :si, :st, 'unique_shoppers', :u, 1, :occ)
                                 """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
                                        "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "occ": when})

            await _update_daily(self.db, when, resolved_ids["tenant_id"], resolved_ids["site_id"],
                                resolved_ids["store_id"], "unique_shoppers", 1)

    async def _create_trade_invoice(self, resolved_ids: dict, order_result: dict):
        """Create trade invoice if applicable"""
        create_trade_invoice_if_applicable(
            self.db, resolved_ids["tenant_id"], int(order_result["order_id"]),
            order_result["total_minor"], self.order_data["currency"],
            resolved_ids["site_id"], resolved_ids["store_id"]
        )

    async def _send_notifications(self, resolved_ids: dict, order_result: dict):
        """Send order notifications"""
        self.db.execute(text("""
                             INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
                             VALUES (:t, :u, 'dev', 'CV Order Receipt', :body)
                             """), {"t": resolved_ids["tenant_id"], "u": resolved_ids["shopper_id"],
                                    "body": f"CV Order {order_result['order_id']} total {order_result['total_minor']} {self.order_data['currency']}"})

    async def _publish_events(self, resolved_ids: dict, order_result: dict):
        """Publish events for integration"""
        # Publish ORDER_CREATED event
        await publish_event(self.db, "ORDER_CREATED", {
            "order_id": order_result["order_id"],
            "tenant_id": resolved_ids["tenant_id"],
            "provider": self.order_data["provider"],
            "total_minor": order_result["total_minor"],
            "currency": self.order_data["currency"]
        }, resolved_ids["tenant_id"])

    async def _compensate(self):
        """Execute compensation steps in reverse order"""
        for step_name, step_data in reversed(self.compensation_steps):
            try:
                if step_name == "delete_order":
                    self.db.execute(text("DELETE FROM order_items_new WHERE order_id=:oid"),
                                    {"oid": step_data["order_id"]})
                    self.db.execute(text("DELETE FROM orders_new WHERE order_id=:oid"),
                                    {"oid": step_data["order_id"]})

                elif step_name == "restore_inventory":
                    for item in step_data["items"]:
                        self.db.execute(text("""
                                             UPDATE inventory_new
                                             SET qty = qty + :q
                                             WHERE store_id = :st
                                               AND sku = :s
                                             """), {"q": item["qty"], "st": step_data["store_id"], "s": item["sku"]})

            except Exception as e:
                # Log compensation failure but continue
                print(f"Compensation step {step_name} failed: {e}")