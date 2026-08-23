from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import hashlib
import hmac
import json
import os
import struct
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .backend import KakaoError, require_windows


PAGE_SIZE = 4096
FILE_HEADER_SIZE = 16
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE_SIZE = 80
KEY_SIZE = 32
HMAC_SALT_MASK = 0x3A

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100


class MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class MemoryRegion:
    base: int
    size: int
    protect: int
    kind: int


@dataclass
class RecoveryStats:
    pid: int
    database: str
    regions_seen: int = 0
    regions_scanned: int = 0
    bytes_scanned: int = 0
    candidates_checked: int = 0
    read_failures: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class RecoveredKey:
    database: Path
    pid: int
    key: bytes
    stats: RecoveryStats

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.key).hexdigest()[:16]


def verify_sqlcipher4_raw_key(page_one: bytes, candidate: bytes) -> bool:
    """Verify a 32-byte raw key against SQLCipher 4 page 1 HMAC."""
    if len(page_one) != PAGE_SIZE or len(candidate) != KEY_SIZE:
        return False
    salt = page_one[:FILE_HEADER_SIZE]
    hmac_salt = bytes(value ^ HMAC_SALT_MASK for value in salt)
    hmac_key = hashlib.pbkdf2_hmac(
        "sha512", candidate, hmac_salt, 2, dklen=KEY_SIZE
    )
    authenticated = page_one[
        FILE_HEADER_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE
    ]
    expected = page_one[
        PAGE_SIZE - RESERVE_SIZE + IV_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE + HMAC_SIZE
    ]
    actual = hmac.new(
        hmac_key, authenticated + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    return hmac.compare_digest(actual, expected)


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MemoryBasicInformation),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    return kernel32


def _process_name(pid: int) -> str | None:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)


def find_kakaotalk_pids() -> list[int]:
    require_windows()
    import win32process

    return [
        pid
        for pid in win32process.EnumProcesses()
        if pid and (_process_name(pid) or "").casefold() == "kakaotalk.exe"
    ]


def _open_kakaotalk_process(pid: int):
    if (_process_name(pid) or "").casefold() != "kakaotalk.exe":
        raise KakaoError(f"PID {pid}는 KakaoTalk.exe가 아닙니다.")
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        code = ctypes.get_last_error()
        raise KakaoError(
            f"KakaoTalk.exe 메모리를 읽을 수 없습니다 (Windows 오류 {code}). "
            "필요하면 PowerShell을 관리자 권한으로 실행하세요."
        )
    return kernel32, handle


def _memory_regions(kernel32, handle) -> list[MemoryRegion]:
    regions: list[MemoryRegion] = []
    address = 0
    info = MemoryBasicInformation()
    while True:
        result = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)
        )
        if not result:
            break
        base = int(info.BaseAddress or 0)
        size = int(info.RegionSize)
        if size <= 0:
            break
        if (
            info.State == MEM_COMMIT
            and info.Type == MEM_PRIVATE
            and not (info.Protect & PAGE_GUARD)
            and not (info.Protect & PAGE_NOACCESS)
        ):
            regions.append(MemoryRegion(base, size, int(info.Protect), int(info.Type)))
        next_address = base + size
        if next_address <= address:
            break
        address = next_address
    # Current KakaoTalk builds keep active SQLCipher material in medium/large
    # private heap segments. Prioritize those, then fall back to small heaps.
    return sorted(regions, key=lambda item: (item.size < 800_000, item.size))


def _read_memory(kernel32, handle, address: int, size: int) -> bytes | None:
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    ok = kernel32.ReadProcessMemory(
        handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(read),
    )
    if not ok or read.value == 0:
        return None
    return buffer.raw[: read.value]


def _candidate_offsets(data: bytes, stride: int) -> np.ndarray:
    """Vectorized low-cost filter for random-looking 32-byte key material."""
    if len(data) < KEY_SIZE:
        return np.empty(0, dtype=np.int64)
    values = np.frombuffer(data, dtype=np.uint8)
    zero_prefix = np.empty(len(values) + 1, dtype=np.int64)
    zero_prefix[0] = 0
    np.cumsum(values == 0, out=zero_prefix[1:])
    zero_counts = zero_prefix[KEY_SIZE:] - zero_prefix[:-KEY_SIZE]

    printable = ((values >= 0x20) & (values <= 0x7E)).astype(np.uint8)
    printable_prefix = np.empty(len(values) + 1, dtype=np.int64)
    printable_prefix[0] = 0
    np.cumsum(printable, out=printable_prefix[1:])
    printable_counts = printable_prefix[KEY_SIZE:] - printable_prefix[:-KEY_SIZE]

    sampled = np.arange(0, len(zero_counts), stride, dtype=np.int64)
    mask = (zero_counts[sampled] <= 4) & (printable_counts[sampled] <= 27)
    return sampled[mask]


