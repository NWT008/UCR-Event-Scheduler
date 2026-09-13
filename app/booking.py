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

import asyncio
import datetime
import json
import os
import re
import tempfile
from typing import Any

from dateutil import parser as dt_parser
from playwright.async_api import async_playwright

from app.building_aliases import match_starred_location, resolve_location_alias


def extract_25live_reference(text: str) -> str | None:
    """Extracts a valid 25Live Reference ID (e.g. 2026-ACFSPN) from text or None."""
    if not text:
        return None
    match = re.search(r"\b(20\d{2}-[A-Z0-9]{4,10})\b", text)
    if match:
        ref = match.group(1)
        if "CONFIRMED" not in ref and not ref.startswith("2026-MOCK"):
            return ref
    return None


def is_mock_mode() -> bool:
    """Returns True if the system is configured to run in Mock 25Live mode."""
    return os.getenv("USE_MOCK_25LIVE", "True").lower() in ["true", "1", "yes"]


async def get_browser_context(playwright, cookies: list[dict[str, Any]] | None = None):
    """Launches headless Chromium and sets up browser context with injected cookies."""
    browser = await playwright.chromium.launch(
        headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    if cookies:
        # Standardize cookie format for Playwright
        formatted_cookies = []
        for cookie in cookies:
            formatted = {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": cookie.get("domain"),
                "path": cookie.get("path", "/"),
            }
            # Remove domain leading dot if present for Playwright compat
            if formatted["domain"] and formatted["domain"].startswith("."):
                # Playwright accepts leading dot, but standardizing helps
                pass
            formatted_cookies.append(formatted)

        await context.add_cookies(formatted_cookies)

    return browser, context


async def check_room_availability(
    cookies: list[dict[str, Any]],
    date: str,
    time: str,
    room_preference: str,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Queries 25Live room availability. Supports Mock and Real modes."""
    if is_mock_mode():
        await asyncio.sleep(1.5)  # Simulate network/automation latency

        # Simple rule-based mock response
        room = room_preference.strip() or "Winston Chung Hall 205"
        available = (
            "unavailable" not in room.lower()
            and "conflict" not in room.lower()
            and "occupied" not in room.lower()
        )

        # If the requested time is 3:00 PM to 4:00 PM (15:00 - 16:00), simulate a conflict
        if time:
            t_lower = time.lower().strip()
            if (
                "15:00" in t_lower
                or "3:00 pm" in t_lower
                or "3:00pm" in t_lower
                or "3 pm" in t_lower
            ):
                available = False

        return {
            "status": "success",
            "available": available,
            "room": room,
            "message": f"Room '{room}' is AVAILABLE on {date} from {time} to {end_time or 'later'}."
            if available
            else f"Room '{room}' is UNAVAILABLE (conflict or occupied) on {date} at {time}.",
        }

    # --- Real Mode ---
    async with async_playwright() as p:
        browser, context = await get_browser_context(p, cookies)
        page = await context.new_page()
        try:
            # Navigate to UCR 25Live instance
            await page.goto(
                "https://25live.collegenet.com/pro/ucr#!/home/dash",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # Check if redirected to Shibboleth, CAS, or SSO login
            current_url = page.url.lower()
            if any(k in current_url for k in ["auth.ucr.edu", "sso.ucr.edu", "shibboleth", "cas/login", "login", "saml"]):
                return {
                    "status": "error",
                    "reason": "session_expired",
                    "message": "UCR session has expired or cookies are invalid. Re-authentication is required.",
                }

            # Perform search/availability check using common 25Live SPA selectors
            # Search input for locations
            await page.wait_for_selector(
                "input[placeholder*='Search Locations']", timeout=10000
            )
            await page.fill("input[placeholder*='Search Locations']", room_preference)
            await page.keyboard.press("Enter")

            await asyncio.sleep(2)  # Wait for table/results to load

            # Simple heuristic checking availability indicator
            content = await page.content()
            available = (
                "conflict" not in content.lower() and "occupied" not in content.lower()
            )

            return {
                "status": "success",
                "available": available,
                "room": room_preference,
                "message": f"Room '{room_preference}' is available."
                if available
                else f"Room '{room_preference}' is occupied.",
            }
        except Exception as e:
            current_url = page.url.lower() if page else ""
            if any(k in current_url for k in ["auth.ucr.edu", "sso.ucr.edu", "shibboleth", "cas/login", "login", "saml"]):
                return {
                    "status": "error",
                    "reason": "session_expired",
                    "message": "UCR session has expired or cookies are invalid. Re-authentication is required.",
                }
            return {
                "status": "error",
                "reason": "automation_failed",
                "message": f"Failed to check availability: {e!s}",
            }
        finally:
            await browser.close()


async def fill_25live_wizard(
    cookies: list[dict[str, Any]], event_details: dict[str, Any]
) -> tuple[str, bytes]:
    """Automates filling the 25Live Event Wizard. Returns (session_id_context, screenshot_bytes)."""
    if is_mock_mode():
        await asyncio.sleep(2.0)  # Simulate automation latency

        # Render a mock 25Live booking wizard preview page using local HTML and take a screenshot
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f0f2f5;
                    margin: 0;
                    padding: 20px;
                    display: flex;
                    justify-content: center;
                }}
                .wizard-container {{
                    width: 750px;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                    border-top: 6px solid #1a73e8;
                    padding: 25px;
                }}
                .header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    border-bottom: 2px solid #e8f0fe;
                    padding-bottom: 15px;
                    margin-bottom: 20px;
                }}
                .logo-text {{
                    font-size: 24px;
                    font-weight: bold;
                    color: #1a73e8;
                }}
                .step {{
                    color: #5f6368;
                    font-size: 14px;
                }}
                .section {{
                    margin-bottom: 18px;
                }}
                .label {{
                    font-weight: 600;
                    color: #202124;
                    margin-bottom: 6px;
                    font-size: 14px;
                }}
                .value {{
                    font-size: 15px;
                    color: #3c4043;
                    background: #f8f9fa;
                    padding: 10px;
                    border-radius: 4px;
                    border: 1px solid #dadce0;
                }}
                .row {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 15px;
                }}
                .badge {{
                    display: inline-block;
                    padding: 3px 8px;
                    border-radius: 12px;
                    font-size: 12px;
                    font-weight: 500;
                    color: white;
                }}
                .badge-yes {{ background-color: #137333; }}
                .badge-no {{ background-color: #c5221f; }}
            </style>
        </head>
        <body>
            <div class="wizard-container">
                <div class="header">
                    <span class="logo-text">UCR 25Live Event Wizard</span>
                    <span class="step">Step 14 of 14: Summary Preview</span>
                </div>

                <div class="section">
                    <div class="label">Event Name (Internal)</div>
                    <div class="value">{event_details.get("event_name")}</div>
                </div>

                <div class="section">
                    <div class="label">Event Title (Published Calendars)</div>
                    <div class="value">{event_details.get("event_title")}</div>
                </div>

                <div class="section">
                    <div class="label">Event Description</div>
                    <div class="value" style="white-space: pre-wrap;">{event_details.get("event_description", "")}</div>
                </div>

                <div class="row">
                    <div class="section">
                        <div class="label">Event Type</div>
                        <div class="value">{event_details.get("event_type")}</div>
                    </div>
                    <div class="section">
                        <div class="label">Sponsoring Organization</div>
                        <div class="value">{event_details.get("primary_organization")}</div>
                    </div>
                </div>

                <div class="row">
                    <div class="section">
                        <div class="label">Start Date & Time</div>
                        <div class="value">{event_details.get("start_time")}</div>
                    </div>
                    <div class="section">
                        <div class="label">End Date & Time</div>
                        <div class="value">{event_details.get("end_time")}</div>
                    </div>
                </div>

                <div class="row">
                    <div class="section">
                        <div class="label">Location (Room)</div>
                        <div class="value">{event_details.get("location")}</div>
                    </div>
                    <div class="section">
                        <div class="label">Expected Attendance</div>
                        <div class="value">{event_details.get("expected_attendance")} attendees</div>
                    </div>
                </div>

                <div class="section">
                    <div class="label">Audiovisual Requirements</div>
                    <div class="value">{event_details.get("audiovisual_requirements")}</div>
                </div>

                <div class="row">
                    <div class="section">
                        <div class="label">Serving Food</div>
                        <div>
                            <span class="badge {"badge-yes" if event_details.get("serving_food") else "badge-no"}">
                                {"Yes" if event_details.get("serving_food") else "No"}
                            </span>
                        </div>
                    </div>
                    <div class="section">
                        <div class="label">Serving Beverages</div>
                        <div>
                            <span class="badge {"badge-yes" if event_details.get("serving_beverages") else "badge-no"}">
                                {"Yes" if event_details.get("serving_beverages") else "No"}
                            </span>
                        </div>
                    </div>
                    <div class="section">
                        <div class="label">Serving Alcohol</div>
                        <div>
                            <span class="badge {"badge-yes" if event_details.get("serving_alcohol") else "badge-no"}">
                                {"Yes" if event_details.get("serving_alcohol") else "No"}
                            </span>
                        </div>
                    </div>
                </div>

                <div class="section" style="margin-top: 15px;">
                    <div class="label">Who is Attending</div>
                    <div class="value">{event_details.get("who_is_attending")}</div>
                </div>

                <div class="section" style="margin-top: 15px;">
                    <div class="label">Additional Comments/Questions</div>
                    <div class="value" style="white-space: pre-wrap;">{event_details.get("additional_comments", "None")}</div>
                </div>
            </div>
        </body>
        </html>
        """

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 800, "height": 750})
            await page.set_content(html_content)
            screenshot_bytes = await page.screenshot(full_page=True)
            await browser.close()

        # Return a simulated workflow session ID
        return "mock_session_98765", screenshot_bytes

    # --- Real Mode ---
    async with async_playwright() as p:
        browser, context = await get_browser_context(p, cookies)
        page = await context.new_page()
        try:
            await _fill_25live_form_on_page(page, event_details)

            # Dismiss any popup/alert modal (e.g. passing period reminder or notification)
            for _ in range(2):
                alert_ok = await page.query_selector(
                    "div[role='alertdialog'] button:has-text('OK'), div.modal button:has-text('OK'), button:text-is('OK')"
                )
                if alert_ok and await alert_ok.is_visible():
                    try:
                        await alert_ok.click()
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass

            # Click Preview button to trigger preview modal
            preview_btn = await page.query_selector(
                "button:has-text('Preview'), button:has-text('Summary')"
            )
            if preview_btn:
                try:
                    await preview_btn.click()
                    await asyncio.sleep(2)
                except Exception:
                    pass

            screenshot_bytes = await page.screenshot(full_page=True)

            # Store the state/browser session context by saving session data to a temporary file
            temp_state_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=".json", mode="w", encoding="utf-8"
            )
            json.dump(
                {"cookies": cookies, "event_details": event_details},
                temp_state_file,
            )
            temp_state_file.close()
            session_id_context = temp_state_file.name

            return session_id_context, screenshot_bytes
        except Exception as e:
            current_url = page.url.lower() if page else ""
            if any(k in current_url for k in ["auth.ucr.edu", "sso.ucr.edu", "shibboleth", "cas/login", "login", "saml"]):
                raise RuntimeError(
                    "UCR session has expired or cookies are invalid. Re-authentication is required."
                ) from e
            raise RuntimeError(
                f"Playwright Event Wizard automation failed: {e!s}"
            ) from e
        finally:
            await browser.close()


