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

"""Campus building aliases, acronym resolution, and room normalization for UCR 25Live."""

import re
from typing import Any

# UC Riverside Campus Building Mappings
# Maps building codes and common acronyms to their 25Live formal names and building codes.
CAMPUS_BUILDINGS: dict[str, dict[str, Any]] = {
    "MSE": {
        "formal_name": "Materials Science and Engineering",
        "building_code": "MAT SCI ENGR",
        "aliases": [
            "mse",
            "materials science",
            "materials science and engineering",
            "materials science & engineering",
            "mat sci engr",
            "mat sci",
        ],
    },
    "SSC": {
        "formal_name": "Student Success Center",
        "building_code": "Student Success Center",
        "aliases": [
            "ssc",
            "student success",
            "student success center",
        ],
    },
    "WCH": {
        "formal_name": "Winston Chung Hall",
        "building_code": "Winston Chung Hall",
        "aliases": [
            "wch",
            "chung",
            "winston chung",
            "winston chung hall",
        ],
    },
    "CHUNG": {
        "formal_name": "Winston Chung Hall",
        "building_code": "Winston Chung Hall",
        "aliases": [
            "wch",
            "chung",
            "winston chung",
            "winston chung hall",
        ],
    },
    "BOYHL": {
        "formal_name": "Alfred M. Boyce Hall",
        "building_code": "Alfred M. Boyce Hall",
        "aliases": [
            "boyhl",
            "boyce",
            "boyce hall",
            "alfred m boyce hall",
            "alfred boyce",
        ],
    },
    "BRNHL": {
        "formal_name": "Bourns Hall",
        "building_code": "Bourns Hall",
        "aliases": [
            "brnhl",
            "bourns",
            "bourns hall",
        ],
    },
    "HMNSS": {
        "formal_name": "Humanities and Social Sciences",
        "building_code": "Humanities and Social Sci",
        "aliases": [
            "hmnss",
            "humanities",
            "humanities and social sciences",
            "humanities & social sciences",
        ],
    },
    "PRCE": {
        "formal_name": "Pierce Hall",
        "building_code": "Pierce Hall",
        "aliases": [
            "prce",
            "pierce",
            "pierce hall",
        ],
    },
    "SPTH": {
        "formal_name": "Spieth Hall",
        "building_code": "Spieth Hall",
        "aliases": [
            "spth",
            "spieth",
            "spieth hall",
        ],
    },
    "PHYS": {
        "formal_name": "Physics",
        "building_code": "Physics",
        "aliases": [
            "phys",
            "physics",
            "physics building",
        ],
    },
    "UNLH": {
        "formal_name": "University Lecture Hall",
        "building_code": "Univ Lecture Hall",
        "aliases": [
            "unlh",
            "univ lecture hall",
            "university lecture hall",
        ],
    },
    "OLMN": {
        "formal_name": "Olmsted Hall",
        "building_code": "Olmsted Hall",
        "aliases": [
            "olmn",
            "olmsted",
            "olmsted hall",
        ],
    },
    "ALUM": {
        "formal_name": "Alumni & Visitors Center",
        "building_code": "Alumni & Visitors Center",
        "aliases": [
            "alum",
            "alumni center",
            "alumni and visitors center",
            "alumni & visitors center",
        ],
    },
    "SRC": {
        "formal_name": "Student Recreation Center",
        "building_code": "SRC North",
        "aliases": [
            "src",
            "src north",
            "src south",
            "recreation center",
            "student recreation center",
        ],
    },
    "HUB": {
        "formal_name": "Highlander Union Building",
        "building_code": "Highlander Union Building",
        "aliases": [
            "hub",
            "highlander union building",
        ],
    },
}


# Specific room aliases mapping common shortcuts to official 25Live space names and formal names
SPECIAL_ROOM_ALIASES: dict[str, list[str]] = {
    # SSC Multi-Purpose Rooms
    "ssc mpr 1": ["SSC 125", "Student Success Center (MPR 1) 125", "SSC MPR 1"],
    "ssc mpr 2": ["SSC 123", "Student Success Center (MPR 2) 123", "SSC MPR 2"],
    "ssc mpr 3": ["SSC 121", "Student Success Center (MPR 3) 121", "SSC MPR 3"],
    "ssc 125": ["SSC 125", "Student Success Center (MPR 1) 125", "SSC MPR 1"],
    "ssc 123": ["SSC 123", "Student Success Center (MPR 2) 123", "SSC MPR 2"],
    "ssc 121": ["SSC 121", "Student Success Center (MPR 3) 121", "SSC MPR 3"],
    # SSC Combo Rooms
    "ssc mpr combo 1/2": ["SSC MPR Combo 1/2", "SSC MPR Combo 1 & 2", "SSC MPR Combo"],
    "ssc mpr combo 1 & 2": ["SSC MPR Combo 1/2", "SSC MPR Combo 1 & 2", "SSC MPR Combo"],
    "ssc mpr combo 2/3": ["SSC MPR Combo 2/3", "SSC MPR Combo 2 & 3", "SSC MPR Combo"],
    "ssc mpr combo 2 & 3": ["SSC MPR Combo 2/3", "SSC MPR Combo 2 & 3", "SSC MPR Combo"],
    "ssc mpr combo 1/2/3": ["SSC MPR Combo 1/2/3", "SSC MPR Combo 1, 2 & 3", "SSC MPR Combo"],
    "ssc mpr combo 1, 2 & 3": ["SSC MPR Combo 1/2/3", "SSC MPR Combo 1, 2 & 3", "SSC MPR Combo"],
    # SRC Multi-Purpose Rooms
    "src mpr a": ["SRC 120 MPR A", "MPR A"],
    "src mpr b": ["SRC 129 MPR B", "MPR B"],
    "src mpr c": ["SRC 133 MPR C", "MPR C"],
    "src mpr d": ["SRC 0119 MPR D", "MPR D"],
    "src mpr e": ["SRC 2107 MPR E", "MPR E"],
}


