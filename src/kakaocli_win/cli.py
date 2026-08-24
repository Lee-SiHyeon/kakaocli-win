from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .backend import (
    KakaoError,
    doctor,
    inspect_tree,
    list_rooms,
    list_windows,
    open_room,
    read_visible,
    send_message,
    start_kakaotalk,
)


def emit(data: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, str):
        print(data)
    elif isinstance(data, list):
        for item in data:
            print(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))
    else:
        for key, value in data.items():
            print(f"{key}: {value}")


def confirm_send(room: str, message: str, *, skip: bool) -> bool:
    if skip:
        return True
    print(f"전송 대상: {room}\n메시지: {message}", file=sys.stderr)
    return input("이대로 전송할까요? [y/N] ").strip().casefold() in {"y", "yes"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kakaocli", description="비공식 Windows 카카오톡 CLI")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="설치 및 실행 상태 점검")
    sub.add_parser("start", help="PC 카카오톡 실행")
    sub.add_parser("windows", help="감지된 카카오톡 창 출력")
    sub.add_parser("rooms", help="현재 독립 창으로 열린 채팅방 출력")

    open_parser = sub.add_parser("open", help="채팅방 검색 및 열기")
    open_parser.add_argument("room")
    open_parser.add_argument("--exact", action="store_true")

    read_parser = sub.add_parser("read", help="열린 화면에 보이는 대화 복사")
    read_parser.add_argument("room")
    read_parser.add_argument("--exact", action="store_true")

    send_parser = sub.add_parser("send", help="채팅방에 메시지 전송")
    send_parser.add_argument("room")
    send_parser.add_argument("message")
    send_parser.add_argument("--exact", action="store_true")
    send_parser.add_argument("--yes", action="store_true", help="확인 질문 생략")
    send_parser.add_argument("--dry-run", action="store_true", help="대상과 내용을 출력하고 전송하지 않음")

    send_self_parser = sub.add_parser(
        "send-self", help="DB에서 나와의 채팅을 찾아 메시지 전송"
    )
    send_self_parser.add_argument("message")
    send_self_parser.add_argument("--yes", action="store_true", help="확인 질문 생략")
    send_self_parser.add_argument(
        "--dry-run", action="store_true", help="대상과 내용을 출력하고 전송하지 않음"
    )

    inspect_parser = sub.add_parser("inspect", help="호환성 진단용 자식 컨트롤 출력")
    inspect_parser.add_argument("--room", help="채팅방 창 검사; 생략 시 메인 창 검사")

    recover_parser = sub.add_parser("recover-key", help="실행 중인 카카오톡 메모리에서 DB 키 복구")
    recover_parser.add_argument("--db", help="대상 .edb 경로; 생략 시 최신 TalkUserDB.edb")
    recover_parser.add_argument("--pid", type=int, help="KakaoTalk.exe PID")
    recover_parser.add_argument("--stride", type=int, default=4, choices=[1, 2, 4, 8, 16])
    recover_parser.add_argument("--timeout", type=float, default=120.0, help="검색 제한 시간(초)")
    recover_parser.add_argument("--no-store", action="store_true", help="검증만 하고 DPAPI 저장하지 않음")
    sub.add_parser("key-status", help="DPAPI 키 저장소 상태 확인")

    friends_parser = sub.add_parser("friends", help="로컬 DB에서 친구 목록 조회")
    friends_parser.add_argument("--contains", help="표시 이름에 포함된 문자열")
    friends_parser.add_argument("--include-hidden", action="store_true", help="숨김 친구 포함")

    chat_rooms_parser = sub.add_parser(
        "chat-rooms", help="로컬 DB에서 채팅방 목록 조회(메시지 본문 제외)"
    )
    chat_rooms_parser.add_argument("--contains", help="방 제목에 포함된 문자열")
    chat_rooms_parser.add_argument("--type", dest="room_type", help="방 종류(예: MultiChat)")
    chat_rooms_parser.add_argument("--limit", type=int, help="최대 출력 개수")
    chat_rooms_parser.add_argument(
        "--include-ids", action="store_true", help="JSON 출력에 로컬 chatId 포함"
    )

    contacts_parser = sub.add_parser(
        "export-room-contacts",
        help="DB에 캐시된 채팅방 참여자 이름과 연락처를 CSV로 저장",
    )
    contacts_parser.add_argument("room", help="채팅방 제목")
    contacts_parser.add_argument("--output", required=True, help="저장할 CSV 경로")
    contacts_parser.add_argument("--exact", action="store_true", help="방 제목 완전 일치")
    contacts_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="참여자 캐시가 불완전해도 부분 목록 저장",
    )

    schema_parser = sub.add_parser("db-schema", help="복호화된 DB의 테이블 구조만 조회")
    schema_parser.add_argument("--db", help="대상 .edb 경로; 생략 시 TalkUserDB.edb")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "start":
            result = {"started": True, "executable": str(start_kakaotalk())}
        elif args.command == "windows":
            result = [window.to_dict() for window in list_windows()]
        elif args.command == "rooms":
            result = [window.to_dict() for window in list_rooms()]
        elif args.command == "open":
            result = {"opened": open_room(args.room, exact=args.exact).to_dict()}
        elif args.command == "read":
            window, text = read_visible(args.room, exact=args.exact)
            result = {"room": window.title, "text": text}
        elif args.command == "inspect":
            result = inspect_tree(args.room)
        elif args.command == "recover-key":
            from .key_recovery import (
                default_database,
                recover_key_from_process,
                store_recovered_key,
            )

            database = Path(args.db) if args.db else default_database()
            recovered = recover_key_from_process(
                database,
                pid=args.pid,
                stride=args.stride,
                timeout=args.timeout,
            )
            if args.no_store:
                result = {
                    "stored": False,
                    "database": str(recovered.database),
                    "fingerprint": recovered.fingerprint,
                    "stats": recovered.stats.__dict__,
                }
            else:
                result = store_recovered_key(recovered)
        elif args.command == "key-status":
            from .key_recovery import key_store_status

            result = key_store_status()
        elif args.command == "friends":
            from .db_reader import read_friends
            from .key_recovery import default_database, load_stored_key

            database = default_database()
            friends = read_friends(
                database,
                load_stored_key(database),
                contains=args.contains,
                include_hidden=args.include_hidden,
            )
            result = friends if args.json else [friend["name"] for friend in friends]
        elif args.command == "chat-rooms":
            from .db_reader import read_chat_rooms
            from .key_recovery import (
                default_chat_list_database,
                load_stored_key,
            )

            database = default_chat_list_database()
            rooms = read_chat_rooms(
                database,
                load_stored_key(database),
                contains=args.contains,
                room_type=args.room_type,
                limit=args.limit,
                include_ids=args.include_ids,
            )
            result = rooms if args.json else [room["title"] for room in rooms]
        elif args.command == "export-room-contacts":
            from .db_reader import read_room_contacts
            from .key_recovery import (
                default_chat_list_database,
                default_database,
                load_stored_key,
            )

            chat_database = default_chat_list_database()
            user_database = default_database()
            export = read_room_contacts(
                chat_database,
                load_stored_key(chat_database),
                user_database,
                load_stored_key(user_database),
                args.room,
                exact=args.exact,
            )
            if not export["complete"] and not args.allow_partial:
                raise KakaoError(
                    "참여자 캐시가 불완전합니다: "
                    f"방 표시 {export['expectedMembers']}명, 캐시 {export['cachedMembers']}명. "
                    "부분 저장을 원하면 --allow-partial을 사용하세요."
                )
            destination = Path(args.output).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            try:
                with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["이름", "전화번호"])
                    writer.writerows(
                        (contact["name"], contact["phone"])
                        for contact in export["contacts"]
                    )
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            result = {
                "saved": True,
                "output": str(destination),
                "room": export["room"],
                "expectedMembers": export["expectedMembers"],
                "exportedMembers": export["cachedMembers"],
                "phoneNumbers": sum(
                    bool(contact["phone"]) for contact in export["contacts"]
                ),
                "complete": export["complete"],
            }
        elif args.command == "db-schema":
            from .db_reader import read_schema
            from .key_recovery import default_database, load_stored_key

            database = Path(args.db).resolve() if args.db else default_database()
            result = read_schema(database, load_stored_key(database))
        elif args.command == "send-self":
            from .db_reader import read_chat_rooms
            from .key_recovery import default_chat_list_database, load_stored_key

            database = default_chat_list_database()
            memo_rooms = read_chat_rooms(
                database,
                load_stored_key(database),
                room_type="MemoChat",
                limit=2,
            )
            if len(memo_rooms) != 1 or not memo_rooms[0]["title"]:
                raise KakaoError("나와의 채팅방을 하나로 식별하지 못했습니다.")
            room = memo_rooms[0]["title"]
            preview = {"room": room, "message": args.message, "exact": True}
            if args.dry_run:
                result = {"sent": False, "dry_run": True, **preview}
            else:
                if not confirm_send(room, args.message, skip=args.yes):
                    emit({"sent": False, "cancelled": True}, as_json=args.json)
                    return 2
                window = send_message(room, args.message, exact=True)
                result = {"sent": True, "room": window.title, "message": args.message}
        elif args.command == "send":
            preview = {"room": args.room, "message": args.message, "exact": args.exact}
            if args.dry_run:
                result = {"sent": False, "dry_run": True, **preview}
            else:
                if not confirm_send(args.room, args.message, skip=args.yes):
                    emit({"sent": False, "cancelled": True}, as_json=args.json)
                    return 2
                window = send_message(args.room, args.message, exact=args.exact)
                result = {"sent": True, "room": window.title, "message": args.message}
        else:
            parser.error("알 수 없는 명령")
            return 2
        emit(result, as_json=args.json)
        return 0
    except KakaoError as exc:
        error = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("취소했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
