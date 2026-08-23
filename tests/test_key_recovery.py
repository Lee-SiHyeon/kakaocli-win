import hashlib
import hmac
import os
import struct

from kakaocli_win.key_recovery import (
    FILE_HEADER_SIZE,
    HMAC_SALT_MASK,
    IV_SIZE,
    KEY_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
    _candidate_offsets,
    _protect_key,
    _unprotect_key,
    verify_sqlcipher4_raw_key,
)


def make_authenticated_page(key: bytes) -> bytes:
    page = bytearray(os.urandom(PAGE_SIZE))
    salt = bytes(page[:FILE_HEADER_SIZE])
    hmac_salt = bytes(value ^ HMAC_SALT_MASK for value in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, dklen=KEY_SIZE)
    authenticated = bytes(page[FILE_HEADER_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE])
    digest = hmac.new(
        hmac_key, authenticated + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    start = PAGE_SIZE - RESERVE_SIZE + IV_SIZE
    page[start : start + len(digest)] = digest
    return bytes(page)


def test_sqlcipher4_raw_key_verification():
    key = os.urandom(KEY_SIZE)
    page = make_authenticated_page(key)
    assert verify_sqlcipher4_raw_key(page, key)
    assert not verify_sqlcipher4_raw_key(page, os.urandom(KEY_SIZE))


def test_candidate_filter_keeps_aligned_random_key():
    key = bytes(range(1, 33))
    block = b"\0" * 64 + key + b"\0" * 64
    assert 64 in set(map(int, _candidate_offsets(block, 4)))


def test_dpapi_round_trip():
    key = os.urandom(KEY_SIZE)
    assert _unprotect_key(_protect_key(key)) == key
