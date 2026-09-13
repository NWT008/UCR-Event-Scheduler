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

import io
import json
import os
import sys

import discord
from discord import app_commands

from app.booking import confirm_booking, fill_25live_wizard
from app.db import get_session
from app.security import (
    preprocess_user_input,
    validate_attendance,
    validate_boolean_choice,
    validate_datetime_str,
    validate_location,
    validate_organization,
)

# Define the 13 questions in order
QUESTIONS = [
    (
        "location",
        "1. Location: What building and room do you prefer? (e.g. Winston Chung Hall 205)",
    ),
    (
        "event_name",
        "2. Event Name & Title: What is the name/title of your event? (This will be used for both internal reference and published calendars)",
    ),
    (
        "event_description",
        "3. Event Description: Please enter a detailed description of the event:",
    ),
    (
        "event_type",
        "4. Event Type: What category is the event? (e.g. Meeting, Seminar, Banquet)",
    ),
    (
        "primary_organization",
        "5. Sponsoring Organization: Which student group or department is organizing this?",
    ),
    (
        "expected_attendance",
        "6. Expected Attendance: How many headcount/attendees are you expecting?",
    ),
    (
        "start_time",
        "7. Start Date & Time: When does the event start? (e.g. January 4 2026 6 pm or Jan 4 2026 6:30 am)",
    ),
    (
        "end_time",
        "8. End Date & Time: When does the event end? (e.g. January 4 2026 8 pm or Jan 4 2026 7:30 am, must be after the start time)",
    ),
    (
        "audiovisual_requirements",
        "9. AV Requirements: What AV equipment is needed? (e.g. Projector, Microphone, or 'None')",
    ),
    ("serving_food", "10. Serving Food? (Answer Yes/No)"),
    ("serving_beverages", "11. Serving Beverages? (Answer Yes/No)"),
    (
        "who_is_attending",
        "12. Target Audience: Who is attending this event? (e.g. Students, Faculty, Public)",
    ),
    (
        "additional_comments",
        "13. Additional Comments/Questions: Please enter any additional instructions or event information for Room Managers and Event Approvers (or 'None'):",
    ),
]


