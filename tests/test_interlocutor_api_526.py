"""Tests for Interlocutor API routes — issue #526."""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
import os

# Use tmp dir for all persistence
@pytest.fixture(autouse=True)
def patch_env(tmp_path, monkeypatch):
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("igris.api.routes.interlocutor._PROJECT_ROOT", str(tmp_path))


@pytest.fixture()
def client():
    from igris.api.routes.interlocutor import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_list_profiles_empty(client):
    r = client.get("/api/identity/profiles")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get_profile(client):
    payload = {"profile_id": "alice", "display_name": "Alice", "trust_level": "trusted",
                "authorized_scopes": ["read"], "expertise_level": "expert",
                "communication_style": "technical"}
    r = client.post("/api/identity/profiles", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["profile_id"] == "alice"

    r2 = client.get("/api/identity/profiles/alice")
    assert r2.status_code == 200
    assert r2.json()["display_name"] == "Alice"


def test_grant_scope(client):
    client.post("/api/identity/profiles", json={
        "profile_id": "bob", "display_name": "Bob"})
    r = client.post("/api/identity/profiles/bob/scopes/grant", json={"scope": "deploy"})
    assert r.status_code == 200
    assert r.json()["action"] == "granted"


def test_revoke_scope(client):
    client.post("/api/identity/profiles", json={
        "profile_id": "carol", "display_name": "Carol",
        "authorized_scopes": ["read", "write"]})
    r = client.post("/api/identity/profiles/carol/scopes/revoke", json={"scope": "write"})
    assert r.status_code == 200


def test_create_delegation_key_no_secrets_in_response(client):
    # Create admin profile first
    client.post("/api/identity/profiles", json={
        "profile_id": "admin", "display_name": "Admin",
        "trust_level": "admin", "authorized_scopes": ["read"]})
    r = client.post("/api/delegation-keys", json={
        "granted_by": "admin",
        "authorized_scopes": ["read"],
        "raw_passphrase": "supersecret_passphrase",
    })
    assert r.status_code == 201
    data = r.json()
    # Must NOT expose secrets
    assert "passphrase_hash" not in data
    assert "salt" not in data
    assert "supersecret" not in str(data)
    assert "key_id" in data


def test_verify_delegation_key(client, tmp_path, monkeypatch):
    monkeypatch.setattr("igris.api.routes.interlocutor._PROJECT_ROOT", str(tmp_path))
    from igris.core.delegation_keys import create_key
    key = create_key(str(tmp_path), "admin", ["read"], ["read"], "mypass")
    r = client.post("/api/delegation-keys/verify", json={
        "key_id": key.key_id,
        "raw_passphrase": "mypass",
        "requested_scopes": ["read"],
    })
    assert r.status_code == 200
    assert r.json()["allowed"] is True


def test_list_delegation_keys_no_secrets(client, tmp_path, monkeypatch):
    monkeypatch.setattr("igris.api.routes.interlocutor._PROJECT_ROOT", str(tmp_path))
    from igris.core.delegation_keys import create_key
    create_key(str(tmp_path), "admin", ["read"], ["read"], "pass123")
    r = client.get("/api/delegation-keys")
    assert r.status_code == 200
    for key_data in r.json():
        assert "passphrase_hash" not in key_data
        assert "salt" not in key_data


def test_audit_recent(client):
    r = client.get("/api/interlocutor/audit/recent")
    assert r.status_code == 200
    assert "events" in r.json()
