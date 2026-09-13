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
import hashlib
import json
import os
import sqlite3
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Constants
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session_cache.db"
)


def get_encryption_key() -> bytes:
    """Derives a 32-byte AES key from the COOKIE_ENCRYPTION_KEY env var using SHA-256."""
    key_str = os.getenv("COOKIE_ENCRYPTION_KEY")
    if not key_str:
        # Fallback to a warning/error in production, but raise for security compliance
        raise ValueError("COOKIE_ENCRYPTION_KEY environment variable is not set")
    return hashlib.sha256(key_str.encode("utf-8")).digest()


def get_user_encryption_key(discord_id: str) -> bytes:
    """Derives a unique 32-byte AES key bound to a specific discord_id using SHA-256."""
    master_key = get_encryption_key()
    return hashlib.sha256(master_key + b":user:" + discord_id.encode("utf-8")).digest()


def encrypt_cookies(
    cookies: list[dict[str, Any]], key: bytes, associated_data: bytes | None = None
) -> tuple[bytes, bytes, bytes]:
    """Encrypts a list of cookies using AES-256-GCM AEAD.

    Returns:
        (encrypted_cookies, iv, tag)
    """
    serialized = json.dumps(cookies).encode("utf-8")
    aesgcm = AESGCM(key)
    iv = os.urandom(12)  # 12-byte nonce for GCM

    # encrypt returns ciphertext + 16-byte tag concatenated in Python cryptography
    encrypted_data = aesgcm.encrypt(iv, serialized, associated_data)

    tag = encrypted_data[-16:]
    encrypted_cookies = encrypted_data[:-16]

    return encrypted_cookies, iv, tag


def decrypt_cookies(
    encrypted_cookies: bytes,
    iv: bytes,
    tag: bytes,
    key: bytes,
    associated_data: bytes | None = None,
) -> list[dict[str, Any]]:
    """Decrypts cookies using AES-256-GCM AEAD."""
    aesgcm = AESGCM(key)
    # Reconstruct the combined ciphertext + tag
    encrypted_data = encrypted_cookies + tag

    decrypted_bytes = aesgcm.decrypt(iv, encrypted_data, associated_data)
    return json.loads(decrypted_bytes.decode("utf-8"))


def init_db():
    """Initializes the SQLite database schema."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                discord_id TEXT PRIMARY KEY,
                encrypted_cookies BLOB NOT NULL,
                iv BLOB NOT NULL,
                tag BLOB NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS time_selections (
                discord_id TEXT PRIMARY KEY,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def save_selected_time(discord_id: str, start_time: str, end_time: str) -> None:
    """Saves the user's selected date/time range to the database."""
    now = datetime.datetime.now(datetime.UTC)
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO time_selections (discord_id, start_time, end_time, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                updated_at = excluded.updated_at
        """,
            (discord_id, start_time, end_time, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_selected_time(discord_id: str) -> tuple[str, str] | None:
    """Retrieves the user's selected start and end times."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT start_time, end_time FROM time_selections WHERE discord_id = ?",
            (discord_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return row if row else None


def delete_selected_time(discord_id: str) -> None:
    """Deletes a user's selected time from the database."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM time_selections WHERE discord_id = ?", (discord_id,)
        )
        conn.commit()
    finally:
        conn.close()


def save_session(discord_id: str, cookies: list[dict[str, Any]]) -> None:
    """Encrypts and saves the user's cookies to the database bound to their discord_id."""
    from app.security import validate_discord_id

    clean_id = validate_discord_id(discord_id)
    user_key = get_user_encryption_key(clean_id)
    encrypted_cookies, iv, tag = encrypt_cookies(
        cookies, user_key, associated_data=clean_id.encode("utf-8")
    )
    now = datetime.datetime.now(datetime.UTC)

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_sessions (discord_id, encrypted_cookies, iv, tag, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                encrypted_cookies = excluded.encrypted_cookies,
                iv = excluded.iv,
                tag = excluded.tag,
                updated_at = excluded.updated_at
        """,
            (clean_id, encrypted_cookies, iv, tag, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(discord_id: str) -> list[dict[str, Any]] | None:
    """Retrieves and decrypts the user's cookies from the database.

    Returns None if the session does not exist, has expired, or fails authentication.
    """
    from app.security import validate_discord_id

    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError:
        return None

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT encrypted_cookies, iv, tag, updated_at FROM user_sessions WHERE discord_id = ?",
            (clean_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return None

    encrypted_cookies, iv, tag, updated_at_str = row

    # Check if session has expired (older than 14 days)
    # sqlite3 datetime format is typically text
    updated_at = datetime.datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.UTC)
    if now - updated_at > datetime.timedelta(days=14):
        # Session expired, delete it
        delete_session(clean_id)
        return None

    user_key = get_user_encryption_key(clean_id)
    try:
        return decrypt_cookies(
            encrypted_cookies,
            iv,
            tag,
            user_key,
            associated_data=clean_id.encode("utf-8"),
        )
    except Exception:
        # Fallback: try master key without associated data for backwards compatibility
        try:
            master_key = get_encryption_key()
            return decrypt_cookies(
                encrypted_cookies, iv, tag, master_key, associated_data=None
            )
        except Exception:
            # Decryption failed (e.g. wrong key or tampering), treat as invalid session
            return None


def delete_session(discord_id: str) -> None:
    """Deletes a user's session from the database."""
    from app.security import validate_discord_id

    try:
        clean_id = validate_discord_id(discord_id)
    except ValueError:
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE discord_id = ?", (clean_id,))
        conn.commit()
    finally:
        conn.close()


# Auto-initialize database on import
init_db()