async def _fill_25live_form_on_page(page, event_details: dict[str, Any]) -> None:
    """Fills the 25Live Event Form with all provided event details."""
    await page.goto(
        "https://25live.collegenet.com/pro/ucr#!/home/event/form",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    current_url = page.url.lower()
    if any(k in current_url for k in ["auth.ucr.edu", "sso.ucr.edu", "shibboleth", "cas/login", "login", "saml"]):
        raise RuntimeError(
            "UCR session has expired or cookies are invalid. Re-authentication is required."
        )

    name_selector = (
        "input[aria-label*='Event Name'], #ngEventFormItem-1, input[name*='eventName']"
    )
    try:
        await page.wait_for_selector(name_selector, timeout=15000)
    except Exception:
        create_btn = await page.query_selector(
            "button#My25Live_btnScheduleEvent, button:has-text('Create an Event'), a:has-text('Event Form')"
        )
        if create_btn:
            await create_btn.click()
            await page.wait_for_selector(name_selector, timeout=20000)
        else:
            await page.wait_for_selector(name_selector, timeout=15000)

    # Pre-fetch user's Starred Locations via 25Live internal API
    starred_locations: list[dict[str, Any]] = []
    try:
        starred_locations = await page.evaluate("""async () => {
            try {
                const r = await fetch('/25live/data/ucr/run/spaces.json?scope=extended&favorite=T&caller=pro-Starred');
                const j = await r.json();
                return (j.spaces?.space || []).map(s => ({
                    space_id: s.space_id,
                    space_name: s.space_name || s.name,
                    formal_name: s.formal_name || '',
                    building_name: s.building_name || '',
                    max_capacity: s.max_capacity
                }));
            } catch(e) {
                return [];
            }
        }""")
    except Exception as e:
        print(f"Notice: Could not fetch starred locations: {e}")

    # 1. Event Name & Title
    name_val = event_details.get("event_name", "")
    await page.fill(name_selector, name_val)

    title_val = event_details.get("event_title") or name_val
    if title_val:
        title_selector = "input[aria-label*='Event Title'], #ngEventFormItem-2, input[name*='eventTitle']"
        try:
            await page.fill(title_selector, title_val)
        except Exception:
            pass

    # 2. Event Description (TinyMCE + Angular JQTE model binding)
    desc_val = event_details.get("event_description", "")
    if desc_val:
        try:
            await page.wait_for_function(
                "() => (window.tinymce && window.tinymce.activeEditor) || document.querySelector('textarea')",
                timeout=10000,
            )
            await page.evaluate(
                """(val) => {
                    const editor = window.tinymce && window.tinymce.activeEditor;
                    if (editor) {
                        editor.setContent('<p>' + val + '</p>');
                        editor.save();
                        if (typeof editor.fire === 'function') {
                            editor.fire('change');
                            editor.fire('input');
                            editor.fire('blur');
                        }
                    }
                    const ta = editor ? document.getElementById(editor.id) : document.querySelector("textarea[aria-label*='Text Box'], textarea[name*='description']");
                    if (ta) {
                        ta.value = val;
                        ta.dispatchEvent(new Event('input', {bubbles: true}));
                        ta.dispatchEvent(new Event('change', {bubbles: true}));
                        ta.dispatchEvent(new Event('blur', {bubbles: true}));
                        if (window.angular) {
                            const scope = window.angular.element(ta).scope();
                            if (scope && scope.JQTE) {
                                scope.JQTE.ngModel = val;
                                scope.JQTE.ariaInvalid = false;
                                if (typeof scope.JQTE.ngChange === 'function') {
                                    scope.JQTE.ngChange();
                                }
                                scope.$apply();
                            }
                        }
                    }
                }""",
                desc_val,
            )
        except Exception as e:
            print(f"Warning: Failed to set event description: {e}")

    # 3. Event Type (Angular UI-Select / Select2 dropdown)
    event_type = event_details.get("event_type")
    if event_type:
        try:
            type_choice = await page.wait_for_selector(
                "button[aria-label*='Event Type'] .select2-choice, button#ngDropdown_2005 .select2-choice, button#ngDropdown_2005",
                timeout=10000,
            )
            if type_choice:
                await type_choice.click()
                await asyncio.sleep(0.5)
                type_opt = await page.wait_for_selector(
                    f".select2-result-label:has-text('{event_type}'), .ui-select-choices-row:has-text('{event_type}')",
                    timeout=5000,
                )
                if type_opt:
                    await type_opt.click()
                    await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Warning: Failed to select event type '{event_type}': {e}")

    # 4. Primary Organization (Angular UI-Select / Select2 search dropdown)
    org = event_details.get("primary_organization")
    if org:
        org_selected = False
        try:
            org_selectors = [
                "button[aria-label*='Primary Department/Organization'] .select2-choice",
                "button#ngDropdown_2001 .select2-choice",
                "button[aria-label*='Primary Department/Organization']",
                "input[placeholder*='Search Organizations']",
                "div[aria-label*='Primary Department/Organization']",
                "#ngEventFormItem-4 .select2-choice",
                "button:has-text('Select from Organizations')",
            ]
            org_trigger = None
            for sel in org_selectors:
                try:
                    org_trigger = await page.wait_for_selector(sel, timeout=3000)
                    if org_trigger and await org_trigger.is_visible():
                        break
                except Exception:
                    continue

            if org_trigger:
                await org_trigger.click()
                await asyncio.sleep(0.5)

                org_input = await page.query_selector(
                    ".select2-drop-active input.select2-input, input.select2-input:visible, input[placeholder*='Search Organizations']"
                )
                if org_input:
                    await org_input.fill("")
                    await org_input.fill(org)
                    await asyncio.sleep(2.0)

                opt_selectors = [
                    f".select2-drop-active .select2-result-label:has-text('{org}')",
                    f".select2-drop-active .ui-select-choices-row:has-text('{org}')",
                    f".dropdown-menu li:has-text('{org}')",
                    f"div[role='option']:has-text('{org}')",
                    ".select2-drop-active .select2-result-label",
                    ".select2-drop-active .ui-select-choices-row",
                ]
                for o_sel in opt_selectors:
                    try:
                        matching_opt = await page.query_selector(o_sel)
                        if matching_opt and await matching_opt.is_visible():
                            await matching_opt.click()
                            await asyncio.sleep(0.5)
                            org_selected = True
                            break
                    except Exception:
                        continue

                if not org_selected and org_input:
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.5)
                    org_selected = True
        except Exception as e:
            print(f"Warning: Failed to select organization '{org}': {e}")

    # 5. Expected Attendance
    attendance = event_details.get("expected_attendance")
    if attendance:
        attendance_selector = "input[aria-label*='Expected Attendance'], #ngEventFormItem-8, input[name*='expectedAttendance']"
        try:
            await page.fill(attendance_selector, str(attendance))
        except Exception:
            pass

    # 6. Date and Time Pickers (with UCR passing period 10-min buffer rule)
    start_str = event_details.get("start_time")
    end_str = event_details.get("end_time")
    dt_start = None
    date_val = ""
    start_val = ""
    if start_str:
        try:
            dt_start = dt_parser.parse(str(start_str))
            date_val = dt_start.strftime("%m/%d/%Y")
            start_val = dt_start.strftime("%I:%M %p").lower().lstrip("0")

            date_inp = await page.query_selector(
                "input#date-1, input[name='dp'], input[aria-label='Date'], input[aria-label*='datetime input']"
            )
            if date_inp:
                await date_inp.fill(date_val)
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.5)

            start_inp = await page.query_selector(
                "input#startTimePicker, input[aria-label='Start Time']"
            )
            if start_inp:
                await start_inp.fill(start_val)
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.5)

            if end_str:
                dt_end = dt_parser.parse(str(end_str))
                # UCR Passing Period Rule: Classroom events must end at :20 or :50
                if dt_end.minute == 0:
                    dt_end = dt_end.replace(minute=50) - datetime.timedelta(hours=1)
                elif dt_end.minute == 30:
                    dt_end = dt_end.replace(minute=20)
                end_val = dt_end.strftime("%I:%M %p").lower().lstrip("0")
                end_inp = await page.query_selector(
                    "input#endTimePicker, input[aria-label='End Time']"
                )
                if end_inp:
                    await end_inp.fill(end_val)
                    await page.keyboard.press("Tab")
                    await asyncio.sleep(1.5)
        except Exception as e:
            print(f"Warning: Date/Time fill error: {e}")

    # 7. Location Search & Assignment
    # UCR 25Live requires a location to be assigned ("Locations - Required").
    # Step 7a: When Date & Time change, 25Live displays an "availability out of date" banner with a Refresh button.
    # We must wait for and click Refresh to un-hide the search interface and load room availability.
    try:
        for _ in range(8):
            refresh_btn = page.locator(
                "button.event-form-availability__refresh, button:text-is('Refresh')"
            )
            if await refresh_btn.count() > 0 and await refresh_btn.first.is_visible():
                await refresh_btn.first.click()
                await asyncio.sleep(2.5)
                break
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"Notice: Availability refresh check: {e}")

    # Scroll Locations section into view if needed
    try:
        loc_section = page.locator("s25-ng-object-search").first
        if await loc_section.count() > 0:
            await loc_section.scroll_into_view_if_needed()
    except Exception:
        pass

    assigned = False
    location = event_details.get("location")
    matched_starred = None
    resolved = None
    target_names: list[str] = []

    if location:
        resolved = resolve_location_alias(location)
        matched_starred = match_starred_location(location, starred_locations)

        if matched_starred:
            s_name = matched_starred.get("space_name") or matched_starred.get("name", "")
            f_name = matched_starred.get("formal_name", "")
            if s_name:
                target_names.append(s_name)
            if f_name and f_name != s_name:
                target_names.append(f_name)
            print(f"Location '{location}' matched in Starred Locations: {s_name} ({f_name})")

        # Also add original string and resolved alias search terms
        for q in [location, *resolved.get("search_queries", [])]:
            if q and q not in target_names:
                target_names.append(q)

    # Step 7b: Prioritize Starred Locations in the currently displayed table
    if location and target_names:
        try:
            reserve_result = await page.evaluate(
                """(targets) => {
                const rows = Array.from(document.querySelectorAll('s25-ng-object-search tr, s25-ng-object-search .c-table--row, s25-ng-object-search [role="row"], tr, .c-table--row'));
                for (const r of rows) {
                    const text = r.innerText || "";
                    for (const target of targets) {
                        if (target && text.toLowerCase().includes(target.toLowerCase())) {
                            const btn = r.querySelector('button.reserve-button, button.aw-button--success, button');
                            if (btn) {
                                const bText = btn.innerText.trim().toLowerCase();
                                if (bText === 'reserve' || bText === 'request') {
                                    btn.click();
                                    return { found: true, text: text.slice(0, 100) };
                                } else if (bText === 'unavailable') {
                                    return { found: false, unavailable: true, text: text.slice(0, 100) };
                                }
                            }
                        }
                    }
                }
                return { found: false };
            }""",
                target_names,
            )
            if reserve_result.get("found"):
                assigned = True
                await asyncio.sleep(2.0)
        except Exception as e:
            print(f"Notice: Initial table check for '{location}': {e}")

    # Step 7c: If not found in current table, perform a direct text search using resolved queries
    if location and not assigned:
        for query in target_names[:2]:  # Try primary target names
            try:
                reset_btn = page.locator("s25-ng-object-search button:text-is('Reset')")
                if await reset_btn.count() > 0 and await reset_btn.first.is_visible():
                    await reset_btn.first.click()
                    await asyncio.sleep(1.0)

                loc_input = page.locator(
                    "s25-ng-object-search textarea[aria-label='Search Locations'], s25-ng-object-search textarea.searchInput, textarea.searchInput"
                )
                if await loc_input.count() > 0 and await loc_input.first.is_visible():
                    await loc_input.first.fill(query)
                    search_btn = page.locator(
                        "s25-ng-object-search button.aw-button--primary:has-text('Search'), s25-ng-object-search button:has-text('Search')"
                    )
                    if await search_btn.count() > 0:
                        await search_btn.first.click()
                        await asyncio.sleep(4.0)

                    direct_reserve = await page.evaluate(
                        """(targets) => {
                            const rows = Array.from(document.querySelectorAll('s25-ng-object-search tr, s25-ng-object-search .c-table--row, s25-ng-object-search [role="row"], tr, .c-table--row'));
                            const debugInfo = [];
                            let reserved = false;
                            for (const r of rows) {
                                const text = r.innerText || "";
                                const btns = Array.from(r.querySelectorAll('button')).map(b => b.innerText.trim());
                                if (text.trim()) {
                                    debugInfo.push({ text: text.slice(0, 100), btns });
                                }
                                for (const target of targets) {
                                    if (!target || text.toLowerCase().includes(target.toLowerCase())) {
                                        const btn = r.querySelector('button.reserve-button, button.aw-button--success, button');
                                        if (btn) {
                                            const bText = btn.innerText.trim().toLowerCase();
                                            if (bText === 'reserve' || bText === 'request') {
                                                btn.click();
                                                reserved = true;
                                                break;
                                            }
                                        }
                                    }
                                }
                                if (reserved) break;
                            }
                            return { reserved, debugInfo };
                        }""",
                        target_names,
                    )
                    if direct_reserve.get("reserved"):
                        assigned = True
                        await asyncio.sleep(2.0)
                        break
            except Exception as e:
                print(f"Notice: Direct search for query '{query}' did not reserve: {e}")

    # Step 7d: Fallback if not assigned
    if not assigned:
        try:
            # First, check if any Reserve button is currently visible in the results table
            any_reserve = await page.evaluate(
                """() => {
                const btns = Array.from(document.querySelectorAll('s25-ng-object-search button.reserve-button, button.reserve-button, s25-ng-object-search button.aw-button--success'));
                const r = btns.find(b => b.innerText.trim().toLowerCase() === 'reserve');
                if (r) {
                    r.click();
                    return true;
                }
                return false;
            }"""
            )
            if any_reserve:
                assigned = True
                await asyncio.sleep(2.0)
            else:
                # Clear textarea before querying Saved Searches
                clear_btn = page.locator(
                    "s25-ng-object-search button.clear, s25-ng-object-search button[aria-label='Clear text']"
                )
                if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                    await clear_btn.first.click()
                    await asyncio.sleep(0.5)
                else:
                    await page.evaluate(
                        """() => {
                        const ta = document.querySelector("s25-ng-object-search textarea");
                        if (ta) {
                            ta.value = "";
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                            ta.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }"""
                    )

                # Select Saved Searches: Specifically select "General Assignment Classrooms (All)"
                saved_btn = await page.wait_for_selector(
                    "button#ngDropdown_2007, button[aria-label*='Saved location searches']",
                    timeout=10000,
                )
                if saved_btn:
                    await saved_btn.click()
                    await asyncio.sleep(0.5)

                    # Look for General Assignment Classrooms (All)
                    saved_opt = await page.wait_for_selector(
                        ".select2-drop-active li:has-text('General Assignment Classrooms (All)')",
                        timeout=5000,
                    )
                    if saved_opt:
                        await saved_opt.click()
                        await asyncio.sleep(1.0)

                        search_btn = page.locator(
                            "s25-ng-object-search button.aw-button--primary:has-text('Search'), s25-ng-object-search button:has-text('Search')"
                        )
                        if await search_btn.count() > 0:
                            await search_btn.first.click()
                            await asyncio.sleep(4.0)

                        fallback_reserve = await page.evaluate(
                            """() => {
                            const btns = Array.from(document.querySelectorAll('s25-ng-object-search button.reserve-button, button.reserve-button, s25-ng-object-search button.aw-button--success'));
                            const r = btns.find(b => b.innerText.trim().toLowerCase() === 'reserve');
                            if (r) {
                                r.click();
                                return true;
                            }
                            return false;
                        }"""
                        )
                        if fallback_reserve:
                            assigned = True
                            await asyncio.sleep(2.0)
        except Exception as e:
            print(f"Warning: Fallback room reservation error: {e}")

    if not assigned:
        # Policy diagnosis: Check if event falls during UCR Registrar Weeks 1-2 lock
        is_weeks_1_2 = False
        if dt_start:
            # Fall 2026 instruction begins Sep 24, 2026. Weeks 1-2 lock ends Friday, Oct 9, 2026.
            start_date_obj = dt_start.date()
            if datetime.date(2026, 9, 24) <= start_date_obj <= datetime.date(2026, 10, 11):
                is_weeks_1_2 = True

        if is_weeks_1_2:
            raise RuntimeError(
                f"Could not reserve '{location}'. UCR campus policy restricts student organization reservations for General Assignment Classrooms during Weeks 1-2 of Fall Quarter (Sept 24 - Oct 9, 2026) while student enrollment is finalized. Reservations for general assignment classrooms open starting Week 3 (Monday, October 12, 2026)."
            )

        raise RuntimeError(
            f"Could not reserve an available classroom in 25Live for '{location}' on {date_val} at {start_val}. All queried classrooms were either occupied or unavailable."
        )

    # 8. Additional Event Information (Required Classroom Custom Attributes)
    # When a classroom is reserved, 25Live adds required fields:
    # 8a. Food & Beverage Policy Acknowledgement: must be set to 'Yes'
    # 8b. Materials list: must be provided
    try:
        await page.evaluate("""() => {
            const allItems = Array.from(document.querySelectorAll('.rose-form--item, fieldset, div'));

            // 8a. Food & Beverage acknowledgement
            const fbItem = allItems.find(el => {
                const t = el.innerText || "";
                return t.includes("food and beverage") && t.includes("not permitted");
            });
            if (fbItem) {
                const yesLabel = fbItem.querySelector('.toggle__label--2') ||
                                 Array.from(fbItem.querySelectorAll('label')).find(l => l.innerText.trim() === 'Yes');
                if (yesLabel) yesLabel.click();
                const yesRadio = fbItem.querySelector('input.toggle__radio--2') ||
                                 fbItem.querySelectorAll('input[type="radio"]')[1];
                if (yesRadio && !yesRadio.checked) yesRadio.click();
            }

            // 8b. Materials input
            const matItem = allItems.find(el => {
                const t = el.innerText || "";
                return t.includes("materials/supplies") && t.includes("list of materials");
            });
            if (matItem) {
                const inp = matItem.querySelector('input, textarea');
                if (inp) {
                    inp.value = "None (Laptop and presentation materials)";
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                    inp.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
        }""")
    except Exception as e:
        print(f"Warning: Could not set custom attributes: {e}")

    # 9. Additional Comments & AV Requirements
    comments = []
    if (
        event_details.get("audiovisual_requirements")
        and str(event_details.get("audiovisual_requirements")).lower() != "none"
    ):
        comments.append(f"AV Requirements: {event_details['audiovisual_requirements']}")
    if (
        event_details.get("additional_comments")
        and str(event_details.get("additional_comments")).lower() != "none"
    ):
        comments.append(str(event_details["additional_comments"]))

    if comments:
        comments_selector = "textarea[aria-label*='Additional Comments'], #ngEventFormItem-13, textarea[name*='additionalComments']"
        try:
            comments_inp = await page.query_selector(comments_selector)
            if comments_inp:
                await comments_inp.fill("\n".join(comments))
        except Exception:
            pass

    # 10. Terms Agreement Checkbox
    try:
        await page.evaluate("""() => {
            const chk = document.querySelector("input#ngCheckboxPro1-");
            if (chk && !chk.checked) {
                chk.click();
            }
        }""")
    except Exception:
        pass


