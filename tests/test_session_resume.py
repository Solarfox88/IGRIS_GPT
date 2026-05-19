from fastapi.testclient import TestClient

from igris.web.server import create_app


def test_api_diagnostics_session_resume():
    client = TestClient(create_app())
    response = client.get("/api/diagnostics/session-resume")
    assert response.status_code == 200
