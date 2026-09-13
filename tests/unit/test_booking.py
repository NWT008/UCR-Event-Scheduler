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

from app import booking


def test_is_mock_mode(monkeypatch):
    monkeypatch.setenv("USE_MOCK_25LIVE", "True")
    assert booking.is_mock_mode() is True

    monkeypatch.setenv("USE_MOCK_25LIVE", "False")
    assert booking.is_mock_mode() is False


@pytest.mark.asyncio
async def test_mock_check_room_availability(monkeypatch):
    monkeypatch.setenv("USE_MOCK_25LIVE", "True")

    # Available room
    res = await booking.check_room_availability(
        [], "2026-10-15", "18:00", "Winston Chung Hall 205"
    )
    assert res["status"] == "success"
    assert res["available"] is True

    # Unavailable room (mock rule checks for "unavailable" in name)
    res_unavailable = await booking.check_room_availability(
        [], "2026-10-15", "18:00", "Winston Chung Hall 205 (Unavailable)"
    )
    assert res_unavailable["status"] == "success"
    assert res_unavailable["available"] is False


@pytest.mark.asyncio
async def test_mock_fill_25live_wizard(monkeypatch):
    monkeypatch.setenv("USE_MOCK_25LIVE", "True")

    event_details = {
        "location": "Winston Chung Hall 205",
        "event_name": "CS Club Meeting",
        "event_title": "ACM CS Meeting",
        "event_description": "Discussion",
        "event_type": "Meeting",
        "primary_organization": "ACM",
        "expected_attendance": 20,
        "start_time": "2026-10-15 18:00",
        "end_time": "2026-10-15 19:00",
        "audiovisual_requirements": "Projector",
        "serving_food": True,
        "serving_beverages": False,
        "serving_alcohol": False,
        "who_is_attending": "Members",
        "additional_comments": "No comments",
    }

    session_id, screenshot = await booking.fill_25live_wizard([], event_details)
    assert session_id == "mock_session_98765"
    assert len(screenshot) > 0
    # PNG magic number verification
    assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_mock_confirm_booking(monkeypatch):
    monkeypatch.setenv("USE_MOCK_25LIVE", "True")

    conf_id = await booking.confirm_booking("mock_session_98765")
    assert conf_id == "UCR-MOCK-987654"


def test_extract_25live_reference():
    # Valid references
    assert booking.extract_25live_reference("2026-ACFSPN") == "2026-ACFSPN"
    assert (
        booking.extract_25live_reference("Event details: Reference: 2026-BCDFG1")
        == "2026-BCDFG1"
    )
    assert (
        booking.extract_25live_reference(
            "https://25live.collegenet.com/pro/ucr#!/home/event/2026-ACFSPN/details"
        )
        == "2026-ACFSPN"
    )

    # Invalid / false positives
    assert booking.extract_25live_reference("UCR-CONFIRMED-OK") is None
    assert booking.extract_25live_reference("2026-MOCK01") is None
    assert booking.extract_25live_reference("No reference here") is None
    assert booking.extract_25live_reference("") is None


@pytest.mark.asyncio
async def test_real_mode_confirm_booking_failure_raises_runtime_error(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setenv("USE_MOCK_25LIVE", "False")

    mock_page = MagicMock()
    mock_page.url = "https://25live.collegenet.com/pro/ucr#!/home/event/form"
    mock_page.goto = AsyncMock()
    mock_save_btn = MagicMock()
    mock_save_btn.click = AsyncMock()
    mock_page.wait_for_selector = AsyncMock(return_value=mock_save_btn)
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.content = AsyncMock(
        return_value="<html><body><div class='validation-error'>Location is required</div></body></html>"
    )

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = MagicMock()
    mock_browser.close = AsyncMock()

    mock_get_ctx = AsyncMock(return_value=(mock_browser, mock_context))
    monkeypatch.setattr("app.booking.get_browser_context", mock_get_ctx)
    monkeypatch.setattr("asyncio.sleep", AsyncMock(return_value=None))

    with pytest.raises(RuntimeError) as exc_info:
        await booking.confirm_booking("nonexistent_session_context")

    assert "Playwright final reservation confirmation failed" in str(exc_info.value)
