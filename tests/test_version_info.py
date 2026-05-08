import pytest
from fastapi.testclient import TestClient
from igris.web.server import create_app

app = create_app()
client = TestClient(app)

def test_version_info():
    response = client.get('/api/version-info')
    assert response.status_code == 200
    assert response.json() == {'app': 'IGRIS_GPT', 'status': 'ok'}