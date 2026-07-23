from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOMIHELM_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    main.login_limiter.events.clear()
    with TestClient(main.app) as test_client:
        yield test_client


def owner_payload(**overrides):
    payload = {
        "display_name": "Tomer",
        "email": "tomer@example.com",
        "password": "correct horse battery staple",
        "organization_name": "MomiHelm Demo",
        "department_id": "Engineering",
    }
    payload.update(overrides)
    return payload


def setup_owner(client: TestClient):
    response = client.post("/auth/setup", json=owner_payload())
    assert response.status_code == 201
    return response


def test_first_run_setup_creates_owner_and_http_only_session(client: TestClient):
    state = client.get("/auth/state")
    assert state.json() == {
        "setup_required": True,
        "authenticated": False,
        "user": None,
    }

    response = setup_owner(client)
    user = response.json()["user"]
    assert user["display_name"] == "Tomer"
    assert user["role"] == "owner"
    assert user["can_manage"] is True
    assert user["department_id"] == "engineering"
    assert user["policy_mode"] == "balanced"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "tomer@example.com"


def test_setup_is_single_use(client: TestClient):
    setup_owner(client)
    second = client.post(
        "/auth/setup",
        json=owner_payload(email="other@example.com"),
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "setup_already_completed"


def test_login_and_logout_invalidate_session(client: TestClient):
    setup_owner(client)
    logout = client.post("/auth/logout")
    assert logout.status_code == 204
    assert logout.content == b""
    cookie = logout.headers["set-cookie"]
    assert "momihelm_session=\"\"" in cookie
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert client.get("/auth/me").status_code == 401

    rejected = client.post(
        "/auth/login",
        json={"email": "tomer@example.com", "password": "wrong"},
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "invalid_credentials"

    accepted = client.post(
        "/auth/login",
        json={
            "email": "tomer@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["authenticated"] is True
    assert client.get("/auth/me").status_code == 200

    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


def test_user_can_change_password_and_refresh_session(client: TestClient):
    setup_owner(client)
    changed = client.put(
        "/auth/password",
        json={
            "current_password": "correct horse battery staple",
            "new_password": "a new and stronger password",
        },
    )
    assert changed.status_code == 200
    assert client.get("/auth/me").status_code == 200

    client.post("/auth/logout")
    old_password = client.post(
        "/auth/login",
        json={
            "email": "tomer@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert old_password.status_code == 401
    new_password = client.post(
        "/auth/login",
        json={
            "email": "tomer@example.com",
            "password": "a new and stronger password",
        },
    )
    assert new_password.status_code == 200


def test_unknown_origin_is_rejected(client: TestClient):
    response = client.post(
        "/auth/setup",
        json=owner_payload(),
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "untrusted_origin"


def test_policy_is_persisted_server_side(client: TestClient):
    setup_owner(client)
    response = client.put("/policy", json={"policy_mode": "aggressive"})
    assert response.status_code == 200
    assert response.json()["policy_mode"] == "aggressive"
    assert client.get("/auth/me").json()["policy_mode"] == "aggressive"


def test_protected_routes_require_a_session(client: TestClient):
    assert client.post("/webhook/tokenwise", json={"prompt": "hello"}).status_code == 401
    assert client.get("/webhook/tokenwise-usage-summary").status_code == 401
    assert client.post("/coding/sessions", json={"objective": "fix code"}).status_code == 401
    assert client.get("/coding/sessions").status_code == 401
    assert client.put("/policy", json={"policy_mode": "balanced"}).status_code == 401
    assert client.get("/users").status_code == 401


def test_coding_session_gateway_enforces_identity_and_read_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = setup_owner(client).json()
    calls = []

    async def fake_optimizer(method, path, *, payload=None, params=None):
        calls.append(
            {"method": method, "path": path, "payload": payload, "params": params}
        )
        return Response(content="{}", media_type="application/json", status_code=201)

    monkeypatch.setattr(main, "_optimizer_request", fake_optimizer)
    created = client.post(
        "/coding/sessions",
        json={
            "objective": "I want you to code with me some game",
            "organization_id": "attacker-org",
            "user_id": "attacker-user",
            "dept_id": "attacker-dept",
            "policy_mode": "aggressive",
        },
    )
    listed = client.get(
        "/coding/sessions?organization_id=attacker&user_id=attacker"
    )

    assert created.status_code == 201
    trusted = calls[0]["payload"]
    assert trusted["organization_id"] == setup["user"]["organization_id"]
    assert trusted["user_id"] == setup["user"]["id"]
    assert trusted["dept_id"] == "engineering"
    assert trusted["policy_mode"] == "balanced"
    assert calls[1]["params"] == {
        "organization_id": setup["user"]["organization_id"],
        "limit": 50,
    }


def test_coding_session_mutations_are_always_user_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = setup_owner(client).json()
    calls = []

    async def fake_optimizer(method, path, *, payload=None, params=None):
        calls.append(
            {"method": method, "path": path, "payload": payload, "params": params}
        )
        return Response(content="{}", media_type="application/json")

    monkeypatch.setattr(main, "_optimizer_request", fake_optimizer)
    patched = client.patch(
        "/coding/sessions/cs-123",
        json={"confirmed_task_type": "feature_implementation"},
    )
    verified = client.post(
        "/coding/sessions/cs-123/verification",
        json={
            "verification_type": "user_acceptance",
            "source": "user",
            "status": "passed",
        },
    )

    expected_scope = {
        "organization_id": setup["user"]["organization_id"],
        "user_id": setup["user"]["id"],
    }
    assert patched.status_code == 200
    assert verified.status_code == 200
    assert calls[0]["params"] == expected_scope
    assert calls[1]["payload"]["organization_id"] == expected_scope["organization_id"]
    assert calls[1]["payload"]["user_id"] == expected_scope["user_id"]
    assert calls[1]["payload"]["source"] == "user"

    forged_automation = client.post(
        "/coding/sessions/cs-123/verification",
        json={
            "verification_type": "tests",
            "source": "automated",
            "status": "passed",
        },
    )
    assert forged_automation.status_code == 422


def test_gateway_overrides_untrusted_identity_and_policy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = setup_owner(client).json()
    captured = {}

    async def fake_upstream(method, path, *, payload=None, params=None):
        captured.update(
            {"method": method, "path": path, "payload": payload, "params": params}
        )
        return Response(
            content='{"answer":"ok","receipt":{}}',
            media_type="application/json",
        )

    monkeypatch.setattr(main, "_upstream_request", fake_upstream)
    response = client.post(
        "/webhook/tokenwise",
        json={
            "prompt": "hello",
            "organization_id": "attacker-org",
            "user_id": "attacker-user",
            "dept_id": "attacker-dept",
            "policy_mode": "conservative",
        },
    )
    assert response.status_code == 200
    trusted = captured["payload"]
    assert trusted["organization_id"] == setup["user"]["organization_id"]
    assert trusted["user_id"] == setup["user"]["id"]
    assert trusted["dept_id"] == "engineering"
    assert trusted["policy_mode"] == "balanced"
    assert trusted["request_id"].startswith("r-")


def test_owner_dashboard_is_forced_to_organization_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = setup_owner(client).json()
    captured = {}

    async def fake_upstream(method, path, *, payload=None, params=None):
        captured.update({"method": method, "path": path, "params": params})
        return Response(content="{}", media_type="application/json")

    monkeypatch.setattr(main, "_upstream_request", fake_upstream)
    response = client.get(
        "/webhook/tokenwise-usage-summary"
        "?organization_id=attacker&dept_id=finance&period_days=7"
    )
    assert response.status_code == 200
    assert captured["params"]["organization_id"] == setup["user"]["organization_id"]
    assert captured["params"]["include_legacy"] == "true"
    assert captured["params"]["dept_id"] == "finance"
    assert captured["params"]["period_days"] == 7


def test_owner_can_create_member_with_user_scoped_dashboard(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = setup_owner(client).json()
    created = client.post(
        "/users",
        json={
            "display_name": "Maya",
            "email": "maya@example.com",
            "password": "a different secure password",
            "role": "member",
            "department_id": "Customer Success",
        },
    )
    assert created.status_code == 201
    member = created.json()
    assert member["organization_id"] == setup["user"]["organization_id"]
    assert member["role"] == "member"
    assert member["can_manage"] is False
    assert member["department_id"] == "customer-success"
    assert len(client.get("/users").json()) == 2

    client.post("/auth/logout")
    accepted = client.post(
        "/auth/login",
        json={
            "email": "maya@example.com",
            "password": "a different secure password",
        },
    )
    assert accepted.status_code == 200
    assert client.put("/policy", json={"policy_mode": "aggressive"}).status_code == 403
    assert client.get("/users").status_code == 403

    captured = {}

    async def fake_upstream(method, path, *, payload=None, params=None):
        captured.update({"method": method, "path": path, "params": params})
        return Response(content="{}", media_type="application/json")

    monkeypatch.setattr(main, "_upstream_request", fake_upstream)
    response = client.get(
        "/webhook/tokenwise-usage-summary"
        "?organization_id=attacker&user_id=attacker&dept_id=finance"
    )
    assert response.status_code == 200
    assert captured["params"] == {
        "period_days": 30,
        "organization_id": member["organization_id"],
        "user_id": member["id"],
    }
