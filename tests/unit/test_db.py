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
import sqlite3

import pytest

from app import db


@pytest.fixture(autouse=True)
def setup_env_and_db(monkeypatch, tmp_path):
    # Set a test encryption key
    monkeypatch.setenv("COOKIE_ENCRYPTION_KEY", "super_secret_test_key_12345")
    # Redirect DB path to a temporary path for testing to avoid modifying actual database
    test_db = str(tmp_path / "test_session_cache.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()


def test_encryption_decryption():
    test_cookies = [
        {"name": "session_id", "value": "xyz123", "domain": "reserve.ucr.edu"},
        {"name": "shib_cookie", "value": "abc456", "domain": ".ucr.edu"},
    ]
    key = db.get_encryption_key()

    enc, iv, tag = db.encrypt_cookies(test_cookies, key)
    assert enc != test_cookies

    decrypted = db.decrypt_cookies(enc, iv, tag, key)
    assert decrypted == test_cookies


def test_save_and_get():
    discord_id = "test_user_123"
    test_cookies = [{"name": "test_cookie", "value": "test_val"}]

    # Save session
    db.save_session(discord_id, test_cookies)

    # Get session
    retrieved = db.get_session(discord_id)
    assert retrieved == test_cookies

    # Delete session
    db.delete_session(discord_id)
    assert db.get_session(discord_id) is None


def test_session_expiry(monkeypatch):
    discord_id = "expired_user_999"
    test_cookies = [{"name": "test_cookie", "value": "test_val"}]

    db.save_session(discord_id, test_cookies)

    # Manually backdate the updated_at timestamp in the database to 15 days ago
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cursor = conn.cursor()
        expired_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=15)
        # SQLite ISO8601 string
        cursor.execute(
            "UPDATE user_sessions SET updated_at = ? WHERE discord_id = ?",
            (expired_time.isoformat(), discord_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Attempting to get the session should return None (and delete it)
    assert db.get_session(discord_id) is None

    # Double check it is deleted from the table
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_sessions WHERE discord_id = ?", (discord_id,)
        )
        count = cursor.fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_decryption_failure(monkeypatch):
    discord_id = "failing_decrypt_user"
    test_cookies = [{"name": "test_cookie", "value": "test_val"}]

    db.save_session(discord_id, test_cookies)

    # Change the encryption key
    monkeypatch.setenv("COOKIE_ENCRYPTION_KEY", "a_different_secret_key_67890")

    # Decryption should fail, leading get_session to return None (safe fallback)
    assert db.get_session(discord_id) is None


def test_user_isolation_encryption():
    user_a = "user_111111111"
    user_b = "user_222222222"
    cookies_a = [{"name": "secret_session", "value": "a_confidential_token"}]

    db.save_session(user_a, cookies_a)

    # User B cannot retrieve User A's session
    assert db.get_session(user_b) is None

    # Verify cryptographic AEAD isolation: even if User B's key attempts to decrypt User A's ciphertext
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT encrypted_cookies, iv, tag FROM user_sessions WHERE discord_id = ?",
            (user_a,),
        )
        enc_a, iv_a, tag_a = cursor.fetchone()
    finally:
        conn.close()

    from cryptography.exceptions import InvalidTag

    # Attempting decryption with user_b key and user_b associated data must raise an error
    key_b = db.get_user_encryption_key(user_b)
    with pytest.raises(InvalidTag):
        db.decrypt_cookies(
            enc_a, iv_a, tag_a, key_b, associated_data=user_b.encode("utf-8")
        )


def test_invalid_discord_id_handling():
    # Attempting SQL injection or directory traversal in discord_id
    malicious_id = "user'; DROP TABLE user_sessions; --"
    test_cookies = [{"name": "test", "value": "val"}]

    with pytest.raises(ValueError):
        db.save_session(malicious_id, test_cookies)

    assert db.get_session(malicious_id) is None
