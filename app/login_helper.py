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

"""Interactive login helper for UCR 25Live authentication with Duo MFA.

SECURITY GUARANTEE:
- Zero Password Exposure: This tool never accesses, reads, logs, or stores user passwords.
- Users authenticate directly inside an official, visible Chromium browser window on UCR's
  HTTPS CAS/Shibboleth SSO portal.
- Playwright passively waits until post-authentication redirection to 25Live is reached,
  extracts only the resulting session cookies, encrypts them bound to the user's Discord ID,
  and closes the browser.
"""

import argparse
import asyncio
import sys
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from app.db import save_session
from app.security import validate_discord_id

TARGET_URL = "https://25live.collegenet.com/pro/ucr#!/home/dash"

ACTIVE_LOGIN_EVENTS: dict[str, asyncio.Event] = {}
ACTIVE_LOGIN_CONTEXTS: dict[str, Any] = {}


def signal_login_complete(discord_id: str) -> bool:
    """Signals an active interactive login session to capture cookies and finalize immediately."""
    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError:
        return False
    event = ACTIVE_LOGIN_EVENTS.get(clean_id)
    if event:
        event.set()
        return True
    return False


def is_authenticated_url(url: str) -> bool:
    """Checks whether the browser URL indicates a completed login on 25Live."""
    u = url.lower()
    if "25live.collegenet.com" in u:
        # Ensure we are not on any intermediate login or redirect endpoints
        for unauth_indicator in ["login", "shibboleth", "cas", "duo", "auth.ucr.edu"]:
            if unauth_indicator in u:
                return False
        return True
    return False


async def perform_interactive_login(
    discord_id: str, timeout_seconds: int = 300
) -> tuple[bool, str]:
    """Launches a visible Chromium window for the user to complete UCR NetID SSO + Duo MFA.

    Args:
        discord_id: The Discord snowflake ID of the user to bind cookies to.
        timeout_seconds: Maximum time allowed to complete authentication (default 5 mins).

    Returns:
        (success, message)
    """
    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError as e:
        return False, f"Invalid Discord ID: {e!s}"

    print(f"[*] Initiating interactive UCR 25Live login for Discord user: {clean_id}")
    print("[*] Launching visible browser. Please complete UCR SSO and Duo MFA...")

    finish_event = asyncio.Event()
    ACTIVE_LOGIN_EVENTS[clean_id] = finish_event

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--start-maximized",
                ],
            )
            context = await browser.new_context(
                no_viewport=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            ACTIVE_LOGIN_CONTEXTS[clean_id] = context
            page = await context.new_page()

            # Navigate to 25Live portal (redirects to UCR CAS login)
            try:
                await page.goto(
                    TARGET_URL, wait_until="domcontentloaded", timeout=60000
                )
                await page.bring_to_front()
                await page.evaluate("() => window.focus()")
            except Exception as e:
                print(f"Warning on initial navigation: {e!s}")

            # Poll until user completes Duo MFA and lands on 25Live
            poll_interval = 2.0
            elapsed = 0.0
            logged_in = False
            visited_login = False

            while elapsed < timeout_seconds:
                # Check if external signal (e.g. from web button) was fired
                if finish_event.is_set():
                    logged_in = True
                    break

                if page.is_closed():
                    # If page was closed, check if cookies were captured before closing
                    cookies = await context.cookies()
                    has_session_cookie = any(
                        "shib" in c.get("name", "").lower()
                        or "session" in c.get("name", "").lower()
                        for c in cookies
                    )
                    if has_session_cookie:
                        logged_in = True
                        break
                    await browser.close()
                    return False, "Browser was closed before authentication completed."

                current_url = page.url.lower()

                # Detect when user lands on UCR SSO / CAS login page
                if (
                    "auth.ucr.edu" in current_url
                    or "cas" in current_url
                    or "login" in current_url
                ):
                    visited_login = True

                # After user visited login, detect return to 25Live dashboard
                if visited_login and is_authenticated_url(current_url):
                    cookies = await context.cookies()
                    has_session_cookie = any(
                        "shib" in c.get("name", "").lower()
                        or "session" in c.get("name", "").lower()
                        or "collegenet.com" in c.get("domain", "")
                        for c in cookies
                    )
                    if has_session_cookie:
                        await asyncio.sleep(3)  # Wait for SPA to settle
                        logged_in = True
                        break

                # Also support direct detection if user arrived at home dashboard with sign-out indicator
                if not visited_login and is_authenticated_url(current_url):
                    try:
                        content = await page.content()
                        if "sign out" in content.lower() or "logout" in content.lower():
                            logged_in = True
                            break
                    except Exception:
                        pass

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            if not logged_in:
                await browser.close()
                return (
                    False,
                    "Authentication timed out waiting for Duo MFA / login completion.",
                )

            # Intercept all session cookies
            all_cookies = await context.cookies()
            filtered_cookies: list[dict[str, Any]] = [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                }
                for c in all_cookies
                if "collegenet.com" in c.get("domain", "")
                or "ucr.edu" in c.get("domain", "")
            ]

            if not filtered_cookies:
                await browser.close()
                return False, "No valid session cookies captured after login."

            # Encrypt and save session strictly bound to this Discord ID
            save_session(clean_id, filtered_cookies)
            await browser.close()

            print(
                f"[+] Successfully captured and encrypted {len(filtered_cookies)} cookies."
            )
            return (
                True,
                f"Successfully authenticated with UCR 25Live. Session encrypted for Discord ID: {clean_id}.",
            )

    except Exception as e:
        return False, f"Interactive login failed: {e!s}"
    finally:
        ACTIVE_LOGIN_EVENTS.pop(clean_id, None)
        ACTIVE_LOGIN_CONTEXTS.pop(clean_id, None)


def main():
    """CLI entrypoint for standalone terminal authentication."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Interactive login helper for UCR 25Live with Duo MFA."
    )
    parser.add_argument(
        "--discord-id",
        dest="discord_id",
        help="The Discord user ID to bind the authenticated session to.",
        default=None,
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=int,
        default=300,
        help="Timeout in seconds to complete login (default: 300).",
    )

    args = parser.parse_args()
    discord_id = args.discord_id

    if not discord_id:
        # Prompt interactively if not passed
        try:
            discord_id = input("Enter your Discord User ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not discord_id:
        print("Error: Discord User ID is required.", file=sys.stderr)
        sys.exit(1)

    success, msg = asyncio.run(
        perform_interactive_login(discord_id=discord_id, timeout_seconds=args.timeout)
    )
    if success:
        print(f"\n[SUCCESS] {msg}")
        sys.exit(0)
    else:
        print(f"\n[ERROR] {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