async def confirm_booking(session_id_context: str) -> str:
    """Submits the final reservation. Session ID context contains the saved state or handles mock."""
    if is_mock_mode():
        await asyncio.sleep(1.5)
        return "UCR-MOCK-987654"

    # --- Real Mode ---
    # Load session context from the temp file
    cookies = []
    event_details = {}
    if os.path.exists(session_id_context):
        try:
            with open(session_id_context, encoding="utf-8") as f:
                data = json.load(f)
                cookies = data.get("cookies", [])
                event_details = data.get("event_details", {})
        except Exception as e:
            print(f"Warning: could not read session context file: {e}")

    async with async_playwright() as p:
        browser, context = await get_browser_context(p, cookies)
        page = await context.new_page()
        try:
            # Fill form before saving
            if event_details:
                await _fill_25live_form_on_page(page, event_details)
            else:
                await page.goto(
                    "https://25live.collegenet.com/pro/ucr#!/home/event/form",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

            # Click REAL Save/Submit button (target the submission button wrapper, not Saved Searches)
            save_btn = await page.wait_for_selector(
                ".rose--submit-wrapper button:has-text('Save'), button[data-ng-click*='save']:has-text('Save'), button.aw-button--primary:text-is('Save')",
                timeout=15000,
            )
            await save_btn.click()
            await asyncio.sleep(2)

            # Handle and dismiss any alert dialogs (such as classroom policy or buffer time alerts)
            for _ in range(8):
                await asyncio.sleep(1)
                try:
                    alert_btn = await page.query_selector(
                        ".modal-content button:has-text('OK'), button:text-is('OK'), .modal-footer button:has-text('OK')"
                    )
                    if alert_btn and await alert_btn.is_visible():
                        await alert_btn.click()
                except Exception:
                    pass

            # Check for error banners or validation blocks on page
            error_selectors = [
                ".alert-danger",
                ".validation-error",
                ".field-validation-error",
                ".text-danger:visible",
                ".has-error .help-block",
                "div.toast-error",
                ".modal-content .text-danger",
            ]
            error_messages = []
            for sel in error_selectors:
                try:
                    elements = await page.query_selector_all(sel)
                    for el in elements:
                        if await el.is_visible():
                            txt = (await el.inner_text()).strip()
                            # Ignore non-error announcements (e.g. accessibility messages or success confirmations)
                            if (
                                txt
                                and not any(
                                    s in txt.lower()
                                    for s in ["added below", "has been added", "saved successfully"]
                                )
                                and txt not in error_messages
                            ):
                                error_messages.append(txt)
                except Exception:
                    pass

            # Wait for 25Live reference ID to appear (polling up to 30 seconds)
            reference_id = None
            for _ in range(30):
                # Check current URL for reference ID
                ref_from_url = extract_25live_reference(page.url)
                if ref_from_url:
                    reference_id = ref_from_url
                    break

                # Check page content for reference ID (e.g. 2026-ACFSPN)
                try:
                    content = await page.content()
                    ref_from_content = extract_25live_reference(content)
                    if ref_from_content:
                        reference_id = ref_from_content
                        break
                except Exception:
                    pass

                await asyncio.sleep(1)

            # Clean up the state file
            if os.path.exists(session_id_context):
                try:
                    os.remove(session_id_context)
                except OSError:
                    pass

            if not reference_id:
                err_detail = "; ".join(error_messages) if error_messages else ""
                error_msg = (
                    f"25Live reservation submission failed: {err_detail}"
                    if err_detail
                    else "25Live did not generate a valid reservation reference ID (e.g. 2026-XXXXXX). The submission may have encountered form validation errors or timed out."
                )
                raise RuntimeError(error_msg)

            return reference_id
        except Exception as e:
            raise RuntimeError(
                f"Playwright final reservation confirmation failed: {e!s}"
            ) from e
        finally:
            await browser.close()


async def get_user_organizations_from_25live(
    cookies: list[dict[str, Any]] | None,
) -> list[str]:
    """Fetches the list of organizations the user has access to from the 25Live dropdown."""
    if is_mock_mode():
        await asyncio.sleep(1.0)
        return ["R'LING", "Tartan Seoul"]

    # --- Real Mode ---
    async with async_playwright() as p:
        browser, context = await get_browser_context(p, cookies)
        page = await context.new_page()
        try:
            # Navigate to event form page
            await page.goto(
                "https://25live.collegenet.com/pro/ucr#!/home/event/form",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # Wait for the organization select dropdown to load
            selector = "button[aria-label*='Primary Department/Organization'] .select2-choice, input[placeholder*='Search Organizations']"
            await page.wait_for_selector(selector, timeout=15000)

            # Click to expand the dropdown
            await page.click(selector)
            await asyncio.sleep(1.5)  # Wait for dropdown items to populate

            # Extract the option texts. In 25Live, they are list items in a popup/dropdown.
            options = await page.evaluate(
                """() => {
                const items = Array.from(document.querySelectorAll('.dropdown-menu li, .select2-results__option, ul.ui-autocomplete li, .ui-menu-item, div[role="option"]'));
                return items.map(item => item.innerText ? item.innerText.trim() : "").filter(Boolean);
            }"""
            )

            if not options:
                options = await page.evaluate(
                    """() => {
                    const items = Array.from(document.querySelectorAll('ul li, ol li, .list-group-item'));
                    return items.map(item => item.innerText ? item.innerText.trim() : "").filter(Boolean);
                }"""
                )

            # Clean and filter the options
            cleaned_options = []
            for opt in options:
                # Remove extra noise, e.g. newlines, stars, etc.
                cleaned = opt.replace("\n", " ").strip()
                if cleaned and len(cleaned) < 100:
                    cleaned_options.append(cleaned)

            return (
                list(set(cleaned_options))
                if cleaned_options
                else ["R'LING", "Tartan Seoul"]
            )
        except Exception as e:
            print(f"Warning: Failed to fetch organizations from 25Live: {e!s}")
            return ["R'LING", "Tartan Seoul"]
        finally:
            await browser.close()


async def get_event_types_from_25live(
    cookies: list[dict[str, Any]] | None,
) -> list[str]:
    """Fetches the list of event types from the 25Live dropdown."""
    if is_mock_mode():
        await asyncio.sleep(1.0)
        return [
            "Academic Exam",
            "Banquet",
            "Camp",
            "Campus Visit/Tour",
            "Ceremony",
            "Clinic",
            "Conference",
            "Information Table",
            "Lecture",
            "Meeting",
            "Orientation",
            "Performance",
            "Reception",
            "Rehearsal",
            "Social Gatherings",
        ]

    # --- Real Mode ---
    async with async_playwright() as p:
        browser, context = await get_browser_context(p, cookies)
        page = await context.new_page()
        try:
            # Navigate to event form page
            await page.goto(
                "https://25live.collegenet.com/pro/ucr#!/home/event/form",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # Wait for and click the event type selector
            selector = "button[aria-label*='Event Type'] .select2-choice, div[class*='eventType-select'], select[name*='eventType'], button:has-text('Select from Types')"
            await page.wait_for_selector(selector, timeout=15000)
            await page.click(selector)
            await asyncio.sleep(1.5)  # Wait for options to render

            # Scrape option texts
            options = await page.evaluate(
                """() => {
                const items = Array.from(document.querySelectorAll('.dropdown-menu li, .select2-results__option, ul.ui-autocomplete li, .ui-menu-item, div[role="option"]'));
                return items.map(item => item.innerText ? item.innerText.trim() : "").filter(Boolean);
            }"""
            )

            if not options:
                options = await page.evaluate(
                    """() => {
                    const items = Array.from(document.querySelectorAll('ul li, ol li, .list-group-item'));
                    return items.map(item => item.innerText ? item.innerText.trim() : "").filter(Boolean);
                }"""
                )

            # Clean and filter the options
            cleaned_options = []
            for opt in options:
                cleaned = opt.replace("\n", " ").strip()
                if cleaned and len(cleaned) < 100:
                    cleaned_options.append(cleaned)

            return (
                list(set(cleaned_options))
                if cleaned_options
                else [
                    "Academic Exam",
                    "Banquet",
                    "Camp",
                    "Campus Visit/Tour",
                    "Ceremony",
                    "Clinic",
                    "Conference",
                    "Information Table",
                    "Lecture",
                    "Meeting",
                    "Orientation",
                    "Performance",
                    "Reception",
                    "Rehearsal",
                    "Social Gatherings",
                ]
            )
        except Exception as e:
            print(f"Warning: Failed to fetch event types from 25Live: {e!s}")
            return [
                "Academic Exam",
                "Banquet",
                "Camp",
                "Campus Visit/Tour",
                "Ceremony",
                "Clinic",
                "Conference",
                "Information Table",
                "Lecture",
                "Meeting",
                "Orientation",
                "Performance",
                "Reception",
                "Rehearsal",
                "Social Gatherings",
            ]
        finally:
            await browser.close()
