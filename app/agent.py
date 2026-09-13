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

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.booking import check_room_availability, confirm_booking, fill_25live_wizard
from app.db import get_session

MODEL = "gemini-3.6-flash"


async def check_room_availability_tool(
    discord_id: str, date: str, time: str, room_preference: str
) -> str:
    """Check if a room is available in UCR 25Live.

    Args:
        discord_id: The Discord user ID of the requester.
        date: The date to check (YYYY-MM-DD).
        time: The time to check (HH:MM).
        room_preference: The building and room name.

    Returns:
        A string message indicating availability or error status.
    """
    cookies = get_session(discord_id)
    if not cookies:
        return "ERROR: User is not authenticated. Please log in first."
    res = await check_room_availability(cookies, date, time, room_preference)
    return res["message"]


async def submit_25live_reservation_tool(
    discord_id: str,
    location: str,
    event_name: str,
    event_title: str,
    event_description: str,
    event_type: str,
    primary_organization: str,
    expected_attendance: int,
    start_time: str,
    end_time: str,
    audiovisual_requirements: str,
    serving_food: bool,
    serving_beverages: bool,
    serving_alcohol: bool,
    who_is_attending: str,
    additional_comments: str = "None",
) -> str:
    """Submit an event reservation to UCR 25Live.

    Args:
        discord_id: The Discord user ID of the requester.
        location: UCR building and room (e.g. WCH 205).
        event_name: Internal reference name of the event.
        event_title: Public-facing title for calendars.
        event_description: Detailed description of the event.
        event_type: Category of the event (e.g. Meeting).
        primary_organization: Sponsoring organization.
        expected_attendance: Headcount of attendees.
        start_time: Start date and time (YYYY-MM-DD HH:MM).
        end_time: End date and time (YYYY-MM-DD HH:MM).
        audiovisual_requirements: Required AV setup.
        serving_food: Whether food will be served (True/False).
        serving_beverages: Whether beverages will be served (True/False).
        serving_alcohol: Whether alcohol will be served (True/False).
        who_is_attending: Target audience description.
        additional_comments: Any additional instructions or comments.

    Returns:
        A string message containing the confirmation ID or error details.
    """
    cookies = get_session(discord_id)
    if not cookies:
        return "ERROR: User is not authenticated. Please log in first."

    details = {
        "location": location,
        "event_name": event_name,
        "event_title": event_title,
        "event_description": event_description,
        "event_type": event_type,
        "primary_organization": primary_organization,
        "expected_attendance": expected_attendance,
        "start_time": start_time,
        "end_time": end_time,
        "audiovisual_requirements": audiovisual_requirements,
        "serving_food": serving_food,
        "serving_beverages": serving_beverages,
        "serving_alcohol": serving_alcohol,
        "who_is_attending": who_is_attending,
        "additional_comments": additional_comments,
    }

    try:
        session_context, _ = await fill_25live_wizard(cookies, details)
        conf_id = await confirm_booking(session_context)
        return (
            f"SUCCESS: Reservation submitted successfully. Confirmation ID: {conf_id}"
        )
    except Exception as e:
        return f"ERROR: Failed to submit reservation: {e!s}"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are a helpful AI assistant designed to check room availability and book events on UCR's 25Live portal reserve.ucr.edu.",
    tools=[check_room_availability_tool, submit_25live_reservation_tool],
)

app = App(
    root_agent=root_agent,
    name="app",
)
