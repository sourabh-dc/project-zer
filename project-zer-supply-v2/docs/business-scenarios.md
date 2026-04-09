# Business Scenarios

## Scenario 1: Clean Vendor Acceptance

1. Customer places one order.
2. System splits order into vendor POs.
3. Vendor accepts all lines.
4. Vendor ships.
5. Customer receives all goods.
6. Invoice matches PO and receipt.
7. Order completes.

## Scenario 2: Vendor Quantity Change

1. Vendor accepts PO with lower quantity.
2. System creates vendor dispute.
3. Ops accepts vendor terms or reallocates line.
4. Shipment and receipt continue on new agreed quantity.

## Scenario 3: Vendor Price Change

1. Vendor proposes higher unit price.
2. System creates vendor price dispute.
3. Ops accepts or rejects vendor terms.
4. If accepted, PO line price updates.
5. If rejected, line is reallocated or cancelled.

## Scenario 4: Vendor Rejects PO

1. Vendor rejects a line.
2. PO line becomes rejected.
3. Ops reviews supplier failure.
4. Ops reallocates to another vendor or cancels line.

## Scenario 5: Customer Short Receipt

1. Vendor ships.
2. Customer receives fewer items than expected.
3. System creates customer dispute.
4. Ops accepts customer claim or rejects it.
5. Line closes when dispute is resolved.

## Scenario 6: Partial Multi-Vendor Delivery

1. One customer order has multiple vendors.
2. Each vendor accepts and ships on their own timeline.
3. Customer receives partial deliveries.
4. Order status moves through partially shipped and partially received states.
5. Finalize only after all lines are completed or cancelled.
