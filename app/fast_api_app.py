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
import contextlib
import json
import os
import sys
from collections.abc import AsyncIterator
from typing import Any

import google.auth
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.cloud import logging as google_cloud_logging
from pydantic import BaseModel

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.typing import Feedback
from app.booking import is_mock_mode
from app.db import get_session, save_session
from app.security import validate_discord_id

load_dotenv()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Ensure encryption key exists, set fallback for local prototyping/tests
if not os.getenv("COOKIE_ENCRYPTION_KEY"):
    os.environ["COOKIE_ENCRYPTION_KEY"] = "default_local_dev_secret_key_32_bytes"
    print(
        "WARNING: COOKIE_ENCRYPTION_KEY environment variable is missing. Set a fallback key.",
        file=sys.stderr,
    )

# Ensure Discord token exists or log warning
if not os.getenv("DISCORD_BOT_TOKEN"):
    print(
        "WARNING: DISCORD_BOT_TOKEN environment variable is not set. Discord bot will not start.",
        file=sys.stderr,
    )

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )

    # Initialize Discord bot background task if token exists
    discord_task = None
    if os.getenv("DISCORD_BOT_TOKEN"):
        try:
            from app.discord_bot import start_discord_bot

            discord_task = asyncio.create_task(start_discord_bot())
            app.state.discord_task = discord_task
            print("Discord bot background task started.")
        except Exception as e:
            print(f"Failed to start Discord bot: {e!s}", file=sys.stderr)

    yield

    # Clean up Discord bot task on shutdown
    if discord_task:
        discord_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await discord_task
        print("Discord bot background task stopped.")


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=True,
    lifespan=lifespan,
)
app.title = "ucr-scheduler"
app.description = "API for UCR 25Live event scheduling bot"


# --- Authentication Gateway Endpoints ---


def parse_cookie_input(raw: str) -> list[dict[str, Any]]:
    """Parses raw cookie data in JSON array, JSON dict, or header key=value; format."""
    raw = raw.strip()
    if not raw:
        raise ValueError("Cookie data cannot be empty")

    # 1. Try parsing JSON array
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                cookies = []
                for item in data:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        cookies.append(
                            {
                                "name": str(item["name"]),
                                "value": str(item["value"]),
                                "domain": str(
                                    item.get("domain", "25live.collegenet.com")
                                ),
                                "path": str(item.get("path", "/")),
                            }
                        )
                if cookies:
                    return cookies
        except Exception:
            pass

    # 2. Try parsing JSON dict
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                cookies = []
                for k, v in data.items():
                    cookies.append(
                        {
                            "name": str(k),
                            "value": str(v),
                            "domain": "25live.collegenet.com",
                            "path": "/",
                        }
                    )
                if cookies:
                    return cookies
        except Exception:
            pass

    # 3. Try parsing key=value; string
    cookies = []
    pairs = raw.split(";")
    for pair in pairs:
        if "=" in pair:
            name, val = pair.split("=", 1)
            name = name.strip()
            val = val.strip()
            if name and val:
                cookies.append(
                    {
                        "name": name,
                        "value": val,
                        "domain": "25live.collegenet.com",
                        "path": "/",
                    }
                )
    if cookies:
        return cookies

    # 4. If raw string is a bare token or cookie value (e.g. copied from DevTools)
    clean_val = raw.strip().strip('"').strip("'")
    if (
        clean_val
        and len(clean_val) >= 8
        and not any(c in clean_val for c in ["\n", "\r", "{", "}", " "])
    ):
        return [
            {
                "name": "WSSESSIONID",
                "value": clean_val,
                "domain": "25live.collegenet.com",
                "path": "/",
            }
        ]

    raise ValueError(
        "Invalid cookie format. Please paste JSON format (from Cookie-Editor), key=value; string, or your WSSESSIONID token."
    )


class StartLoginRequest(BaseModel):
    discord_id: str


class ImportCookiesRequest(BaseModel):
    discord_id: str
    cookies_data: str


_background_tasks: set[asyncio.Task] = set()


