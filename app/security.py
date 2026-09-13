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

import datetime
import difflib
import json
import os
import re
from typing import Any

from google.genai import Client
from pydantic import BaseModel, Field, field_validator, model_validator

# --- Component 1: Schema Validation ---


class EventBookingDetails(BaseModel):
    location: str = Field(..., min_length=2, description="Preferred building/room")
    event_name: str = Field(
        ..., min_length=2, description="Internal event reference name"
    )
    event_title: str = Field(
        ..., min_length=2, description="Public-facing event title for calendars"
    )
    event_description: str = Field(
        ..., min_length=5, description="Detailed event description"
    )
    event_type: str = Field(..., min_length=2, description="Category of the event")
    primary_organization: str = Field(
        ..., min_length=2, description="Sponsoring group or department"
    )
    expected_attendance: int = Field(..., gt=0, description="Expected headcount")
    start_time: datetime.datetime = Field(
        ..., description="Event starting date and time"
    )
    end_time: datetime.datetime = Field(..., description="Event ending date and time")
    audiovisual_requirements: str = Field(..., description="Needed equipment or 'None'")
    serving_food: bool = Field(..., description="Is food being served?")
    serving_beverages: bool = Field(..., description="Are beverages being served?")
    serving_alcohol: bool = Field(..., description="Is alcohol being served?")
    who_is_attending: str = Field(
        ..., min_length=2, description="Target audience description"
    )
    additional_comments: str = Field(
        "None", description="Additional instructions or comments"
    )

    @field_validator("start_time", mode="before")
    @classmethod
    def validate_start_time_in_future(cls, value: Any) -> Any:
        if isinstance(value, str):
            # Parse string datetimes
            try:
                dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as e:
                raise ValueError(
                    "Invalid start_time datetime format (use ISO 8601, e.g. YYYY-MM-DDTHH:MM:SS)"
                ) from e
        elif isinstance(value, datetime.datetime):
            dt = value
        else:
            return value

        # Make dt timezone aware if it's naive (default to UTC or local)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)

        now = datetime.datetime.now(datetime.UTC)
        if dt < now:
            raise ValueError("Event start time must be in the future")
        return dt

    @model_validator(mode="after")
    def validate_time_range(self) -> "EventBookingDetails":
        start = self.start_time
        end = self.end_time

        # Ensure end time is also a datetime (pydantic handles initial parsing)
        if not isinstance(start, datetime.datetime) or not isinstance(
            end, datetime.datetime
        ):
            return self

        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=datetime.UTC)

        if end <= start:
            raise ValueError("Event end time must be after the start time")
        return self


# --- Individual Field Validation Helpers ---


def validate_attendance(val: str) -> int:
    """Helper to validate headcount integer."""
    try:
        count = int(val)
        if count <= 0:
            raise ValueError()
        return count
    except ValueError as e:
        raise ValueError(
            "Expected attendance must be a positive number greater than 0"
        ) from e


def validate_boolean_choice(val: str) -> bool:
    """Helper to validate Yes/No choices."""
    normalized = val.strip().lower()
    if normalized in ["yes", "y", "true", "t", "1"]:
        return True
    elif normalized in ["no", "n", "false", "f", "0"]:
        return False
    else:
        raise ValueError("Please answer with 'Yes' or 'No'")


