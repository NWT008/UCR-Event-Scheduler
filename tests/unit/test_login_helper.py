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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.login_helper import is_authenticated_url, perform_interactive_login


def test_is_authenticated_url():
    # Authenticated 25Live URLs
    assert is_authenticated_url("https://25live.collegenet.com/pro/ucr#!/home/dash")
    assert is_authenticated_url(
        "https://25live.collegenet.com/pro/ucr#!/home/event/list"
    )

    # Unauthenticated / SSO redirect URLs
    assert not is_authenticated_url(
        "https://auth.ucr.edu/cas/login?service=https://25live..."
    )
    assert not is_authenticated_url("https://25live.collegenet.com/shibboleth/login")
    assert not is_authenticated_url("https://api.duosecurity.com/frame/prompt")
    assert not is_authenticated_url("https://google.com")


@pytest.mark.asyncio
async def test_perform_interactive_login_invalid_id():
    success, msg = await perform_interactive_login("invalid id with spaces")
    assert not success
    assert "Invalid Discord ID" in msg


@pytest.mark.asyncio
async def test_perform_interactive_login_success(monkeypatch, tmp_path):
    user_id = "test_user_456"
    test_cookies = [
        {
            "name": "WSSESSIONID",
            "value": "authenticated_val_789",
            "domain": "25live.collegenet.com",
            "path": "/",
        }
    ]

    # Mock DB save_session
    mock_save = MagicMock()
    monkeypatch.setattr("app.login_helper.save_session", mock_save)

    # Mock Playwright
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.url = "https://25live.collegenet.com/pro/ucr#!/home/dash"
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(
        return_value="<html><body><div>Sign Out</div></body></html>"
    )

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.cookies = AsyncMock(return_value=test_cookies)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_p_ctx = MagicMock()
    mock_p_ctx.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_p_ctx.__aexit__ = AsyncMock()

    with patch("app.login_helper.async_playwright", return_value=mock_p_ctx):
        success, msg = await perform_interactive_login(user_id, timeout_seconds=5)

    assert success
    assert "Successfully authenticated" in msg
    mock_save.assert_called_once_with(user_id, test_cookies)