class ConfirmBookingView(discord.ui.View):
    """View with green Confirm and red Cancel buttons for final booking submission."""

    def __init__(self, discord_id: str):
        super().__init__(timeout=180.0)
        self.discord_id = discord_id
        self.value = None

    @discord.ui.button(label="Confirm Booking", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message(
                "Only the user who initiated scheduling can confirm.", ephemeral=True
            )
            return
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message(
                "Only the user who initiated scheduling can cancel.", ephemeral=True
            )
            return
        self.value = False
        await interaction.response.defer()
        self.stop()


class SessionState:
    """Manages the state of a single user's booking questionnaire in a channel."""

    def __init__(self, channel: discord.TextChannel, user_id: str):
        self.channel = channel
        self.user_id = user_id
        self.current_step = 0
        self.answers = {}
        self.poll_task = None

    def cleanup(self):
        """Cancels any active background polling tasks."""
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()

    async def poll_time_selection(self):
        """Polls the database for a saved time selection for this user."""
        import asyncio

        from app.db import delete_selected_time, get_selected_time
        from app.security import validate_datetime_str

        # Poll every 2 seconds for up to 5 minutes (300 seconds)
        timeout = 300
        interval = 2.0
        elapsed = 0

        while elapsed < timeout:
            # Check if this session is still active and at the start_time step (index 6)
            key = (self.channel.id, self.user_id)
            if active_sessions.get(key) is not self or self.current_step != 6:
                return  # Session replaced/cancelled or progressed via manual typing

            time_sel = get_selected_time(self.user_id)
            if time_sel:
                start_str, end_str = time_sel
                try:
                    start_dt = validate_datetime_str(start_str)
                    end_dt = validate_datetime_str(end_str)

                    self.answers["start_time"] = start_dt
                    self.answers["end_time"] = end_dt
                    # Move past start_time (6) and end_time (7)
                    self.current_step = 8

                    await self.channel.send(
                        f"✅ **Time Selected via Calendar:** {start_dt.strftime('%Y-%m-%d %I:%M %p')} to {end_dt.strftime('%Y-%m-%d %I:%M %p')}"
                    )

                    delete_selected_time(self.user_id)
                    # Automatically proceed to next question
                    await self.ask_question()
                    return
                except Exception as e:
                    await self.channel.send(
                        f"⚠️ **Error parsing calendar time:** {e!s}. Please try again."
                    )
                    delete_selected_time(self.user_id)

            await asyncio.sleep(interval)
            elapsed += interval

    async def ask_question(self):
        """Sends the current step's question to the channel."""
        _, prompt = QUESTIONS[self.current_step]
        await self.channel.send(f"<@{self.user_id}> {prompt}")

    async def handle_message(self, message: discord.Message) -> bool:
        """Processes the user's answer to the current question.

        Returns:
            True if questionnaire is finished, False otherwise.
        """
        # Step 1: Preprocess user input (Prompt Injection Check + Redaction)
        raw_text = message.content
        sanitized = preprocess_user_input(raw_text)

        if sanitized == "INVALID INPUT: PROMPT INJECTION":
            await self.channel.send(
                f"❌ **Error:** {sanitized}. Conversation terminated."
            )
            return True

        # Step 2: Validate the current field value
        field_name, _ = QUESTIONS[self.current_step]
        validated_val = None

        try:
            if field_name == "expected_attendance":
                validated_val = validate_attendance(sanitized)
            elif field_name in ["serving_food", "serving_beverages", "serving_alcohol"]:
                validated_val = validate_boolean_choice(sanitized)
            elif field_name in ["start_time", "end_time"]:
                validated_val = validate_datetime_str(sanitized)
            elif field_name == "location":
                try:
                    validated_val = validate_location(sanitized)
                except ValueError as e:
                    # Not in local catalog. Let's do a live check!
                    await self.channel.send(
                        "⏳ *Room not found in local catalog. Verifying with live 25Live portal...*"
                    )
                    from app.booking import check_room_availability

                    # Fetch cookies
                    cookies = get_session(self.user_id)
                    live_res = await check_room_availability(
                        cookies=cookies,
                        date="2026-09-25",
                        time="3:00 pm",
                        room_preference=sanitized,
                    )
                    if live_res.get("status") == "success":
                        # Room exists! Let's save it to our local catalog
                        from app.security import load_resource

                        locs = load_resource("locations.json")
                        new_loc = sanitized.strip()
                        if len(new_loc) > 3 and not new_loc.isupper():
                            # Title case if not acronym
                            new_loc = new_loc.title()

                        if new_loc not in locs:
                            locs.append(new_loc)
                            resources_dir = os.path.join(
                                os.path.dirname(__file__),
                                "resources",
                            )
                            os.makedirs(resources_dir, exist_ok=True)
                            filepath = os.path.join(resources_dir, "locations.json")
                            with open(filepath, "w") as f:
                                json.dump(locs, f, indent=2)

                        validated_val = new_loc
                        await self.channel.send(
                            f"✅ *Verified! Added '{new_loc}' to local room directory.*"
                        )
                    else:
                        raise e
            elif field_name == "event_type":
                # Let's pull the live event types from 25Live portal and only validate against them
                await self.channel.send(
                    "⏳ *Verifying event type options with 25Live portal...*"
                )
                import difflib

                from app.booking import get_event_types_from_25live

                cookies = get_session(self.user_id)
                allowed_types = await get_event_types_from_25live(cookies)

                # Try to match the typed event type against the allowed types
                val_clean = sanitized.strip().lower()
                matched_type = None
                for t in allowed_types:
                    if t.lower() == val_clean:
                        matched_type = t
                        break

                if not matched_type:
                    matches = difflib.get_close_matches(
                        sanitized, allowed_types, n=1, cutoff=0.6
                    )
                    if matches:
                        matched_type = matches[0]

                if matched_type:
                    validated_val = matched_type
                    # Cache/update the local event_types.json list with the scraped allowed_types
                    from app.security import load_resource

                    resources_dir = os.path.join(
                        os.path.dirname(__file__),
                        "resources",
                    )
                    os.makedirs(resources_dir, exist_ok=True)
                    filepath = os.path.join(resources_dir, "event_types.json")
                    with open(filepath, "w") as f:
                        json.dump(allowed_types, f, indent=2)

                    await self.channel.send(
                        f"✅ *Verified! Match found: '{matched_type}'.*"
                    )
                else:
                    types_str = ", ".join(allowed_types[:10]) + (
                        ", ..." if len(allowed_types) > 10 else ""
                    )
                    raise ValueError(
                        f"'{sanitized}' is not a valid Event Type. "
                        f"Valid options include: {types_str}"
                    )
            elif field_name == "primary_organization":
                try:
                    validated_val = validate_organization(sanitized)
                except ValueError as e:
                    # If not in local catalog, let's pull from the 25Live site
                    await self.channel.send(
                        "⏳ *Organization not found in local directory. Pulling authorized organizations from your 25Live profile...*"
                    )
                    import difflib

                    from app.booking import get_user_organizations_from_25live

                    cookies = get_session(self.user_id)
                    user_orgs = await get_user_organizations_from_25live(cookies)

                    # Try to match the typed organization against the user's organizations
                    val_clean = sanitized.strip().lower()
                    matched_org = None
                    for org in user_orgs:
                        if org.lower() == val_clean:
                            matched_org = org
                            break

                    if not matched_org:
                        matches = difflib.get_close_matches(
                            sanitized, user_orgs, n=1, cutoff=0.5
                        )
                        if matches:
                            matched_org = matches[0]

                    if matched_org:
                        validated_val = matched_org
                        # Save it to organizations.json so it's cached/available locally
                        from app.security import load_resource

                        orgs = load_resource("organizations.json")
                        if matched_org not in orgs:
                            orgs.append(matched_org)
                            resources_dir = os.path.join(
                                os.path.dirname(__file__),
                                "resources",
                            )
                            os.makedirs(resources_dir, exist_ok=True)
                            filepath = os.path.join(resources_dir, "organizations.json")
                            with open(filepath, "w") as f:
                                json.dump(orgs, f, indent=2)

                        await self.channel.send(
                            f"✅ *Verified! Match found: '{matched_org}'. Added to local organization directory.*"
                        )
                    else:
                        # No match found in the user's authorized organizations either
                        if user_orgs:
                            orgs_str = ", ".join(user_orgs)
                            raise ValueError(
                                f"'{sanitized}' is not one of your authorized organizations. "
                                f"Your organizations are: {orgs_str}"
                            ) from e
                        else:
                            raise e
            elif field_name == "event_description":
                from app.security import clean_text_with_llm

                await self.channel.send(
                    "✨ *Refining and cleaning up event description wording...*"
                )
                event_name_ctx = self.answers.get("event_name")
                validated_val = await clean_text_with_llm(
                    sanitized, event_name=event_name_ctx
                )
            elif field_name == "additional_comments":
                from app.security import clean_text_with_llm

                await self.channel.send(
                    "✨ *Refining and cleaning up comments wording...*"
                )
                validated_val = await clean_text_with_llm(
                    sanitized, autocorrect_only=True
                )
            else:
                # Text fields
                validated_val = sanitized.strip()
                if not validated_val:
                    raise ValueError("This field cannot be empty.")
        except ValueError as e:
            error_msg = str(e) or "Invalid input format."
            await self.channel.send(
                f"⚠️ **Validation Failed:** {error_msg}. Please try again."
            )
            await self.ask_question()
            return False

        # Save validated answer
        self.answers[field_name] = validated_val
        if field_name == "event_name":
            self.answers["event_title"] = validated_val
        self.current_step += 1

        # Check if more questions remain
        if self.current_step < len(QUESTIONS):
            # If start_time was just set, we check if end_time needs to be validated against it later
            await self.ask_question()
            return False

        # All questions completed! Run validation on the complete model
        self.answers["serving_alcohol"] = False
        await self.channel.send(
            "🔄 **Questionnaire complete.** Validating inputs and generating 25Live booking preview..."
        )

        # Validate date, time, operating hours, and conflicts
        try:
            start = self.answers["start_time"]
            end = self.answers["end_time"]
            if end <= start:
                await self.channel.send(
                    "⚠️ **Validation Failed:** Event end time must be after the start time. Let's re-answer the End Time question."
                )
                self.current_step = 7  # end_time step
                await self.ask_question()
                return False

            # 1. Future Date Check
            import datetime

            now = datetime.datetime.now(datetime.UTC)
            start_tz = start
            if start_tz.tzinfo is None:
                start_tz = start_tz.replace(tzinfo=datetime.UTC)
            if start_tz < now:
                await self.channel.send(
                    "⚠️ **Validation Failed:** The start date/time must be in the future. Let's re-answer the Start Time question."
                )
                self.current_step = 6  # start_time step
                await self.ask_question()
                return False

            # 2. SRC Hours of Operation Check (6:00 AM - 12:00 AM)
            room = self.answers.get("location", "")
            if "src" in room.lower() or "student recreation center" in room.lower():
                is_valid = True
                if start.hour < 6:
                    is_valid = False

                if end.date() == start.date():
                    pass
                elif (end.date() - start.date()).days == 1:
                    if not (end.hour == 0 and end.minute == 0):
                        is_valid = False
                else:
                    is_valid = False

                if not is_valid:
                    await self.channel.send(
                        "⚠️ **Validation Failed:** The Student Recreation Center (SRC) is only open from **6:00 AM to 12:00 AM (midnight)**. Your requested time is outside hours of operation. Let's re-answer the Start Time question."
                    )
                    self.current_step = 6  # start_time step
                    await self.ask_question()
                    return False

            # 3. Live 25Live Calendar Conflict Checker
            await self.channel.send(
                "⏳ *Checking 25Live calendar for event conflicts and room availability...*"
            )
            from app.booking import check_room_availability

            cookies = get_session(self.user_id)
            avail_res = await check_room_availability(
                cookies=cookies,
                date=start.strftime("%Y-%m-%d"),
                time=start.strftime("%H:%M"),
                room_preference=room,
                end_time=end.strftime("%H:%M"),
            )

            if avail_res.get("status") != "success" or not avail_res.get("available"):
                if avail_res.get("reason") == "session_expired":
                    from app.db import delete_session

                    delete_session(self.user_id)
                    login_url = f"http://localhost:8000/login?discord_id={self.user_id}"
                    await self.channel.send(
                        f"⚠️ **Validation Failed:** UCR session has expired or cookies are invalid.\n"
                        f"Please click here to re-authenticate: [**Authenticate with UCR 25Live**]({login_url})"
                    )
                    return True  # Terminate session cleanly

                conflict_msg = avail_res.get(
                    "message", "The room has a conflict or is occupied."
                )
                await self.channel.send(
                    f"⚠️ **Validation Failed:** {conflict_msg} Let's re-answer the Start Time question."
                )
                self.current_step = 6  # start_time step
                await self.ask_question()
                return False

        except Exception as e:
            await self.channel.send(f"⚠️ **Validation Failed:** {e!s}")
            return True

        # Launch Playwright to fill out form and take preview screenshot
        try:
            cookies = get_session(self.user_id)
            # Format times as strings for visual HTML mock rendering
            display_details = self.answers.copy()
            display_details["start_time"] = start.strftime("%Y-%m-%d %I:%M %p")
            display_details["end_time"] = end.strftime("%Y-%m-%d %I:%M %p")

            session_context, screenshot_bytes = await fill_25live_wizard(
                cookies, display_details
            )

            # Send screenshot to channel
            file = discord.File(
                io.BytesIO(screenshot_bytes), filename="booking_preview.png"
            )
            await self.channel.send(
                content=f"<@{self.user_id}> here is your 25Live booking preview. Please review it carefully:",
                file=file,
            )

            # Send buttons view
            view = ConfirmBookingView(self.user_id)
            msg = await self.channel.send(
                "Ready to submit this booking request to UCR 25Live?", view=view
            )

            await view.wait()

            if view.value is True:
                await msg.edit(
                    content="⏳ **Submitting booking to UCR 25Live...**", view=None
                )
                try:
                    conf_id = await confirm_booking(session_context)
                    await self.channel.send(
                        f"✅ **Booking Successful!**\nConfirmation ID: `{conf_id}`\nView details: [UCR 25Live Dashboard](https://25live.collegenet.com/pro/ucr#!/home/dash)"
                    )
                except Exception as e:
                    await self.channel.send(
                        f"❌ **Booking Submission Failed:** {e!s}\n\n"
                        f"⚠️ Your reservation **was not created** in 25Live. Please check that the room is available, verify your account authorizations, and try running `/schedule` again."
                    )
            else:
                await msg.edit(
                    content="❌ **Booking Cancelled.** Session discarded.", view=None
                )

        except Exception as e:
            if any(
                k in str(e).lower()
                for k in ["session has expired", "re-authentication", "cookies are invalid"]
            ):
                from app.db import delete_session

                delete_session(self.user_id)
                login_url = f"http://localhost:8000/login?discord_id={self.user_id}"
                await self.channel.send(
                    f"⚠️ **Session Expired:** Your UCR 25Live authentication has expired.\n"
                    f"Please click here to log in and renew your session: [**Authenticate with UCR 25Live**]({login_url})"
                )
                return True

            await self.channel.send(
                f"❌ **Automation Error:** Failed to complete booking wizard: {e!s}"
            )

        return True


active_sessions = {}


class BookingBotClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Sync slash commands globally
        await self.tree.sync()
        print("Slash command tree synced.")


client = BookingBotClient()


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")


@client.tree.command(
    name="login",
    description="Get secure authentication link for UCR 25Live.",
)
async def login(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    login_url = f"http://localhost:8000/login?discord_id={user_id}"
    await interaction.response.send_message(
        f"🔒 **UCR 25Live Authentication Gateway**\n\n"
        f"Please click the link below to authenticate your session:\n"
        f"👉 [**Click Here to Authenticate**]({login_url})\n\n"
        f"*(Note: You will authenticate directly on UCR's official Single Sign-On and Duo MFA portal. Your password is never seen or stored by this bot.)*",
        ephemeral=True,
    )


@client.tree.command(
    name="schedule", description="Start event scheduling questionnaire for UCR 25Live."
)
async def schedule(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    cookies = get_session(user_id)

    if not cookies:
        # User not authenticated, send DM and message with clickable login link
        login_url = f"http://localhost:8000/login?discord_id={user_id}"
        dm_msg = (
            f"🔒 **Authentication Required for UCR 25Live**\n\n"
            f"To schedule space on the UCR 25Live portal, please authenticate your session using the link below:\n"
            f"👉 [**Click Here to Authenticate**]({login_url})\n\n"
            f"Once you have signed in and completed Duo MFA, run `/schedule` again in the channel."
        )
        try:
            await interaction.user.send(dm_msg)
            await interaction.response.send_message(
                f"🔒 **Authentication Required.** I've sent you your personal login link in DMs, or click here: [**Authenticate Now**]({login_url})",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"🔒 **Authentication Required.** Please click here to authenticate: [**Authenticate Now**]({login_url})",
                ephemeral=True,
            )
        return

    # Check if a session is already active in this channel for this user
    key = (interaction.channel.id, user_id)
    if key in active_sessions:
        await interaction.response.send_message(
            "You already have an active scheduling session in this channel.",
            ephemeral=True,
        )
        return

    # Start the questionnaire
    await interaction.response.send_message(
        "🏁 **Starting UCR 25Live Scheduling Bot...**", ephemeral=True
    )
    session = SessionState(interaction.channel, user_id)
    active_sessions[key] = session
    await session.ask_question()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    key = (message.channel.id, str(message.author.id))
    if key in active_sessions:
        session = active_sessions[key]
        # Run handle_message
        finished = await session.handle_message(message)
        if finished:
            session.cleanup()
            del active_sessions[key]


async def start_discord_bot():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print(
            "DISCORD_BOT_TOKEN not set. Discord bot client will not run.",
            file=sys.stderr,
        )
        return
    try:
        await client.start(token)
    except Exception as e:
        print(f"Error starting Discord bot: {e!s}", file=sys.stderr)


async def stop_discord_bot():
    if not client.is_closed():
        await client.close()
