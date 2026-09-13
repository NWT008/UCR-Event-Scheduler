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

"""Unit tests for UCR building aliases and starred location matching."""

from app.building_aliases import (
    match_starred_location,
    normalize_string,
    resolve_location_alias,
)


def test_normalize_string():
    assert normalize_string("MSE 104") == "mse104"
    assert normalize_string("  Student-Success Center (MPR 1)  ") == "studentsuccesscentermpr1"
    assert normalize_string("") == ""
    assert normalize_string(None) == ""


def test_resolve_location_alias_mse():
    res = resolve_location_alias("MSE 104")
    assert res["building_code"] == "MSE"
    assert res["formal_name"] == "Materials Science and Engineering"
    assert res["room_number"] == "104"
    assert "MSE 104" in res["search_queries"]
    assert "Materials Science and Engineering 104" in res["search_queries"]


def test_resolve_location_alias_ssc():
    res = resolve_location_alias("Student Success Center 121")
    assert res["building_code"] == "SSC"
    assert res["formal_name"] == "Student Success Center"
    assert res["room_number"] == "121"
    assert "SSC 121" in res["search_queries"]
    assert "Student Success Center 121" in res["search_queries"]


def test_resolve_location_alias_wch():
    res = resolve_location_alias("Chung 205")
    assert res["building_code"] in ["WCH", "CHUNG"]
    assert res["formal_name"] == "Winston Chung Hall"
    assert res["room_number"] == "205"
    assert "Winston Chung Hall 205" in res["search_queries"]


def test_match_starred_location_exact_code():
    starred = [
        {"space_name": "MSE 104", "formal_name": "Materials Science and Engineering 104"},
        {"space_name": "SRC 129 MPR B", "formal_name": "MPR B"},
    ]
    matched = match_starred_location("MSE 104", starred)
    assert matched is not None
    assert matched["space_name"] == "MSE 104"


def test_match_starred_location_formal_name():
    starred = [
        {"space_name": "MSE 104", "formal_name": "Materials Science and Engineering 104"},
        {"space_name": "SRC 129 MPR B", "formal_name": "MPR B"},
    ]
    matched = match_starred_location("Materials Science and Engineering 104", starred)
    assert matched is not None
    assert matched["space_name"] == "MSE 104"


def test_match_starred_location_fuzzy_alias():
    starred = [
        {"space_name": "MSE 104", "formal_name": "Materials Science and Engineering 104"},
        {"space_name": "SRC 129 MPR B", "formal_name": "MPR B"},
    ]
    matched = match_starred_location("mat sci 104", starred)
    assert matched is not None
    assert matched["space_name"] == "MSE 104"


def test_match_starred_location_none():
    starred = [
        {"space_name": "MSE 104", "formal_name": "Materials Science and Engineering 104"},
    ]
    matched = match_starred_location("Bourns Hall B118", starred)
    assert matched is None


def test_resolve_location_alias_ssc_mpr_and_combos():
    # SSC MPR 3 should map to SSC 121
    res_mpr3 = resolve_location_alias("SSC MPR 3")
    assert res_mpr3["building_code"] == "SSC"
    assert "SSC 121" in res_mpr3["search_queries"]
    assert "Student Success Center (MPR 3) 121" in res_mpr3["search_queries"]

    # SSC MPR Combo 2/3 should keep SSC building code and combo queries
    res_combo = resolve_location_alias("SSC MPR Combo 2/3")
    assert res_combo["building_code"] == "SSC"
    assert "SSC MPR Combo 2/3" in res_combo["search_queries"]
    assert "SSC MPR Combo 2 & 3" in res_combo["search_queries"]


def test_match_starred_location_ssc_mpr():
    starred = [
        {"space_name": "SSC 121", "formal_name": "Student Success Center (MPR 3) 121"},
        {"space_name": "SSC MPR Combo 2/3", "formal_name": "SSC MPR Combo 2 & 3"},
    ]
    assert match_starred_location("SSC MPR 3", starred)["space_name"] == "SSC 121"
    assert match_starred_location("ssc mpr combo 2/3", starred)["space_name"] == "SSC MPR Combo 2/3"