@app.post("/api/start_login")
async def api_start_login(req: StartLoginRequest):
    """Starts the Playwright interactive browser authentication in background."""
    try:
        clean_id = validate_discord_id(req.discord_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    from app.login_helper import perform_interactive_login

    task = asyncio.create_task(perform_interactive_login(clean_id, timeout_seconds=300))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started", "message": "Browser launch initiated."}


@app.get("/api/session_status")
async def api_session_status(discord_id: str):
    """Checks whether the user currently has an active, valid session."""
    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError:
        return {"authenticated": False, "count": 0}

    cookies = get_session(clean_id)
    return {"authenticated": bool(cookies), "count": len(cookies) if cookies else 0}


class CompleteLoginRequest(BaseModel):
    discord_id: str


@app.post("/api/complete_login")
async def api_complete_login(req: CompleteLoginRequest):
    """Signals an active interactive browser login to save cookies and finalize."""
    try:
        clean_id = validate_discord_id(req.discord_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    from app.login_helper import signal_login_complete

    signaled = signal_login_complete(clean_id)
    return {
        "status": "signaled" if signaled else "not_found",
        "message": "Signal sent to active login.",
    }


@app.post("/api/import_cookies")
async def api_import_cookies(req: ImportCookiesRequest):
    """Imports and encrypts raw cookies bound strictly to the given discord_id."""
    try:
        clean_id = validate_discord_id(req.discord_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        cookies = parse_cookie_input(req.cookies_data)
        save_session(clean_id, cookies)
        return {
            "status": "success",
            "count": len(cookies),
            "message": f"Successfully encrypted and saved {len(cookies)} cookies.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to process cookies: {e!s}"
        ) from e


@app.get("/login", response_class=HTMLResponse)
async def login_page(discord_id: str):
    """Interactive NetID Single Sign-On and session management gateway."""
    if not discord_id:
        raise HTTPException(status_code=400, detail="Missing discord_id")

    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError:
        clean_id = discord_id.strip()

    existing_cookies = get_session(clean_id)
    has_session = bool(existing_cookies)
    mock_mode = is_mock_mode()

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>UCR Single Sign-On & 25Live Gateway</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 20px;
                background: #f0f2f5;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .container {{
                max-width: 580px;
                width: 100%;
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                border-top: 6px solid #1a73e8;
            }}
            h2 {{ color: #1a73e8; margin-top: 0; }}
            .badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 12px;
                font-size: 13px;
                font-weight: bold;
            }}
            .badge-active {{ background: #e6f4ea; color: #137333; }}
            .badge-inactive {{ background: #fce8e6; color: #c5221f; }}
            .card-section {{
                border: 1px solid #dadce0;
                border-radius: 6px;
                padding: 16px;
                margin-top: 20px;
                background: #fafbfc;
            }}
            .card-section h3 {{ margin-top: 0; color: #202124; font-size: 16px; }}
            button {{
                background: #1a73e8;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-size: 15px;
                font-weight: 600;
                cursor: pointer;
                transition: background 0.2s;
            }}
            button:hover {{ background: #1557b0; }}
            button:disabled {{ background: #dadce0; cursor: not-allowed; }}
            textarea {{
                width: 100%;
                box-sizing: border-box;
                height: 80px;
                font-family: monospace;
                font-size: 12px;
                padding: 8px;
                border: 1px solid #dadce0;
                border-radius: 4px;
                margin-bottom: 10px;
            }}
            .security-box {{
                background: #e8f0fe;
                border-left: 4px solid #1a73e8;
                padding: 10px 14px;
                border-radius: 0 4px 4px 0;
                font-size: 13px;
                color: #174ea6;
                margin-top: 15px;
            }}
            .status-text {{
                font-size: 14px;
                margin-top: 10px;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>UCR Single Sign-On</h2>
            <p>Authenticating Discord User: <strong>{clean_id}</strong></p>
            <p>Status:
                <span id="sessionBadge" class="badge {
        "badge-active" if has_session else "badge-inactive"
    }">
                    {"✓ Session Active" if has_session else "⚠️ No Active Session"}
                </span>
            </p>

            <div class="security-box">
                🛡️ <strong>Zero Password Exposure</strong>: Keystrokes and passwords are typed directly into UCR's official Single Sign-On portal (<code>auth.ucr.edu</code>) and are never intercepted or stored. Session cookies are encrypted with AES-256-GCM AEAD bound to your Discord ID.
            </div>

            <!-- Option A: Interactive Browser Window -->
            <!-- Option 1: Interactive Browser Window -->
            <div class="card-section">
                <h3>Option 1: Launch Interactive Duo MFA Login</h3>
                <p style="font-size: 14px; color: #5f6368;">
                    Opens a dedicated Chromium window navigating directly to UCR SSO (<code>auth.ucr.edu</code>). Complete your NetID and Duo push there.
                </p>
                <button id="launchBtn" onclick="launchLogin()">🌐 Launch UCR Login Window</button>
                <div id="launchActions" style="display: none; margin-top: 14px;">
                    <div id="launchStatus" class="status-text" style="color: #1a73e8; margin-bottom: 10px;">
                        ⏳ <strong>Browser window launched!</strong> Check your desktop/taskbar for the Chromium login window, log in with NetID & approve Duo MFA.
                    </div>
                    <p style="font-size: 13px; color: #5f6368; margin-bottom: 8px;">
                        When you reach 25Live, your session will save automatically. If the window remains open, click:
                    </p>
                    <button id="completeBtn" onclick="completeLogin()" style="background: #137333;">✅ I Have Finished Duo MFA (Save Session)</button>
                </div>
            </div>

            <!-- Option 2: Direct 25Live Cookie Import -->
            <div class="card-section">
                <h3>Option 2: Direct 25Live Cookie Import (Instant)</h3>
                <p style="font-size: 14px; color: #5f6368;">
                    Already logged in to 25Live in your browser? You can paste your session directly:
                </p>
                <div style="background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 6px; padding: 12px; margin-bottom: 12px; font-size: 13px; color: #3c4043; line-height: 1.5;">
                    <a href="https://25live.collegenet.com/pro/ucr#!/home/dash" target="_blank" style="display: inline-block; margin-bottom: 8px; padding: 6px 12px; background: #e8f0fe; color: #1a73e8; border-radius: 4px; text-decoration: none; font-weight: bold; border: 1px solid #cce0ff;">↗️ Open UCR 25Live in New Tab</a><br>
                    <strong>Method A (Easiest - DevTools):</strong><br>
                    1. On the 25Live tab, press <code>F12</code> &rarr; click <strong>Application</strong> &rarr; <strong>Cookies</strong> &rarr; <code>25live.collegenet.com</code>.<br>
                    2. Double-click the <strong>Value</strong> of <code>WSSESSIONID</code>, copy it, and paste it below.<br>
                    <strong>Method B (Cookie-Editor):</strong><br>
                    1. With the Cookie-Editor extension on 25Live, click <em>Export &rarr; Export as JSON</em>.<br>
                    2. Paste the JSON below and click <strong>Save & Encrypt Cookies</strong>.
                </div>
                <textarea id="cookiesInput" placeholder="Paste WSSESSIONID value (e.g. s%3A...) or full Cookie-Editor JSON here"></textarea>
                <button onclick="importCookies()">💾 Save & Encrypt Cookies</button>
                <div id="importStatus" class="status-text"></div>
            </div>

            <!-- Option C: Mock login for dev/testing -->
            {
        f'''
            <div class="card-section" style="background: #fff8e1; border-color: #ffe082;">
                <h3 style="color: #f57f17;">Developer Mock Mode</h3>
                <p style="font-size: 13px; color: #5f6368;">Simulate an authenticated session without live UCR credentials:</p>
                <form action="/capture" method="get">
                    <input type="hidden" name="discord_id" value="{clean_id}">
                    <button type="submit" style="background: #f57f17;">Complete Mock Login</button>
                </form>
            </div>
            '''
        if mock_mode
        else ""
    }
        </div>

        <script>
            const discordId = "{clean_id}";
            let pollTimer = null;

            async function checkStatus() {{
                try {{
                    const res = await fetch(`/api/session_status?discord_id=${{discordId}}`);
                    const data = await res.json();
                    if (data.authenticated) {{
                        document.getElementById("sessionBadge").className = "badge badge-active";
                        document.getElementById("sessionBadge").innerText = `✓ Session Active (${{data.count}} cookies)`;
                        const statusEl = document.getElementById("launchStatus");
                        if (statusEl) {{
                            statusEl.innerHTML = "🎉 <strong>Authentication Successful!</strong> Session saved. You can now return to Discord and run <code>/schedule</code>.";
                            statusEl.style.color = "#137333";
                        }}
                        const completeBtn = document.getElementById("completeBtn");
                        if (completeBtn) completeBtn.style.display = "none";
                        if (pollTimer) clearInterval(pollTimer);
                    }}
                }} catch (e) {{
                    console.error("Status check failed", e);
                }}
            }}

            async function launchLogin() {{
                const btn = document.getElementById("launchBtn");
                const actions = document.getElementById("launchActions");
                const status = document.getElementById("launchStatus");
                btn.disabled = true;
                actions.style.display = "block";
                status.style.color = "#1a73e8";
                status.innerHTML = "⏳ <strong>Browser launched!</strong> Check your taskbar/desktop for the Chromium window, log in with NetID & approve Duo MFA. Once at 25Live, return here.";

                try {{
                    await fetch('/api/start_login', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ discord_id: discordId }})
                    }});
                    // Start polling
                    pollTimer = setInterval(checkStatus, 2500);
                }} catch (e) {{
                    status.innerHTML = "❌ Failed to start login: " + e;
                    status.style.color = "#c5221f";
                    btn.disabled = false;
                }}
            }}

            async function completeLogin() {{
                const status = document.getElementById("launchStatus");
                status.innerHTML = "⏳ Saving and encrypting session cookies...";
                try {{
                    await fetch('/api/complete_login', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ discord_id: discordId }})
                    }});
                    setTimeout(checkStatus, 1000);
                }} catch (e) {{
                    status.innerHTML = "❌ Error signaling completion: " + e;
                    status.style.color = "#c5221f";
                }}
            }}

            async function importCookies() {{
                const text = document.getElementById("cookiesInput").value;
                const status = document.getElementById("importStatus");
                if (!text.trim()) {{
                    status.innerText = "Please paste cookie data first.";
                    status.style.color = "#c5221f";
                    return;
                }}
                try {{
                    const res = await fetch('/api/import_cookies', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ discord_id: discordId, cookies_data: text }})
                    }});
                    const data = await res.json();
                    if (res.ok) {{
                        status.innerText = `✓ Success: ${{data.count}} cookies encrypted and saved!`;
                        status.style.color = "#137333";
                        checkStatus();
                    }} else {{
                        status.innerText = "Error: " + (data.detail || "Invalid format");
                        status.style.color = "#c5221f";
                    }}
                }} catch (e) {{
                    status.innerText = "Network error: " + e;
                    status.style.color = "#c5221f";
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html


@app.get("/capture", response_class=HTMLResponse)
async def capture_cookies(discord_id: str):
    """Callback page that intercepts cookies, encrypts, and stores them in SQLite."""
    if not discord_id:
        raise HTTPException(status_code=400, detail="Missing discord_id")

    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Generate mock cookies mimicking UCR SSO and 25Live session cookies
    mock_cookies = [
        {
            "name": "WSSESSIONID",
            "value": f"mock_session_{clean_id}_xyz123",
            "domain": "25live.collegenet.com",
            "path": "/",
        },
        {
            "name": "_shibsession_ucr",
            "value": f"mock_shibsession_{clean_id}_abc456",
            "domain": ".ucr.edu",
            "path": "/",
        },
    ]

    try:
        save_session(clean_id, mock_cookies)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to encrypt and save session: {e!s}"
        ) from e

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authentication Successful</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #e6f4ea; }
            .card { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); text-align: center; border-top: 6px solid #137333; max-width: 400px; }
            h2 { color: #137333; margin-top: 0; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>✓ Authentication Successful</h2>
            <p>Your UCR 25Live session cookies have been securely encrypted and cached.</p>
            <p>You can close this window now and return to Discord.</p>
        </div>
    </body>
    </html>
    """
    return html


class SelectedTimeRequest(BaseModel):
    discord_id: str
    start_time: str
    end_time: str


@app.get("/select_time", response_class=HTMLResponse)
async def select_time_page(discord_id: str):
    """Serves the interactive drag-and-drop calendar page for date/time selection."""
    if not discord_id:
        raise HTTPException(status_code=400, detail="Missing discord_id")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Select Event Date & Time</title>
        <meta charset="utf-8" />
        <link href="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.css" rel="stylesheet" />
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.js"></script>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 20px;
                background: #f0f2f5;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .container {{
                max-width: 900px;
                width: 100%;
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                border-top: 6px solid #1a73e8;
            }}
            h2 {{
                color: #1a73e8;
                text-align: center;
                margin-top: 0;
            }}
            p {{
                text-align: center;
                color: #5f6368;
                margin-bottom: 20px;
            }}
            #calendar {{
                margin-bottom: 20px;
            }}
            .btn-container {{
                display: flex;
                justify-content: center;
                gap: 15px;
            }}
            button {{
                background: #1a73e8;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 4px;
                font-size: 16px;
                cursor: pointer;
                font-weight: bold;
            }}
            button:disabled {{
                background: #ccc;
                cursor: not-allowed;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Select Event Date & Time</h2>
            <p>Click and drag across the calendar grid to select your desired start and end times.</p>
            <div id="calendar"></div>
            <div class="btn-container">
                <button id="submitBtn" disabled>Confirm Selected Time</button>
            </div>
        </div>

        <script>
            let selectedStart = null;
            let selectedEnd = null;

            document.addEventListener('DOMContentLoaded', function() {{
                var calendarEl = document.getElementById('calendar');
                var calendar = new FullCalendar.Calendar(calendarEl, {{
                    initialView: 'timeGridWeek',
                    selectable: true,
                    selectMirror: true,
                    allDaySlot: false,
                    slotMinTime: '07:00:00',
                    slotMaxTime: '22:00:00',
                    headerToolbar: {{
                        left: 'prev,next today',
                        center: 'title',
                        right: 'timeGridWeek,timeGridDay'
                    }},
                    select: function(info) {{
                        selectedStart = info.startStr;
                        selectedEnd = info.endStr;
                        document.getElementById('submitBtn').disabled = false;
                    }},
                    unselect: function() {{
                        selectedStart = null;
                        selectedEnd = null;
                        document.getElementById('submitBtn').disabled = true;
                    }}
                }});
                calendar.render();

                document.getElementById('submitBtn').addEventListener('click', function() {{
                    if (!selectedStart || !selectedEnd) return;

                    fetch('/save_selected_time', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify({{
                            discord_id: '{discord_id}',
                            start_time: selectedStart,
                            end_time: selectedEnd
                        }})
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        if (data.status === 'success') {{
                            document.body.innerHTML = `
                                <div class="container" style="text-align: center; margin-top: 50px; border-top: 6px solid #137333;">
                                    <h2 style="color: #137333;">✓ Time Selection Saved</h2>
                                    <p>Selected Range: <strong>${{new Date(selectedStart).toLocaleString()}}</strong> to <strong>${{new Date(selectedEnd).toLocaleString()}}</strong></p>
                                    <p>Closing this tab automatically...</p>
                                </div>
                            `;
                            setTimeout(() => {{
                                window.close();
                            }}, 1500);
                        }} else {{
                            alert('Failed to save time: ' + data.message);
                        }}
                    }})
                    .catch(err => {{
                        alert('Error: ' + err);
                    }});
                }});
            }});
        </script>
    </body>
    </html>
    """
    return html


@app.post("/save_selected_time")
async def save_selected_time_api(req: SelectedTimeRequest):
    """Endpoint that saves the drag-and-drop selected time range."""
    from app.db import save_selected_time

    try:
        save_selected_time(req.discord_id, req.start_time, req.end_time)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
