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

from app import agent, db


@pytest.fixture(autouse=True)
def setup_env_and_db(monkeypatch, tmp_path):
    monkeypatch.setenv("COOKIE_ENCRYPTION_KEY", "test_key_agent")
    monkeypatch.setenv("USE_MOCK_25LIVE", "True")
    test_db = str(tmp_path / "test_session_cache_agent.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()

    # Save a mock session for testing
    db.save_session("user123", [{"name": "mock", "value": "val", "domain": "ucr.edu"}])


@pytest.mark.asyncio
async def test_check_room_availability_tool():
    res = await agent.check_room_availability_tool(
        discord_id="user123",
        date="2026-10-15",
        time="18:00",
        room_preference="Winston Chung Hall 205",
    )
    assert "AVAILABLE" in res
    assert "Winston Chung Hall 205" in res


@pytest.mark.asyncio
async def test_check_room_availability_unauthenticated():
    res = await agent.check_room_availability_tool(
        discord_id="missing_user",
        date="2026-10-15",
        time="18:00",
        room_preference="WCH 205",
    )
    assert "ERROR" in res
    assert "not authenticated" in res


@pytest.mark.asyncio
async def test_submit_25live_reservation_tool():
    res = await agent.submit_25live_reservation_tool(
        discord_id="user123",
        location="WCH 205",
        event_name="CS Club",
        event_title="ACM Meeting",
        event_description="Discussion of ACM rules",
        event_type="Meeting",
        primary_organization="ACM",
        expected_attendance=30,
        start_time="2026-10-15 18:00",
        end_time="2026-10-15 19:00",
        audiovisual_requirements="None",
        serving_food=False,
        serving_beverages=False,
        serving_alcohol=False,
        who_is_attending="Students",
    )
    assert "SUCCESS" in res
    assert "UCR-MOCK-987654" in res
