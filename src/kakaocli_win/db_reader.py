from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import struct
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .backend import KakaoError
from .key_recovery import (
    FILE_HEADER_SIZE,
    HMAC_SALT_MASK,
    HMAC_SIZE,
    IV_SIZE,
    KEY_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
)

SQLITE_HEADER = b"SQLite format 3\0"


def _hmac_key(page_one: bytes, key: bytes) -> bytes:
    salt = page_one[:FILE_HEADER_SIZE]
    hmac_salt = bytes(value ^ HMAC_SALT_MASK for value in salt)
    return hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, dklen=KEY_SIZE)


def _verify_page(page: bytes, page_number: int, hmac_key: bytes) -> bool:
    payload_end = PAGE_SIZE - RESERVE_SIZE
    iv = page[payload_end : payload_end + IV_SIZE]
    expected = page[
        payload_end + IV_SIZE : payload_end + IV_SIZE + HMAC_SIZE
    ]
    offset = FILE_HEADER_SIZE if page_number == 1 else 0
    authenticated = page[offset:payload_end] + iv
    actual = hmac.new(
        hmac_key, authenticated + struct.pack("<I", page_number), hashlib.sha512
    ).digest()
    return hmac.compare_digest(actual, expected)


def decrypt_sqlcipher4(database: Path, key: bytes, destination: Path) -> int:
    """Decrypt a SQLCipher 4 database using a validated 32-byte raw key."""
    database = database.resolve()
    destination = destination.resolve()
    if len(key) != KEY_SIZE:
        raise KakaoError("DB 키 길이가 올바르지 않습니다.")
    if not database.is_file():
        raise KakaoError(f"DB 파일을 찾지 못했습니다: {database}")
    size = database.stat().st_size
    if size < PAGE_SIZE or size % PAGE_SIZE:
        raise KakaoError("DB 크기가 SQLCipher 4096바이트 페이지 형식과 맞지 않습니다.")

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    page_count = size // PAGE_SIZE
    try:
        with database.open("rb") as source, temporary.open("wb") as target:
            page_one = source.read(PAGE_SIZE)
            hmac_key = _hmac_key(page_one, key)
            source.seek(0)
            for page_number in range(1, page_count + 1):
                page = source.read(PAGE_SIZE)
                if len(page) != PAGE_SIZE:
                    raise KakaoError(f"DB {page_number}페이지를 완전히 읽지 못했습니다.")
                if not _verify_page(page, page_number, hmac_key):
                    raise KakaoError(f"DB {page_number}페이지 HMAC 검증에 실패했습니다.")

                payload_end = PAGE_SIZE - RESERVE_SIZE
                offset = FILE_HEADER_SIZE if page_number == 1 else 0
                encrypted = page[offset:payload_end]
                iv = page[payload_end : payload_end + IV_SIZE]
                decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
                plaintext = decryptor.update(encrypted) + decryptor.finalize()

                output = bytearray(PAGE_SIZE)
                if page_number == 1:
                    output[:FILE_HEADER_SIZE] = SQLITE_HEADER
                output[offset:payload_end] = plaintext
                if page_number == 1:
                    # Plain SQLite must see no codec-reserved bytes. The
                    # decrypted b-tree payload remains valid before this area.
                    output[20] = 0
                target.write(output)
        os.replace(temporary, destination)
        return page_count
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@contextmanager
def temporary_plaintext_database(database: Path, key: bytes) -> Iterator[Path]:
    handle, raw_path = tempfile.mkstemp(prefix="kakaocli-", suffix=".sqlite")
    os.close(handle)
    path = Path(raw_path)
    try:
        decrypt_sqlcipher4(database, key, path)
        yield path
    finally:
        for candidate in (
            path,
            path.with_suffix(path.suffix + ".tmp"),
            Path(str(path) + "-wal"),
            Path(str(path) + "-shm"),
            Path(str(path) + "-journal"),
        ):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass


def read_schema(database: Path, key: bytes) -> list[dict]:
    with temporary_plaintext_database(database, key) as plaintext:
        connection = sqlite3.connect(
            f"file:{plaintext}?mode=ro&immutable=1", uri=True
        )
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            result = []
            for (name,) in tables:
                escaped = name.replace('"', '""')
                columns = [
                    row[1]
                    for row in connection.execute(f'PRAGMA table_info("{escaped}")')
                ]
                count = connection.execute(
                    f'SELECT COUNT(*) FROM "{escaped}"'
                ).fetchone()[0]
                result.append({"table": name, "columns": columns, "rows": count})
            return result
        finally:
            connection.close()


def read_friends(
    database: Path,
    key: bytes,
    *,
    contains: str | None = None,
    include_hidden: bool = False,
) -> list[dict]:
    with temporary_plaintext_database(database, key) as plaintext:
        connection = sqlite3.connect(
            f"file:{plaintext}?mode=ro&immutable=1", uri=True
        )
        try:
            conditions = ["type = 1", "coalesce(purged, 0) = 0"]
            parameters: list[object] = []
            if not include_hidden:
                conditions.append("coalesce(hidden, 0) = 0")
            if contains:
                conditions.append(
                    "lower(coalesce(friendNickName, '') || ' ' || "
                    "coalesce(nickName, '')) LIKE ?"
                )
                parameters.append(f"%{contains.casefold()}%")

            rows = connection.execute(
                "SELECT userId, "
                "coalesce(nullif(friendNickName, ''), nickName, '') AS displayName, "
                "coalesce(hidden, 0), coalesce(favorite, 0) "
                "FROM talkUser WHERE "
                + " AND ".join(conditions)
                + " ORDER BY displayName COLLATE NOCASE",
                parameters,
            ).fetchall()
            return [
                {
                    "name": display_name,
                    "hidden": bool(hidden),
                    "favorite": bool(favorite),
                }
                for _user_id, display_name, hidden, favorite in rows
                if display_name
            ]
        finally:
            connection.close()


def read_chat_rooms(
    database: Path,
    key: bytes,
    *,
    contains: str | None = None,
    room_type: str | None = None,
    limit: int | None = None,
    include_ids: bool = False,
) -> list[dict]:
    """Read room metadata from chatListInfo without reading message bodies."""
    if limit is not None and limit < 1:
        raise KakaoError("--limit은 1 이상이어야 합니다.")

    with temporary_plaintext_database(database, key) as plaintext:
        connection = sqlite3.connect(
            f"file:{plaintext}?mode=ro&immutable=1", uri=True
        )
        try:
            rows = connection.execute(
                "SELECT chatId, type, chatRoomTitle, activeMembersCount, "
                "newMessageCount, lastUpdatedAt "
                "FROM chatRoomList ORDER BY lastUpdatedAt DESC"
            ).fetchall()

            needle = contains.casefold() if contains else None
            expected_type = room_type.casefold() if room_type else None
            result: list[dict] = []
            for chat_id, kind, title, members, unread, updated_at in rows:
                title = title or ""
                kind = kind or ""
                if needle and needle not in title.casefold():
                    continue
                if expected_type and kind.casefold() != expected_type:
                    continue
                item = {
                    "title": title,
                    "type": kind,
                    "members": int(members or 0),
                    "unread": int(unread or 0),
                    "lastUpdatedAt": updated_at,
                }
                if include_ids:
                    item["chatId"] = chat_id
                result.append(item)
                if limit is not None and len(result) >= limit:
                    break
            return result
        finally:
            connection.close()
