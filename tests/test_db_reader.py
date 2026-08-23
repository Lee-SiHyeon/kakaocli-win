import hashlib
import hmac
import os
import struct
from contextlib import contextmanager

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import kakaocli_win.db_reader as db_reader
from kakaocli_win.db_reader import SQLITE_HEADER, decrypt_sqlcipher4
from kakaocli_win.key_recovery import (
    FILE_HEADER_SIZE,
    HMAC_SALT_MASK,
    IV_SIZE,
    KEY_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
)


def encrypt_test_page(plaintext: bytes, key: bytes) -> bytes:
    salt = os.urandom(FILE_HEADER_SIZE)
    iv = os.urandom(IV_SIZE)
    payload_end = PAGE_SIZE - RESERVE_SIZE
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(plaintext[FILE_HEADER_SIZE:payload_end])
    ciphertext += encryptor.finalize()
    hmac_salt = bytes(value ^ HMAC_SALT_MASK for value in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, dklen=KEY_SIZE)
    digest = hmac.new(
        hmac_key, ciphertext + iv + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    return salt + ciphertext + iv + digest


def test_decrypt_sqlcipher4_page(tmp_path):
    key = os.urandom(KEY_SIZE)
    plaintext = bytearray(os.urandom(PAGE_SIZE))
    plaintext[:FILE_HEADER_SIZE] = SQLITE_HEADER
    plaintext[20] = 0
    encrypted = encrypt_test_page(bytes(plaintext), key)
    source = tmp_path / "source.edb"
    destination = tmp_path / "plain.sqlite"
    source.write_bytes(encrypted)

    assert decrypt_sqlcipher4(source, key, destination) == 1
    result = destination.read_bytes()
    assert result[: PAGE_SIZE - RESERVE_SIZE] == plaintext[: PAGE_SIZE - RESERVE_SIZE]
    assert result[PAGE_SIZE - RESERVE_SIZE :] == bytes(RESERVE_SIZE)


def test_read_chat_rooms_filters_and_omits_ids_by_default(tmp_path, monkeypatch):
    database = tmp_path / "rooms.sqlite"
    connection = db_reader.sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE chatRoomList (chatId INTEGER, type TEXT, chatRoomTitle TEXT, "
        "activeMembersCount INTEGER, newMessageCount INTEGER, lastUpdatedAt INTEGER)"
    )
    connection.executemany(
        "INSERT INTO chatRoomList VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "MultiChat", "바다 모임", 3, 1, 20),
            (2, "DirectChat", "친구", 2, 0, 10),
        ],
    )
    connection.commit()
    connection.close()

    @contextmanager
    def passthrough(_database, _key):
        yield database

    monkeypatch.setattr(db_reader, "temporary_plaintext_database", passthrough)
    rooms = db_reader.read_chat_rooms(
        database, b"x" * 32, contains="바다", room_type="multichat"
    )
    assert rooms == [
        {
            "title": "바다 모임",
            "type": "MultiChat",
            "members": 3,
            "unread": 1,
            "lastUpdatedAt": 20,
        }
    ]