def validate_datetime_str(val: str) -> datetime.datetime:
    """Helper to parse and validate datetime string."""
    # Clean input: remove commas and normalize spaces
    val_clean = val.strip().replace(",", "")
    val_clean = re.sub(r"\s+", " ", val_clean)
    # Normalize am/pm to uppercase PM/AM
    val_clean = re.sub(
        r"\b(am|pm)\b", lambda m: m.group(0).upper(), val_clean, flags=re.IGNORECASE
    )
    # Ensure space before AM/PM if missing (e.g., 6pm -> 6 PM)
    val_clean = re.sub(r"(\d+)\s*(AM|PM)\b", r"\1 \2", val_clean)

    # Standard formats to try parsing
    formats = [
        # Full Month Name formats
        "%B %d %Y %I:%M %p",  # January 4 2026 6:30 AM
        "%B %d %Y %I %p",  # January 4 2026 6 PM
        "%B %d %Y %H:%M",  # January 4 2026 18:00
        # Abbreviated Month Name formats
        "%b %d %Y %I:%M %p",  # Jan 4 2026 6:30 AM
        "%b %d %Y %I %p",  # Jan 4 2026 6 PM
        "%b %d %Y %H:%M",  # Jan 4 2026 18:00
        # Numeric formats
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I %p",
        "%Y-%m-%dT%H:%M:%S",
        # Date only formats (default to 12:00 PM)
        "%B %d %Y",
        "%b %d %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]

    dt = None
    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(val_clean, fmt)
            break
        except ValueError:
            continue

    if dt is None:
        try:
            # Try fromisoformat as fallback
            dt = datetime.datetime.fromisoformat(val_clean.replace("Z", "+00:00"))
        except ValueError:
            pass

    if dt is None:
        raise ValueError(
            "Invalid date/time format. Please use formats like: January 4 2026 6 pm, Jan 4 2026 6:30 am, or YYYY-MM-DD HH:MM."
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)

    return dt


def load_resource(filename: str) -> list[str]:
    """Load resource JSON file lazily."""
    filepath = os.path.join(os.path.dirname(__file__), "resources", filename)
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


def match_dropdown_value(val: str, filename: str, field_name: str) -> str:
    """Matches a string to the closest value in a resource directory using difflib."""
    options = load_resource(filename)
    if not options:
        return val.strip()  # Fallback if resource file is missing

    val_clean = val.strip()
    # Case-insensitive exact match
    for opt in options:
        if opt.lower() == val_clean.lower():
            return opt

    # Fuzzy match
    matches = difflib.get_close_matches(val_clean, options, n=1, cutoff=0.5)
    if matches:
        return matches[0]

    # No match found, raise detailed ValueError with suggestions
    close_hints = difflib.get_close_matches(val_clean, options, n=3, cutoff=0.3)
    hint_msg = f" Did you mean one of: {', '.join(close_hints)}?" if close_hints else ""
    raise ValueError(f"'{val_clean}' is not a valid {field_name}.{hint_msg}")


def validate_location(val: str) -> str:
    """Validates and fuzzy matches locations with building code fidelity."""
    options = load_resource("locations.json")
    if not options:
        return val.strip()

    val_clean = val.strip()
    # 1. Exact case-insensitive match
    for opt in options:
        if opt.lower() == val_clean.lower():
            return opt

    # 2. Check special room aliases / resolved queries
    from app.building_aliases import resolve_location_alias
    resolved = resolve_location_alias(val_clean)
    b_code = resolved.get("building_code", "").strip().lower()
    formal_b = resolved.get("formal_name", "").strip().lower()

    for q in resolved.get("search_queries", []):
        for opt in options:
            if opt.lower() == q.lower():
                return opt

    # 3. Filter candidate options if a known building code is present
    filtered_options = options
    if b_code:
        matching_b_opts = [
            opt for opt in options
            if opt.lower().startswith(b_code + " ") or opt.lower() == b_code or (formal_b and formal_b in opt.lower())
        ]
        if matching_b_opts:
            filtered_options = matching_b_opts

    # 4. Fuzzy match within filtered options with safe cutoff
    matches = difflib.get_close_matches(val_clean, filtered_options, n=1, cutoff=0.6)
    if matches:
        return matches[0]

    # No match found, raise detailed ValueError with suggestions
    close_hints = difflib.get_close_matches(val_clean, filtered_options, n=3, cutoff=0.3)
    hint_msg = f" Did you mean one of: {', '.join(close_hints)}?" if close_hints else ""
    raise ValueError(f"'{val_clean}' is not a valid Location.{hint_msg}")


def validate_event_type(val: str) -> str:
    """Validates and fuzzy matches event types."""
    return match_dropdown_value(val, "event_types.json", "Event Type")


def validate_organization(val: str) -> str:
    """Validates and fuzzy matches sponsoring organizations."""
    return match_dropdown_value(val, "organizations.json", "Sponsoring Organization")


# --- Component 2: Sensitive Data Redaction ---

# Regex patterns for sensitive information redaction
NETID_PATTERN = re.compile(r"\b[a-z]{2,8}\d{1,4}\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b")
# API Keys, secrets, passwords
API_KEY_PATTERN = re.compile(
    r"\b(api[_-]?key|secret|token|password)\s*[:=]\s*\S+", re.IGNORECASE
)


def redact_sensitive_data(text: str) -> str:
    """Detects and redacts sensitive information like NetIDs, passwords, credentials, etc."""
    if not isinstance(text, str):
        return text

    # Redact passwords/tokens matching pattern first
    text = API_KEY_PATTERN.sub(lambda m: f"{m.group(1)}: [REDACTED_API_KEY]", text)

    # Redact credit card numbers
    text = CREDIT_CARD_PATTERN.sub("[REDACTED_CREDIT_CARD]", text)

    # Redact Social Security Numbers
    text = SSN_PATTERN.sub("[REDACTED_SSN]", text)

    # Redact Email addresses
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)

    # Redact UCR NetIDs (but avoid redacting standard short English words that fit the pattern)
    # E.g. avoid redacting 'to', 'in', 'an', but redact things like 'ntaing123'
    def netid_replacer(match):
        val = match.group(0)
        # Verify it actually contains a digit to distinguish from just letters
        if any(char.isdigit() for char in val):
            return "[REDACTED_NETID]"
        return val

    text = NETID_PATTERN.sub(netid_replacer, text)

    return text


