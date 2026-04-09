from supply_v2.apps.factory import create_procurement_app
from supply_v2.shared.server import build_service_app

app = build_service_app(create_procurement_app)
