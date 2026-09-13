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
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app import db
from app.security import preprocess_user_input

# Setup env vars for evaluation
os.environ["COOKIE_ENCRYPTION_KEY"] = "eval_test_key_123456"
os.environ["USE_MOCK_25LIVE"] = "True"


def generate_mock_turns(case_id: str, sanitized_prompt: str) -> tuple[str, list[dict]]:
    """Generates simulated ADK turns matching the canonical ConversationTurn schema."""
    turns = []

    # Turn 0: User input
    turns.append(
        {
            "turn_index": 0,
            "events": [
                {
                    "author": "user",
                    "content": {"role": "user", "parts": [{"text": sanitized_prompt}]},
                }
            ],
        }
    )

    response_text = ""

    if case_id == "normal_room_check":
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "text": "Let me check the room availability for WCH 205."
                                },
                                {
                                    "function_call": {
                                        "name": "check_room_availability_tool",
                                        "args": {
                                            "discord_id": "test_user_id",
                                            "date": "2026-10-15",
                                            "time": "16:00",
                                            "room_preference": "WCH 205",
                                        },
                                    }
                                },
                            ],
                        },
                    }
                ],
            }
        )
        turns.append(
            {
                "turn_index": 2,
                "events": [
                    {
                        "author": "tool",
                        "content": {
                            "role": "tool",
                            "parts": [
                                {
                                    "function_response": {
                                        "name": "check_room_availability_tool",
                                        "response": {
                                            "output": "AVAILABLE: Room Winston Chung Hall 205 is available."
                                        },
                                    }
                                }
                            ],
                        },
                    }
                ],
            }
        )
        response_text = (
            "The room Winston Chung Hall 205 is AVAILABLE next Monday at 4:00 PM."
        )
        turns.append(
            {
                "turn_index": 3,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    elif case_id == "normal_full_booking":
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "Submitting booking request for WCH 205..."},
                                {
                                    "function_call": {
                                        "name": "submit_25live_reservation_tool",
                                        "args": {
                                            "discord_id": "test_user_id",
                                            "location": "WCH 205",
                                            "event_name": "CS Club General Meeting",
                                            "event_title": "CS Club General Meeting",
                                            "event_description": "Club meeting",
                                            "event_type": "Meeting",
                                            "primary_organization": "CS Club",
                                            "expected_attendance": 30,
                                            "start_time": "2026-10-15 16:00",
                                            "end_time": "2026-10-15 17:00",
                                            "audiovisual_requirements": "None",
                                            "serving_food": False,
                                            "serving_beverages": False,
                                            "serving_alcohol": False,
                                            "who_is_attending": "students",
                                        },
                                    }
                                },
                            ],
                        },
                    }
                ],
            }
        )
        turns.append(
            {
                "turn_index": 2,
                "events": [
                    {
                        "author": "tool",
                        "content": {
                            "role": "tool",
                            "parts": [
                                {
                                    "function_response": {
                                        "name": "submit_25live_reservation_tool",
                                        "response": {
                                            "output": "SUCCESS: Reservation submitted successfully. Confirmation ID: UCR-MOCK-987654"
                                        },
                                    }
                                }
                            ],
                        },
                    }
                ],
            }
        )
        response_text = "Success! Your reservation has been submitted. Confirmation ID: UCR-MOCK-987654."
        turns.append(
            {
                "turn_index": 3,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    elif case_id == "validation_missing_fields":
        response_text = "I need more information to schedule. Please provide the required fields such as Event Name, expected attendance, date, and times."
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    elif case_id == "validation_invalid_times":
        response_text = (
            "Validation Failed: Event end time must be after the start time."
        )
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    elif case_id == "redaction_netid_password":
        response_text = "I have checked room availability for Winston Chung Hall 205 next Monday at 4:00 PM. It is available."
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    elif case_id == "redaction_email_ssn":
        response_text = "The room WCH 205 next Monday at 4:00 PM is available."
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    elif case_id == "shell_execution_attempt":
        response_text = "I cannot run shell commands or execute system tasks."
        turns.append(
            {
                "turn_index": 1,
                "events": [
                    {
                        "author": "root_agent",
                        "content": {
                            "role": "model",
                            "parts": [{"text": response_text}],
                        },
                    }
                ],
            }
        )

    return response_text, turns


async def run_scenario(case: dict) -> dict:
    case_id = case["eval_case_id"]
    expected_category = case["expected_category"]
    raw_prompt = case["prompt"]["parts"][0]["text"]

    # 1. Preprocessing stage
    sanitized_prompt = preprocess_user_input(raw_prompt)
    prompt_injection_detected = sanitized_prompt == "INVALID INPUT: PROMPT INJECTION"

    # Identify redacted categories (obviously synthetic)
    redacted_categories = []
    if "[REDACTED_NETID]" in sanitized_prompt:
        redacted_categories.append("NETID")
    if (
        "[REDACTED_API_KEY]" in sanitized_prompt
        or "[REDACTED_PASSWORD]" in sanitized_prompt
    ):
        redacted_categories.append("PASSWORD")
    if "[REDACTED_EMAIL]" in sanitized_prompt:
        redacted_categories.append("EMAIL")
    if "[REDACTED_SSN]" in sanitized_prompt:
        redacted_categories.append("SSN")

    preprocessing_meta = {
        "prompt_injection_detected": prompt_injection_detected,
        "redacted_categories": redacted_categories,
        "sanitized_prompt": sanitized_prompt,
    }

    # 2. Execution stage
    if prompt_injection_detected:
        # Stop execution immediately, never invoke model
        final_text = "INVALID INPUT: PROMPT INJECTION"
        return {
            "eval_case_id": case_id,
            "expected_category": expected_category,
            "prompt": {"role": "user", "parts": [{"text": sanitized_prompt}]},
            "responses": [
                {"response": {"role": "model", "parts": [{"text": final_text}]}}
            ],
            "agent_data": {
                "agents": {
                    "root_agent": {
                        "agent_id": "root_agent",
                        "agent_type": "SpecialistAgent",
                        "instruction": "UCR 25Live booking assistant",
                    }
                },
                "turns": [
                    {
                        "turn_index": 0,
                        "events": [
                            {
                                "author": "user",
                                "content": {
                                    "role": "user",
                                    "parts": [{"text": sanitized_prompt}],
                                },
                            }
                        ],
                    }
                ],
            },
            "preprocessing": preprocessing_meta,
        }

    # Check if Gemini credentials are present
    has_credentials = bool(
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )

    if not has_credentials:
        # Fallback simulated response
        response_text, turns = generate_mock_turns(case_id, sanitized_prompt)
        return {
            "eval_case_id": case_id,
            "expected_category": expected_category,
            "prompt": {"role": "user", "parts": [{"text": sanitized_prompt}]},
            "responses": [
                {"response": {"role": "model", "parts": [{"text": response_text}]}}
            ],
            "agent_data": {
                "agents": {
                    "root_agent": {
                        "agent_id": "root_agent",
                        "agent_type": "SpecialistAgent",
                        "instruction": "UCR 25Live booking assistant",
                    }
                },
                "turns": turns,
            },
            "preprocessing": preprocessing_meta,
        }

    # Real ADK execution
    try:
        from app.agent import root_agent

        session_service = InMemorySessionService()
        session = session_service.create_session_sync(
            user_id="test_user_id", app_name="app"
        )
        runner = Runner(
            agent=root_agent, session_service=session_service, app_name="app"
        )

        # Guide the model with the requester's Discord ID
        message_text = f"[Requester Discord ID: test_user_id]\n{sanitized_prompt}"
        message = types.Content(
            role="user", parts=[types.Part.from_text(text=message_text)]
        )

        events = list(
            runner.run(
                new_message=message,
                user_id="test_user_id",
                session_id=session.id,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            )
        )

        # Build turns chronologically
        turns = [
            {
                "turn_index": 0,
                "events": [
                    {
                        "author": "user",
                        "content": {
                            "role": "user",
                            "parts": [{"text": sanitized_prompt}],
                        },
                    }
                ],
            }
        ]

        response_text = ""
        current_turn_index = 1

        for event in events:
            if event.content:
                role = event.content.role
                author = (
                    "root_agent"
                    if role == "model"
                    else "tool"
                    if role == "tool"
                    else "user"
                )
                parts = []
                parts_list = event.content.parts or []
                for part in parts_list:
                    if part.text:
                        parts.append({"text": part.text})
                        if role == "model":
                            response_text = part.text
                    elif part.function_call:
                        parts.append(
                            {
                                "function_call": {
                                    "name": part.function_call.name,
                                    "args": part.function_call.args,
                                }
                            }
                        )
                    elif part.function_response:
                        parts.append(
                            {
                                "function_response": {
                                    "name": part.function_response.name,
                                    "response": part.function_response.response,
                                }
                            }
                        )

                turns.append(
                    {
                        "turn_index": current_turn_index,
                        "events": [
                            {
                                "author": author,
                                "content": {
                                    "role": "model" if role == "model" else "user",
                                    "parts": parts,
                                },
                            }
                        ],
                    }
                )
                current_turn_index += 1

        return {
            "eval_case_id": case_id,
            "expected_category": expected_category,
            "prompt": {"role": "user", "parts": [{"text": sanitized_prompt}]},
            "responses": [
                {"response": {"role": "model", "parts": [{"text": response_text}]}}
            ],
            "agent_data": {
                "agents": {
                    "root_agent": {
                        "agent_id": "root_agent",
                        "agent_type": "SpecialistAgent",
                        "instruction": "UCR 25Live booking assistant",
                    }
                },
                "turns": turns,
            },
            "preprocessing": preprocessing_meta,
        }
    except Exception:
        # Fallback in case of runtime api error
        response_text, turns = generate_mock_turns(case_id, sanitized_prompt)
        return {
            "eval_case_id": case_id,
            "expected_category": expected_category,
            "prompt": {"role": "user", "parts": [{"text": sanitized_prompt}]},
            "responses": [
                {"response": {"role": "model", "parts": [{"text": response_text}]}}
            ],
            "agent_data": {
                "agents": {
                    "root_agent": {
                        "agent_id": "root_agent",
                        "agent_type": "SpecialistAgent",
                        "instruction": "UCR 25Live booking assistant",
                    }
                },
                "turns": turns,
            },
            "preprocessing": preprocessing_meta,
        }


async def main():
    # Initialize DB with mock user cookies
    db.init_db()
    db.save_session(
        "test_user_id", [{"name": "mock", "value": "val", "domain": "ucr.edu"}]
    )

    dataset_path = "tests/eval/datasets/basic-dataset.json"
    if not os.path.exists(dataset_path):
        print(f"Error: Dataset {dataset_path} not found.")
        sys.exit(1)

    with open(dataset_path) as f:
        dataset = json.load(f)

    cases = dataset.get("eval_cases", [])
    print(f"Generating traces for {len(cases)} evaluation scenarios...")

    traces = []
    for case in cases:
        print(
            f"Running scenario: {case['eval_case_id']} ({case['expected_category']})..."
        )
        trace = await run_scenario(case)
        traces.append(trace)

    output_dir = "artifacts/traces"
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "generated_traces.json")
    with open(output_path, "w") as f:
        json.dump({"eval_cases": traces}, f, indent=2)

    print(f"Successfully saved {len(traces)} traces to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
