from supply_v2.apps.factory import create_invoice_app
from supply_v2.shared.server import build_service_app


app = build_service_app(create_invoice_app)
