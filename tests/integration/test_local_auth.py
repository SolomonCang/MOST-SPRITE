from __future__ import annotations

from fastapi.testclient import TestClient


def test_preconfigured_accounts_can_login_switch_and_logout(api_client: TestClient) -> None:
    unauthenticated = api_client.get("/api/v1/me")
    assert unauthenticated.status_code == 401

    configuration = api_client.get("/api/v1/auth/configuration")
    assert configuration.status_code == 200
    body = configuration.json()
    assert body["auth_mode"] == "dev"
    assert {account["role"] for account in body["accounts"]} == {
        "administrator",
        "observer",
        "instrument_engineer",
        "data_reducer",
    }
    default_account = next(
        account for account in body["accounts"] if account["id"] == body["default_account_id"]
    )
    assert default_account["username"] == "administrator"

    for account in body["accounts"]:
        logged_in = api_client.post(
            "/api/v1/auth/login", json={"account_id": account["id"]}
        )
        assert logged_in.status_code == 200
        assert logged_in.json()["subject"] == account["username"]
        assert logged_in.json()["role"] == account["role"]
        assert "HttpOnly" in logged_in.headers["set-cookie"]
        current = api_client.get("/api/v1/me")
        assert current.status_code == 200
        assert current.json() == logged_in.json()

    logged_out = api_client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 204
    assert api_client.get("/api/v1/me").status_code == 401


def test_tampered_local_session_is_rejected(api_client: TestClient) -> None:
    configuration = api_client.get("/api/v1/auth/configuration").json()
    account_id = configuration["default_account_id"]
    assert api_client.post("/api/v1/auth/login", json={"account_id": account_id}).status_code == 200
    token = api_client.cookies.get("sprite_session")
    assert token
    api_client.cookies.set("sprite_session", f"{token}tampered")
    response = api_client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_SESSION_INVALID"


def test_selected_role_is_enforced(api_client: TestClient) -> None:
    configuration = api_client.get("/api/v1/auth/configuration").json()
    observer = next(
        account for account in configuration["accounts"] if account["role"] == "observer"
    )
    assert api_client.post(
        "/api/v1/auth/login", json={"account_id": observer["id"]}
    ).status_code == 200
    forbidden = api_client.post(
        "/api/v1/instrument:recover",
        headers={"Idempotency-Key": "observer-recover-0001"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"
