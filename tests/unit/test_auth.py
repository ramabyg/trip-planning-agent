"""Family login gate: cookie crypto (auth.py) and the HTTP surface (main.py).

Offline — TestClient never reaches an LLM; auth rejects requests before the
agent layer, and only auth/identity endpoints are exercised authenticated.
"""
import pytest
from fastapi.testclient import TestClient

import auth


@pytest.fixture()
def configured_auth(monkeypatch):
    monkeypatch.setenv("FAMILY1_PASSWORD", "pw-one")
    monkeypatch.setenv("FAMILY2_PASSWORD", "pw-two")
    monkeypatch.setenv("FAMILY3_PASSWORD", "pw-three")
    monkeypatch.setenv("COOKIE_SECRET", "unit-test-secret")


@pytest.fixture()
def client(configured_auth):
    import main
    # https base URL so the Secure cookie is stored and replayed by the client.
    return TestClient(main.app, base_url="https://testserver")


class TestCookieCrypto:
    def test_password_identifies_family(self, configured_auth):
        assert auth.check_password("pw-two") == "family-2"
        assert auth.check_password("pw-one") == "family-1"
        assert auth.check_password("wrong") is None
        assert auth.check_password("") is None

    def test_cookie_round_trip(self, configured_auth):
        value = auth.make_cookie_value("family-3")
        assert auth.verify_cookie_value(value) == "family-3"

    def test_tampered_cookie_rejected(self, configured_auth):
        value = auth.make_cookie_value("family-2")
        family, expires, signature = value.split(".")
        assert auth.verify_cookie_value(f"family-1.{expires}.{signature}") is None
        assert auth.verify_cookie_value(f"{family}.{expires}.{'0' * 64}") is None
        assert auth.verify_cookie_value("garbage") is None
        assert auth.verify_cookie_value(None) is None

    def test_expired_cookie_rejected(self, configured_auth):
        value = auth.make_cookie_value("family-2", now=0)  # expired long ago
        assert auth.verify_cookie_value(value) is None

    def test_gate_disabled_without_passwords(self, monkeypatch):
        for i in (1, 2, 3):
            monkeypatch.delenv(f"FAMILY{i}_PASSWORD", raising=False)
        assert not auth.auth_enabled()


class TestHttpGate:
    def test_protected_routes_require_login(self, client):
        assert client.get("/api/trip-context").status_code == 401
        assert client.post("/run_sse", json={}).status_code == 401
        assert client.get("/tmp/day_1_plan.md").status_code == 401
        assert client.get("/api/me").status_code == 401

    def test_browser_redirects_to_login(self, client):
        response = client.get("/ui/", headers={"accept": "text/html"},
                              follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_login_page_is_public(self, client):
        assert client.get("/login").status_code == 200
        assert client.get("/api/health").status_code == 200

    def test_wrong_password_rejected_without_detail(self, client):
        response = client.post("/login", json={"password": "nope"})
        assert response.status_code == 401
        assert "nope" not in response.text  # never echo the attempt

    def test_login_grants_family_scoped_access(self, client):
        response = client.post("/login", json={"password": "pw-two"})
        assert response.status_code == 200
        assert response.json()["family"] == "family-2"
        me = client.get("/api/me")
        assert me.status_code == 200
        assert me.json() == {"family": "family-2", "label": "Family 2"}
        assert client.get("/api/trip-context").status_code == 200

    def test_tampered_cookie_is_unauthenticated(self, client):
        client.post("/login", json={"password": "pw-one"})
        client.cookies.set(auth.COOKIE_NAME, "family-3.9999999999.deadbeef")
        assert client.get("/api/me").status_code == 401
