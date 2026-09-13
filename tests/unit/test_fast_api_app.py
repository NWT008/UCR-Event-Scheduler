# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from fastapi.testclient import TestClient

from app import db


@pytest.fixture(autouse=True)
def setup_env_and_db(monkeypatch, tmp_path):
    monkeypatch.setenv("COOKIE_ENCRYPTION_KEY", "test_key_fastapi")
    test_db = str(tmp_path / "test_session_cache_fastapi.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()


def test_login_endpoint():
    # Import app inside so monkeypatch applies to env vars checked at module level
    from app.fast_api_app import app

    client = TestClient(app)

    response = client.get("/login?discord_id=user123")
    assert response.status_code == 200
    assert "UCR Single Sign-On" in response.text
    assert "user123" in response.text


def test_capture_endpoint():
    from app.fast_api_app import app

    client = TestClient(app)

    # Assert session is initially empty
    assert db.get_session("user123") is None

    response = client.get("/capture?discord_id=user123")
    assert response.status_code == 200
    assert "Authentication Successful" in response.text

    # Verify session cookies were encrypted and saved
    cookies = db.get_session("user123")
    assert cookies is not None
    assert len(cookies) == 2
    assert cookies[0]["name"] == "WSSESSIONID"
    assert "user123" in cookies[0]["value"]


def test_select_time_endpoint():
    from app.fast_api_app import app

    client = TestClient(app)

    response = client.get("/select_time?discord_id=user123")
    assert response.status_code == 200
    assert "Select Event Date & Time" in response.text
    assert "user123" in response.text


def test_save_selected_time_endpoint():
    from app.fast_api_app import app

    client = TestClient(app)

    # Initial get should be None
    assert db.get_selected_time("user123") is None

    payload = {
        "discord_id": "user123",
        "start_time": "2026-10-15 18:00",
        "end_time": "2026-10-15 19:00",
    }
    response = client.post("/save_selected_time", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Retrieve from DB
    res = db.get_selected_time("user123")
    assert res is not None
    assert res[0] == "2026-10-15 18:00"
    assert res[1] == "2026-10-15 19:00"


def test_api_session_status_and_import_cookies():
    from app.fast_api_app import app

    client = TestClient(app)

    # Initial status: false
    res = client.get("/api/session_status?discord_id=user123")
    assert res.status_code == 200
    assert res.json()["authenticated"] is False

    # Import cookies via JSON
    cookie_json = '[{"name": "WSSESSIONID", "value": "live_val_abc", "domain": "25live.collegenet.com"}]'
    res_import = client.post(
        "/api/import_cookies",
        json={"discord_id": "user123", "cookies_data": cookie_json},
    )
    assert res_import.status_code == 200
    assert res_import.json()["status"] == "success"
    assert res_import.json()["count"] == 1

    # Check status again: true
    res_after = client.get("/api/session_status?discord_id=user123")
    assert res_after.status_code == 200
    assert res_after.json()["authenticated"] is True
    assert res_after.json()["count"] == 1

    # Verify decrypted from DB
    cookies = db.get_session("user123")
    assert cookies is not None
    assert cookies[0]["name"] == "WSSESSIONID"
    assert cookies[0]["value"] == "live_val_abc"


def test_api_start_login_endpoint(monkeypatch):
    from unittest.mock import AsyncMock

    from app.fast_api_app import app

    mock_perform = AsyncMock(return_value=(True, "ok"))
    monkeypatch.setattr("app.login_helper.perform_interactive_login", mock_perform)

    client = TestClient(app)
    res = client.post("/api/start_login", json={"discord_id": "user123"})
    assert res.status_code == 200
    assert res.json()["status"] == "started"


def test_import_cookies_bare_token():
    from app.fast_api_app import app

    client = TestClient(app)
    token = "s%3A_0WP86-eI6z_lV8someLongTokenValue12345"
    res = client.post(
        "/api/import_cookies",
        json={"discord_id": "user123", "cookies_data": token},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["count"] == 1

    saved = db.get_session("user123")
    assert saved is not None
    assert saved[0]["name"] == "WSSESSIONID"
    assert saved[0]["value"] == token


def test_api_complete_login(monkeypatch):
    from app.fast_api_app import app

    monkeypatch.setattr("app.login_helper.signal_login_complete", lambda uid: True)

    client = TestClient(app)
    res = client.post("/api/complete_login", json={"discord_id": "user123"})
    assert res.status_code == 200
    assert res.json()["status"] == "signaled"
