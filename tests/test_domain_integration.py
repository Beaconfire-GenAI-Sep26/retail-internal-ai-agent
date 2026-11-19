"""Exercise the consolidated API against C-01's real mapped tables."""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from domain.app.main import create_app
from domain.app.models import Store, MenuItem


def test_store_menu_api_uses_existing_domain_models(engine, settings, identities):
    mapped = engine.execution_options(schema_translate_map={"domain": None})
    Store.__table__.create(mapped)
    MenuItem.__table__.create(mapped)
    with Session(mapped) as session:
        session.add(Store(store_id="STORE-A", name="Existing Store", city="Chicago",
                          timezone="America/Chicago", cuisine="chinese", is_active=True,
                          opening_hours={"open": "11:00", "close": "22:00"},
                          onboarded_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        session.add(MenuItem(item_id="ITEM-A-001", store_id="STORE-A", name="Noodles",
                             category="entree", price=Decimal("12.50"),
                             available_modifiers=["Extra sauce"]))
        session.commit()

    app = create_app(engine, settings, service_token="integration-service-token")
    with TestClient(app, root_path="/domain") as client:
        headers = {"Authorization": f"Bearer {identities('viewer', ['STORE-A'])}"}
        store = client.get("/domain/stores/STORE-A", headers=headers)
        assert store.status_code == 200
        assert store.json() == {"store_id": "STORE-A", "name": "Existing Store", "city": "Chicago",
                                "timezone": "America/Chicago", "cuisine": "chinese"}
        menu = client.get("/domain/stores/STORE-A/menu", headers=headers)
        assert menu.status_code == 200
        assert menu.json()[0]["available_modifiers"] == ["Extra sauce"]
        assert menu.json()[0]["price"] == 12.5
        assert client.get("/domain/stores/STORE-B", headers=headers).status_code == 403