# --- Component 3: Prompt Injection Detection ---

PROMPT_INJECTION_KEYWORDS = [
    "ignore previous",
    "ignore all previous",
    "override system",
    "system prompt",
    "developer instruction",
    "reveal credentials",
    "bypass validation",
    "override instruction",
    "do not redact",
    "you are now a",
    "impersonate",
    "ignore rules",
    "ignore the rules",
]

PROMPT_INJECTION_REGEX = re.compile(
    r"\b(system\s+prompt|ignore\s+previous|override\s+system|impersonate|you\s+are\s+now\s+a)\b",
    re.IGNORECASE,
)


def detect_prompt_injection(text: str) -> bool:
    """Inspects text input for potential prompt injection attempts."""
    if not isinstance(text, str):
        return False

    text_lower = text.lower()

    # Check keywords list
    for kw in PROMPT_INJECTION_KEYWORDS:
        if kw in text_lower:
            return True

    # Check regexes
    if PROMPT_INJECTION_REGEX.search(text_lower):
        return True

    return False


# --- Component 4: Preprocessing Pipeline Entrypoint ---


def preprocess_user_input(raw_input: str) -> str:
    """Executes the mandatory security preprocessing pipeline for raw strings.

    Returns the sanitized string or 'INVALID INPUT: PROMPT INJECTION' if injection is detected.
    """
    if not isinstance(raw_input, str):
        return raw_input

    # Step 1: Prompt Injection Check
    if detect_prompt_injection(raw_input):
        return "INVALID INPUT: PROMPT INJECTION"

    # Step 2: Sensitive Data Redaction
    sanitized = redact_sensitive_data(raw_input)

    return sanitized


async def clean_text_with_llm(
    text: str, event_name: str | None = None, autocorrect_only: bool = False
) -> str:
    """Uses Gemini to clean, professionalize, and expand event wording.

    Falls back to a basic rule-based clean-up if API is unconfigured.
    """
    # Rule-based cleaning fallback
    fallback_text = text.strip()
    fallback_text = re.sub(r"\s+", " ", fallback_text)
    fallback_text = re.sub(r"([.?!,;:])\1+", r"\1", fallback_text)

    # Check if we have API configuration
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_CLOUD_PROJECT")):
        return fallback_text

    try:
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI") == "true"
        client = Client(
            vertexai=use_vertex,
            project=os.getenv("GOOGLE_CLOUD_PROJECT") if use_vertex else None,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            if use_vertex
            else None,
        )

        model_name = "gemini-3.6-flash"
        if autocorrect_only:
            prompt = (
                "You are an assistant that autocorrects spelling, grammar, and punctuation for UCR scheduling comments.\n"
                "Review the user's input and correct any typos, spelling errors, grammatical mistakes, or awkward phrasing. "
                "Do NOT add any new details or expand on the input; keep the original meaning and length as close as possible. "
                "Only output the corrected text, with no extra chatter.\n"
            )
        else:
            prompt = (
                "You are an assistant that writes clean, professional event descriptions for UCR scheduling.\n"
                "Take the user's brief input and rewrite/expand it into a professional paragraph describing "
                "what will actually be done at the event. Do NOT write an invitation (do not say 'join us', 'come to', etc.). "
                "Focus purely on describing the activities and content of the event. Use the user's input and "
                "enrich it with plausible details to make it a complete description of the event activities. "
                "The generated description MUST be brief, between 25 and 45 words in length.\n"
            )
            if event_name:
                prompt += f"The event is named: '{event_name}'.\n"

        prompt += f"\nUser input: {text}\nClean result:"

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        if response.text:
            return response.text.strip()
    except Exception as e:
        print(
            f"Warning: LLM text cleaning failed ({e!s}). Using fallback rule-based cleaning."
        )

    return fallback_text


def validate_discord_id(discord_id: str) -> str:
    """Validates that a Discord user ID consists only of safe alphanumeric/snowflake characters."""
    if not isinstance(discord_id, str):
        raise ValueError("Discord ID must be a string")
    clean_id = discord_id.strip()
    if not re.match(r"^[a-zA-Z0-9_\-]{3,32}$", clean_id):
        raise ValueError(
            "Invalid Discord ID format. Must be a safe alphanumeric identifier (3-32 chars)."
        )
    return clean_id
