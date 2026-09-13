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

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app import db  # noqa: E402
from app.security import clean_text_with_llm  # noqa: E402

os.environ["COOKIE_ENCRYPTION_KEY"] = "eval_test_key_123456"
os.environ["USE_MOCK_25LIVE"] = "True"


async def run_description_case(case: dict) -> dict:
    case_id = case["eval_case_id"]
    expected_category = case["expected_category"]
    raw_prompt = case["prompt"]["parts"][0]["text"]
    event_name = case.get("event_name")

    # Run description clean and expansion
    response_text = await clean_text_with_llm(raw_prompt, event_name=event_name)

    # Format trace to meet agents-cli conversation expectation
    return {
        "eval_case_id": case_id,
        "expected_category": expected_category,
        "event_name": event_name,
        "prompt": {"role": "user", "parts": [{"text": raw_prompt}]},
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
            "turns": [
                {
                    "turn_index": 0,
                    "events": [
                        {
                            "author": "user",
                            "content": {
                                "role": "user",
                                "parts": [{"text": raw_prompt}],
                            },
                        }
                    ],
                },
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
                },
            ],
        },
    }


async def main():
    db.init_db()

    dataset_path = "tests/eval/datasets/description-dataset.json"
    if not os.path.exists(dataset_path):
        print(f"Error: Dataset {dataset_path} not found.")
        sys.exit(1)

    with open(dataset_path) as f:
        dataset = json.load(f)

    cases = dataset.get("eval_cases", [])
    print(f"Generating traces for {len(cases)} description evaluation scenarios...")

    traces = []
    for case in cases:
        print(f"Running scenario: {case['eval_case_id']}...")
        trace = await run_description_case(case)
        traces.append(trace)

    output_dir = "artifacts/traces"
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "description_traces.json")
    with open(output_path, "w") as f:
        json.dump({"eval_cases": traces}, f, indent=2)

    print(f"Successfully saved {len(traces)} description traces to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