def normalize_string(val: str | None) -> str:
    """Normalizes string for comparison: lowercase, alphanumeric characters only."""
    if not val:
        return ""
    return re.sub(r"[^a-z0-9]", "", val.lower())


def resolve_location_alias(raw_input: str) -> dict[str, Any]:
    """Resolves a raw location string (e.g. 'MSE 104', 'SSC MPR 3', 'SSC MPR Combo 2/3')

    into standardized building components and query terms.
    """
    cleaned = raw_input.strip()
    if not cleaned:
        return {
            "raw": "",
            "building_code": "",
            "formal_name": "",
            "room_number": "",
            "search_queries": [],
        }

    # Check combo room pattern like 'MPR Combo 2/3' or 'MPR Combo 2 & 3' first
    combo_match = re.search(
        r"\b(MPR\s+Combo\s+[\d/&,\s]+)\b", cleaned, re.IGNORECASE
    )
    if combo_match:
        room_number = combo_match.group(1).strip()
    else:
        # Extract room number (digits, optionally followed by letters like 129A or MPR B)
        room_match = re.search(
            r"\b(\d+[A-Za-z]?|\bMPR\s+[A-Za-z0-9]+)\b", cleaned, re.IGNORECASE
        )
        room_number = room_match.group(1).strip() if room_match else ""

    # Extract building portion by removing the room number
    building_part = (
        re.sub(re.escape(room_number), "", cleaned, count=1, flags=re.IGNORECASE).strip()
        if room_number
        else cleaned
    )
    norm_building = normalize_string(building_part)

    matched_code = ""
    matched_entry = None

    for code, data in CAMPUS_BUILDINGS.items():
        if norm_building == normalize_string(code) or norm_building.startswith(normalize_string(code)):
            matched_code = code
            matched_entry = data
            break
        for alias in data["aliases"]:
            if norm_building == normalize_string(alias) or norm_building.startswith(normalize_string(alias)):
                matched_code = code
                matched_entry = data
                break
        if matched_entry:
            break

    search_queries = [cleaned]

    # Check for known special room shortcuts
    clean_lower = cleaned.lower()
    for shortcut, targets in SPECIAL_ROOM_ALIASES.items():
        if clean_lower == shortcut or normalize_string(clean_lower) == normalize_string(shortcut):
            for t in targets:
                if t not in search_queries:
                    search_queries.append(t)

    if matched_entry:
        formal_name = matched_entry["formal_name"]
        b_code = matched_entry["building_code"]
        if room_number:
            search_queries.append(f"{matched_code} {room_number}")
            search_queries.append(f"{formal_name} {room_number}")
            search_queries.append(f"{b_code} {room_number}")
        else:
            search_queries.append(matched_code)
            search_queries.append(formal_name)
    else:
        formal_name = building_part.strip()
        b_code = building_part.strip()

    # Deduplicate queries while preserving order
    seen = set()
    deduped_queries = []
    for q in search_queries:
        if q and q.lower() not in seen:
            seen.add(q.lower())
            deduped_queries.append(q)

    return {
        "raw": cleaned,
        "building_code": matched_code or building_part.strip(),
        "formal_name": formal_name,
        "room_number": room_number,
        "search_queries": deduped_queries,
    }


def match_starred_location(
    user_query: str, starred_locations: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Matches a user's location input against their list of Starred Locations in 25Live.

    Returns the matching starred location dict or None.
    """
    if not user_query or not starred_locations:
        return None

    norm_query = normalize_string(user_query)
    resolved = resolve_location_alias(user_query)
    room_num = resolved.get("room_number", "")
    building_code = resolved.get("building_code", "")

    # 1. Exact match on normalized space_name or formal_name
    for space in starred_locations:
        s_name = normalize_string(space.get("space_name") or space.get("name"))
        f_name = normalize_string(space.get("formal_name"))
        if norm_query and (norm_query == s_name or norm_query == f_name):
            return space

    # 2. Check if any resolved alias search query matches a starred space
    for q in resolved.get("search_queries", []):
        norm_q = normalize_string(q)
        if norm_q:
            for space in starred_locations:
                s_name = normalize_string(space.get("space_name") or space.get("name"))
                f_name = normalize_string(space.get("formal_name"))
                if norm_q == s_name or norm_q == f_name:
                    return space

    # 3. Match if room number and building alias/code match
    if room_num:
        norm_room = normalize_string(room_num)
        for space in starred_locations:
            s_name = normalize_string(space.get("space_name") or space.get("name"))
            f_name = normalize_string(space.get("formal_name"))
            b_name = normalize_string(space.get("building_name"))

            # Ensure the room number is in the space name
            if norm_room in s_name or norm_room in f_name:
                # Check building code / formal name
                if building_code and (
                    normalize_string(building_code) in s_name
                    or normalize_string(building_code) in f_name
                    or normalize_string(building_code) in b_name
                ):
                    return space
                # Check resolved formal name
                res_formal = normalize_string(resolved.get("formal_name"))
                if res_formal and (res_formal in s_name or res_formal in f_name):
                    return space

    # 3. Substring containment match
    for space in starred_locations:
        s_name = normalize_string(space.get("space_name") or space.get("name"))
        f_name = normalize_string(space.get("formal_name"))
        if norm_query in s_name or norm_query in f_name:
            return space
        if s_name and s_name in norm_query:
            return space

    return None
