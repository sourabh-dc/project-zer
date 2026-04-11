# Supply V2 Dispute Flow

## Vendor Dispute

1. Customer order creates vendor-specific purchase orders.
2. Vendor receives PO by email or vendor portal API.
3. Vendor acknowledges each PO line or posts to vendor-dispute endpoint using secure vendor access token.
4. If vendor accepts, line becomes `accepted`.
5. If vendor changes quantity, price, or rejects, system creates a `vendor` dispute.
6. Disputed line is marked `disputed`.
7. Ops reviews dispute.
8. Ops can:
   - accept vendor terms
   - reject vendor terms
   - reallocate line to another vendor
   - cancel line
9. If vendor terms accepted, accepted quantity and price update on the PO line.
10. If vendor terms rejected, PO line stays rejected until reallocation or cancellation.

### How vendor raises dispute right now

- Route `POST /purchase-orders/{po_id}/acknowledge`
  - normal authenticated vendor or ops path
- Route `POST /purchase-orders/{po_id}/vendor-disputes`
  - secure email-token path
  - uses `X-Vendor-Access-Token`
  - token binds tenant, vendor, PO, and expiry

### How vendor communication works right now

- PO issue creates `Notification`
- Notification creates `OutboxEvent`
- Outbox worker forwards to broker
- Broker consumer sends email
- Email payload now includes `vendor_token`
- Token can back a secure link in the email template
- Current code issues and verifies token
- Current code does not yet render HTML link body with branded template

## Customer Dispute

1. Vendor ships items.
2. Customer records goods receipt.
3. If received quantity is short or condition is not good, system creates a `customer` dispute.
4. Order line becomes `disputed`.
5. Ops reviews customer dispute.
6. Ops can:
   - accept customer claim
   - commercial settlement
   - reject customer claim
   - close as received
7. Accepted claims close the line as completed.
8. Rejected claims move the line back to received.

## GRN and 3-way match

- GRN here is `GoodsReceipt`
- Route `POST /orders/{order_id}/receipts`
- Receipt stores expected quantity, received quantity, and condition per line
- Receipt line mismatch creates customer dispute
- Invoice service does 3-way match:
  - PO accepted quantity and price
  - GRN received quantity
  - invoice billed quantity and price
- Match outcomes:
  - `matched`
  - `receipt_mismatch`
  - `po_mismatch`
  - `mismatch`

## Event Trail

- `vendor_dispute.created`
- `customer_dispute.created`
- `dispute.resolved`
- `customer_order.line_reallocated`
- `customer_order.line_cancelled`
