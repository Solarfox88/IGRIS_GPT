from fastapi.testclient import TestClient

from igris.web.server import create_app


def test_rank_ui_card_endpoint_available():
    client = TestClient(create_app())
    response = client.get("/api/rank/ui-card")

    assert response.status_code == 200
