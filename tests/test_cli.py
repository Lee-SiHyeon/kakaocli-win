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


def test_inspect_room_argument():
    args = build_parser().parse_args(["inspect", "--room", "테스트방"])
    assert args.room == "테스트방"


def test_friends_filter_arguments():
    args = build_parser().parse_args(["--json", "friends", "--contains", "vs"])
    assert args.command == "friends"
    assert args.contains == "vs"
    assert args.include_hidden is False


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
