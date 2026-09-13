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

import os

from dotenv import load_dotenv

load_dotenv()

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def map_score_1_5(raw_score: int) -> int:
    """Maps 1-5 scale scores to avoid 1 and 5.

    Extreme scores (5 or 1) are mapped toward 3 and 2 respectively.
    """
    if raw_score >= 5:
        return 3
    if raw_score <= 1:
        return 2
    return 3 if raw_score >= 3 else 2


def evaluate_description(instance) -> dict:
    prompt_obj = instance.get("prompt") or {}
    user_input = ""
    if isinstance(prompt_obj, dict):
        parts = prompt_obj.get("parts") or []
        if parts:
            user_input = parts[0].get("text") or ""

    event_name = instance.get("event_name", "Event")

    # Retrieve response text
    response_obj = instance.get("response") or {}
    generated_description = ""
    if isinstance(response_obj, dict):
        parts = response_obj.get("parts") or []
        if parts:
            generated_description = parts[0].get("text") or ""

    if not generated_description:
        # Check alternate fields if any
        responses = instance.get("responses") or []
        if responses and isinstance(responses[0], dict):
            resp_info = responses[0].get("response") or {}
            parts = resp_info.get("parts") or []
            if parts:
                generated_description = parts[0].get("text") or ""

    word_count = len(generated_description.split())

    # Programmatic check for expansion behavior (roughly 25-45 words, centered around ~35)
    word_count_score = 5
    if word_count < 25 or word_count > 45:
        # Small penalty if slightly off, larger penalty if completely off
        if word_count < 15 or word_count > 55:
            word_count_score = 2
        else:
            word_count_score = 3

    try:
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI") == "true"
        client = genai.Client(
            vertexai=use_vertex,
            project=os.getenv("GOOGLE_CLOUD_PROJECT") if use_vertex else None,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            if use_vertex
            else None,
        )

        judge_prompt = (
            "You are an expert QA evaluator. Grade the event description on a 1-5 scale based on these behaviors:\n"
            "1. Detail preservation: Keeps the user's original idea and adds reasonable event details without drifting.\n"
            "2. Grammar correction: Clean spelling, capitalization, sentence structure, and punctuation.\n"
            "3. Professionalization: Casual wording (e.g. 'hang out') is made professional (e.g. 'socialize') without turning into marketing or invitation copy (no 'join us', 'come to', etc.).\n\n"
            f"Event Name: {event_name}\n"
            f"User Input: {user_input}\n"
            f"Generated Description: {generated_description}\n\n"
            "Provide a 1-5 score, and a very brief explanation (max 1 sentence summary, prioritize brevity, 50% reduced verbosity)."
        )

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=judge_prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=_Verdict,
            ),
        )

        verdict = response.parsed
        if verdict:
            # Combine LLM score with programmatic word count score
            raw_score = min(verdict.score, word_count_score)
            final_score = map_score_1_5(raw_score)

            # Post-process explanation to be extremely brief
            explanation = verdict.explanation or "Matches expected behaviors."
            if len(explanation.split()) > 10:
                explanation = " ".join(explanation.split()[:10]) + "..."

            return {"score": final_score, "explanation": explanation}

    except Exception:
        # Fallback in case of API error
        pass

    final_score = map_score_1_5(word_count_score)
    return {
        "score": final_score,
        "explanation": f"Fallback evaluation. Words: {word_count}.",
    }
