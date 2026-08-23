from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

if os.name == "nt":
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()


CHAT_CLASS = "EVA_Window_Dblclk"
INPUT_CLASSES = {"RICHEDIT50W", "RichEdit50W", "RichEditD2DPT"}


class KakaoError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    width: int
    height: int
    visible: bool
    kind: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["hwnd"] = hex(self.hwnd)
        return data


def require_windows() -> None:
    if os.name != "nt":
        raise KakaoError("kakaocli-win은 Windows에서만 실행할 수 있습니다.")


def enum_children(hwnd: int) -> list[int]:
    children: list[int] = []
    win32gui.EnumChildWindows(hwnd, lambda child, _: children.append(child), None)
    return children


def _input_handles(hwnd: int) -> list[int]:
    return [
        child
        for child in enum_children(hwnd)
        if win32gui.IsWindowVisible(child)
        and (
            win32gui.GetClassName(child) in INPUT_CLASSES
            or "RICHEDIT" in win32gui.GetClassName(child).upper()
        )
    ]


def classify_window(hwnd: int, title: str, class_name: str) -> str:
    if class_name != CHAT_CLASS:
        return "other"
    if _input_handles(hwnd):
        return "chat"
    return "main" if title in {"", "카카오톡", "KakaoTalk"} else "popup"


def list_windows() -> list[WindowInfo]:
    require_windows()
    result: list[WindowInfo] = []

    def callback(hwnd: int, _: object) -> None:
        try:
            class_name = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            if "EVA" not in class_name and "카카오톡" not in title and "KakaoTalk" not in title:
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            result.append(
                WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    class_name=class_name,
                    width=max(0, right - left),
                    height=max(0, bottom - top),
                    visible=bool(win32gui.IsWindowVisible(hwnd)),
                    kind=classify_window(hwnd, title, class_name),
                )
            )
        except Exception:
            return

    win32gui.EnumWindows(callback, None)
    return sorted(result, key=lambda item: (item.kind, item.title, item.hwnd))


def list_rooms() -> list[WindowInfo]:
    return [
        window
        for window in list_windows()
        if window.kind == "chat" and window.visible and window.title.strip()
    ]


def find_main_window() -> WindowInfo | None:
    candidates = [
        window
        for window in list_windows()
        if window.kind == "main" and window.width > 0 and window.height > 0
    ]
    return max(candidates, key=lambda item: item.width * item.height, default=None)


def find_room(room: str, *, exact: bool = False) -> WindowInfo | None:
    needle = room.casefold().strip()
    matches = []
    for window in list_rooms():
        title = window.title.casefold().strip()
        if (exact and title == needle) or (not exact and needle in title):
            matches.append(window)
    if len(matches) > 1 and not exact:
        names = ", ".join(repr(item.title) for item in matches)
        raise KakaoError(f"채팅방 이름이 여러 개와 일치합니다: {names}. --exact를 사용하세요.")
    return matches[0] if matches else None


def _focus(hwnd: int) -> None:
    root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or hwnd
    win32gui.ShowWindow(root, win32con.SW_SHOW)
    win32gui.ShowWindow(root, win32con.SW_RESTORE)
    current_tid = win32api.GetCurrentThreadId()
    target_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
    attached = False
    try:
        if current_tid != target_tid:
            attached = bool(ctypes.windll.user32.AttachThreadInput(current_tid, target_tid, True))
        ctypes.windll.user32.BringWindowToTop(root)
        ctypes.windll.user32.SetForegroundWindow(root)
        ctypes.windll.user32.SetFocus(hwnd)
    finally:
        if attached:
            ctypes.windll.user32.AttachThreadInput(current_tid, target_tid, False)


def _press(vk: int, modifiers: tuple[int, ...] = ()) -> None:
    for modifier in modifiers:
        win32api.keybd_event(modifier, 0, 0, 0)
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    for modifier in reversed(modifiers):
        win32api.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)


def _set_text(hwnd: int, text: str) -> bool:
    win32gui.SendMessage(hwnd, win32con.WM_SETTEXT, 0, text)
    if win32gui.GetWindowText(hwnd) == text:
        return True

    # Recent KakaoTalk RichEdit controls can reject WM_SETTEXT while still
    # accepting the normal RichEdit replace-selection operation.
    win32gui.SendMessage(hwnd, win32con.EM_SETSEL, 0, -1)
    win32gui.SendMessage(hwnd, win32con.EM_REPLACESEL, True, text)
    if win32gui.GetWindowText(hwnd) == text:
        return True

    _focus(hwnd)
    _press(ord("A"), (win32con.VK_CONTROL,))
    # KakaoTalk intentionally returns an empty value for this control even
    # while typed text is visibly present. SendInput's accepted-event count is
    # therefore the only programmatic confirmation available before Enter.
    return _send_unicode_input(text)