def recover_key_from_process(
    database: Path,
    *,
    pid: int | None = None,
    stride: int = 4,
    timeout: float = 120.0,
    chunk_size: int = 1_048_576,
) -> RecoveredKey:
    require_windows()
    database = database.resolve()
    if not database.is_file():
        raise KakaoError(f"DB 파일을 찾지 못했습니다: {database}")
    with database.open("rb") as stream:
        page_one = stream.read(PAGE_SIZE)
    if len(page_one) != PAGE_SIZE:
        raise KakaoError("DB 첫 페이지가 4096바이트보다 작습니다.")
    if stride not in {1, 2, 4, 8, 16}:
        raise KakaoError("stride는 1, 2, 4, 8, 16 중 하나여야 합니다.")

    pids = [pid] if pid else find_kakaotalk_pids()
    if not pids:
        raise KakaoError("실행 중인 KakaoTalk.exe를 찾지 못했습니다.")
    selected_pid = pids[0]
    stats = RecoveryStats(pid=selected_pid, database=str(database))
    started = time.monotonic()
    kernel32, handle = _open_kakaotalk_process(selected_pid)
    try:
        regions = _memory_regions(kernel32, handle)
        stats.regions_seen = len(regions)
        for region in regions:
            if time.monotonic() - started > timeout:
                raise KakaoError(
                    f"키 검색 제한 시간 {timeout:g}초를 초과했습니다. "
                    "대상 카카오톡 화면을 연 뒤 다시 시도하거나 --stride 1을 사용하세요."
                )
            overlap = b""
            consumed = 0
            while consumed < region.size:
                size = min(chunk_size, region.size - consumed)
                block = _read_memory(kernel32, handle, region.base + consumed, size)
                if block is None:
                    stats.read_failures += 1
                    break
                data = overlap + block
                data_base = region.base + consumed - len(overlap)
                stats.bytes_scanned += len(block)
                offsets = _candidate_offsets(data, stride)
                for offset_value in offsets:
                    offset = int(offset_value)
                    candidate = data[offset : offset + KEY_SIZE]
                    # Pointer-heavy heap data can pass vector filters; this
                    # final diversity check is cheap after vector reduction.
                    if len(set(candidate)) < 18:
                        continue
                    stats.candidates_checked += 1
                    if verify_sqlcipher4_raw_key(page_one, candidate):
                        stats.regions_scanned += 1
                        stats.elapsed_seconds = round(time.monotonic() - started, 3)
                        return RecoveredKey(database, selected_pid, candidate, stats)
                overlap = data[-(KEY_SIZE - 1) :]
                consumed += size
            stats.regions_scanned += 1
    finally:
        kernel32.CloseHandle(handle)
    stats.elapsed_seconds = round(time.monotonic() - started, 3)
    raise KakaoError(
        "메모리에서 검증 가능한 키를 찾지 못했습니다. 카카오톡에서 대상 데이터가 "
        "사용되는 화면을 연 뒤 다시 시도하세요. 필요하면 --stride 1로 정밀 검색하세요."
    )


def default_database() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Kakao" / "KakaoTalk" / "users"
    candidates = [
        path
        for path in root.glob("*/TalkUserDB.edb")
        if "_backup_" not in str(path.parent)
    ]
    if not candidates:
        raise KakaoError("TalkUserDB.edb를 찾지 못했습니다.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _key_store_path() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "kakaocli-win" / "keys.json"


def _protect_key(key: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptProtectData(
        key,
        "kakaocli-win SQLCipher key",
        None,
        None,
        None,
        0x1,
    )


def _unprotect_key(protected: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptUnprotectData(protected, None, None, None, 0x1)[1]


def store_recovered_key(result: RecoveredKey) -> dict:
    store_path = _key_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    protected = _protect_key(result.key)
    store = {"version": 1, "keys": {}}
    if store_path.is_file():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    identity = hashlib.sha256(str(result.database).casefold().encode("utf-8")).hexdigest()
    store.setdefault("keys", {})[identity] = {
        "database": str(result.database),
        "protected_key": base64.b64encode(protected).decode("ascii"),
        "fingerprint": result.fingerprint,
        "recovered_at": datetime.now(timezone.utc).isoformat(),
        "pid": result.pid,
    }
    temporary = store_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, store_path)
    return {
        "stored": True,
        "store": str(store_path),
        "database": str(result.database),
        "fingerprint": result.fingerprint,
        "stats": asdict(result.stats),
    }


def load_stored_key(database: Path) -> bytes:
    path = _key_store_path()
    if not path.is_file():
        raise KakaoError("DPAPI 키 저장소가 없습니다. recover-key를 먼저 실행하세요.")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
        identity = hashlib.sha256(
            str(database.resolve()).casefold().encode("utf-8")
        ).hexdigest()
        encoded = store["keys"][identity]["protected_key"]
        key = _unprotect_key(base64.b64decode(encoded))
    except (OSError, ValueError, KeyError) as exc:
        raise KakaoError(f"저장된 키를 불러오지 못했습니다: {exc}") from exc
    if len(key) != KEY_SIZE:
        raise KakaoError("저장된 키의 길이가 올바르지 않습니다.")
    return key


def key_store_status() -> dict:
    path = _key_store_path()
    if not path.is_file():
        return {"store": str(path), "exists": False, "keys": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KakaoError(f"키 저장소를 읽지 못했습니다: {exc}") from exc
    keys = []
    for item in data.get("keys", {}).values():
        keys.append(
            {
                "database": item.get("database"),
                "fingerprint": item.get("fingerprint"),
                "recovered_at": item.get("recovered_at"),
                "pid": item.get("pid"),
            }
        )
    return {"store": str(path), "exists": True, "keys": keys}
