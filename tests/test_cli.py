import pytest

import kakaocli_win.backend as backend
from kakaocli_win.backend import KakaoError, WindowInfo
from kakaocli_win.cli import build_parser


def test_send_dry_run_arguments():
    args = build_parser().parse_args(["--json", "send", "친구", "안녕", "--dry-run"])
    assert args.json is True
    assert args.command == "send"
    assert args.room == "친구"
    assert args.message == "안녕"
    assert args.dry_run is True


def test_send_requires_message():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["send", "친구"])


def test_send_self_dry_run_arguments():
    args = build_parser().parse_args(["--json", "send-self", "메모", "--dry-run"])
    assert args.command == "send-self"
    assert args.message == "메모"
    assert args.dry_run is True
    assert args.yes is False


def test_inspect_room_argument():
    args = build_parser().parse_args(["inspect", "--room", "테스트방"])
    assert args.room == "테스트방"


def test_friends_filter_arguments():
    args = build_parser().parse_args(["--json", "friends", "--contains", "vs"])
    assert args.command == "friends"
    assert args.contains == "vs"
    assert args.include_hidden is False


def test_chat_rooms_filter_arguments():
    args = build_parser().parse_args(
        ["--json", "chat-rooms", "--contains", "바다", "--type", "MultiChat", "--limit", "5"]
    )
    assert args.command == "chat-rooms"
    assert args.contains == "바다"
    assert args.room_type == "MultiChat"
    assert args.limit == 5
    assert args.include_ids is False


def test_export_room_contacts_arguments():
    args = build_parser().parse_args(
        [
            "--json",
            "export-room-contacts",
            "동창방",
            "--output",
            "contacts.csv",
            "--exact",
        ]
    )
    assert args.command == "export-room-contacts"
    assert args.room == "동창방"
    assert args.output == "contacts.csv"
    assert args.exact is True
    assert args.allow_partial is False


def make_window(title: str, hwnd: int) -> WindowInfo:
    return WindowInfo(hwnd, title, backend.CHAT_CLASS, 380, 640, True, "chat")


def test_find_room_rejects_ambiguous_partial_match(monkeypatch):
    monkeypatch.setattr(
        backend,
        "list_rooms",
        lambda: [make_window("개발팀", 1), make_window("개발팀 공지", 2)],
    )
    with pytest.raises(KakaoError, match="여러 개"):
        backend.find_room("개발팀")


def test_find_room_exact_match(monkeypatch):
    expected = make_window("개발팀", 1)
    monkeypatch.setattr(
        backend,
        "list_rooms",
        lambda: [expected, make_window("개발팀 공지", 2)],
    )
    assert backend.find_room("개발팀", exact=True) == expected


def test_open_room_requires_manual_open_when_not_found(monkeypatch):
    monkeypatch.setattr(backend, "list_rooms", lambda: [])
    with pytest.raises(KakaoError, match="직접 독립 창으로"):
        backend.open_room("개발팀", exact=True)


def test_set_text_falls_back_to_replace_selection(monkeypatch):
    state = {"text": ""}

    def send_message(_hwnd, message, _wparam, lparam):
        if message == backend.win32con.EM_REPLACESEL:
            state["text"] = lparam

    monkeypatch.setattr(backend.win32gui, "SendMessage", send_message)
    monkeypatch.setattr(backend.win32gui, "GetWindowText", lambda _hwnd: state["text"])
    assert backend._set_text(1, "테스트") is True
    assert state["text"] == "테스트"