def _send_unicode_input(text: str) -> bool:
    """Type Unicode text through SendInput without touching the clipboard."""
    ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        ]

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [
            ("ki", KeyboardInput),
            ("mi", MouseInput),
            ("hi", HardwareInput),
        ]

    class Input(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", ctypes.c_ulong), ("union", InputUnion)]

    key_events = []
    encoded = text.encode("utf-16-le")
    for offset in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[offset : offset + 2], "little")
        key_events.append(Input(1, InputUnion(ki=KeyboardInput(0, unit, 0x0004, 0, 0))))
        key_events.append(Input(1, InputUnion(ki=KeyboardInput(0, unit, 0x0006, 0, 0))))
    if not key_events:
        return True
    inputs = (Input * len(key_events))(*key_events)
    sent = ctypes.windll.user32.SendInput(len(inputs), inputs, ctypes.sizeof(Input))
    return sent == len(inputs)


def open_room(room: str, *, exact: bool = False, timeout: float = 3.0) -> WindowInfo:
    existing = find_room(room, exact=exact)
    if existing:
        _focus(existing.hwnd)
        return existing

    raise KakaoError(
        f"안전한 자동 검색을 지원하지 않는 카카오톡 버전입니다. "
        f"PC 카카오톡에서 {room!r} 방을 직접 독립 창으로 연 뒤 다시 실행하세요."
    )


def send_message(room: str, message: str, *, exact: bool = False) -> WindowInfo:
    if not message:
        raise KakaoError("빈 메시지는 전송할 수 없습니다.")
    window = open_room(room, exact=exact)
    inputs = _input_handles(window.hwnd)
    if not inputs:
        raise KakaoError("메시지 입력창을 찾지 못했습니다.")

    input_hwnd = inputs[-1]
    _focus(input_hwnd)
    if not _set_text(input_hwnd, message):
        raise KakaoError("메시지 입력에 실패했습니다. 전송하지 않았습니다.")
    _press(win32con.VK_RETURN)
    time.sleep(0.2)
    remaining = win32gui.GetWindowText(input_hwnd)
    if remaining == message:
        raise KakaoError("Enter 입력 후에도 메시지가 남아 있습니다. 전송 여부를 직접 확인하세요.")
    return window


def read_visible(room: str, *, exact: bool = False, timeout: float = 1.5) -> tuple[WindowInfo, str]:
    import win32clipboard

    window = open_room(room, exact=exact)
    list_candidates = [
        child
        for child in enum_children(window.hwnd)
        if "LIST" in win32gui.GetClassName(child).upper()
    ]
    if not list_candidates:
        raise KakaoError("대화 목록 컨트롤을 찾지 못했습니다. `kakaocli inspect --room`을 실행하세요.")

    target = max(
        list_candidates,
        key=lambda hwnd: max(0, win32gui.GetWindowRect(hwnd)[2] - win32gui.GetWindowRect(hwnd)[0])
        * max(0, win32gui.GetWindowRect(hwnd)[3] - win32gui.GetWindowRect(hwnd)[1]),
    )
    _focus(target)
    sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
    _press(ord("A"), (win32con.VK_CONTROL,))
    _press(ord("C"), (win32con.VK_CONTROL,))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ctypes.windll.user32.GetClipboardSequenceNumber() != sequence:
            break
        time.sleep(0.05)
    else:
        raise KakaoError("화면의 대화 내용을 복사하지 못했습니다.")

    try:
        win32clipboard.OpenClipboard()
        text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    except Exception as exc:
        raise KakaoError("클립보드에서 대화 텍스트를 읽지 못했습니다.") from exc
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
    return window, text.strip()


def inspect_tree(room: str | None = None) -> list[dict]:
    window = find_room(room) if room else find_main_window()
    if not window:
        raise KakaoError("검사할 카카오톡 창을 찾지 못했습니다.")
    rows = []
    for child in enum_children(window.hwnd):
        left, top, right, bottom = win32gui.GetWindowRect(child)
        rows.append(
            {
                "hwnd": hex(child),
                "class_name": win32gui.GetClassName(child),
                "text": win32gui.GetWindowText(child),
                "visible": bool(win32gui.IsWindowVisible(child)),
                "rect": [left, top, right, bottom],
            }
        )
    return rows


def find_executable() -> Path | None:
    require_windows()
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Kakao" / "KakaoTalk" / "KakaoTalk.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Kakao" / "KakaoTalk" / "KakaoTalk.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Kakao" / "KakaoTalk" / "KakaoTalk.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def start_kakaotalk() -> Path:
    executable = find_executable()
    if not executable:
        raise KakaoError("KakaoTalk.exe를 찾지 못했습니다. PC 카카오톡을 먼저 설치하세요.")
    subprocess.Popen([str(executable)], close_fds=True)
    return executable


def doctor() -> dict:
    require_windows()
    executable = find_executable()
    windows = list_windows()
    main = find_main_window()
    rooms = list_rooms()
    return {
        "ok": bool(main),
        "platform": os.name,
        "executable": str(executable) if executable else None,
        "installed": executable is not None,
        "running": bool(windows),
        "main_window_found": main is not None,
        "open_rooms": [room.title for room in rooms],
        "next": (
            "준비 완료"
            if main
            else "PC 카카오톡을 설치하고 로그인한 뒤 메인 창을 열어 두세요."
        ),
    }
