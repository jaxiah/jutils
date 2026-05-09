#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any


DEFAULT_PROMPT = "Reply with exactly: pong"
DEFAULT_STATE_FILE = "codex_auto_ping_state.json"
DEFAULT_LIMIT_ID = "codex"
WINDOW_HOURS = 5
MANUAL_TIME_FORMAT = "%Y-%m-%d-%H-%M"
MANUAL_TIME_SHORT_FORMAT = "%H:%M"


def now_local() -> datetime:
    return datetime.now().astimezone()


def format_ts(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone offset, for example +08:00")
    return parsed


def parse_manual_local_ts(value: str) -> datetime:
    local_tz = now_local().tzinfo
    try:
        parsed = datetime.strptime(value, MANUAL_TIME_FORMAT)
        return parsed.replace(tzinfo=local_tz)
    except ValueError:
        pass

    try:
        parsed_short = datetime.strptime(value, MANUAL_TIME_SHORT_FORMAT)
    except ValueError as exc:
        raise ValueError(
            "manual time must use 'YYYY-MM-DD-HH-MM' or 'HH:MM', "
            "for example 2026-05-09-15-09 or 15:09"
        ) from exc

    now = now_local()
    candidate = now.replace(
        hour=parsed_short.hour,
        minute=parsed_short.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.replace(tzinfo=local_tz)


def epoch_to_local(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=now_local().tzinfo)


def describe_ts(value: datetime | None) -> str:
    return format_ts(value) if value is not None else "<none>"


def parse_time_of_day(value: str) -> dt_time:
    try:
        return datetime.strptime(value, MANUAL_TIME_SHORT_FORMAT).time()
    except ValueError as exc:
        raise ValueError(f"time must use {MANUAL_TIME_SHORT_FORMAT!r}, for example 10:00") from exc


def combine_local(day: date, time_value: dt_time) -> datetime:
    return datetime.combine(day, time_value, tzinfo=now_local().tzinfo)


def next_daily_start(now: datetime, start_time: dt_time) -> datetime:
    today_start = combine_local(now.date(), start_time)
    if now < today_start:
        return today_start
    return combine_local(now.date() + timedelta(days=1), start_time)


def in_daily_quiet_hours(now: datetime, start_time: dt_time) -> bool:
    return now.time() < start_time


def resolve_codex_bin(user_value: str) -> str:
    if Path(user_value).exists():
        return str(Path(user_value))

    for candidate in (user_value, f"{user_value}.cmd", "codex.cmd", "codex"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise FileNotFoundError(f"Could not find Codex CLI executable from {user_value!r}")


@dataclass
class State:
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_known_reset_at: datetime | None = None
    last_exit_code: int | None = None
    last_stdout: str | None = None
    last_stderr: str | None = None

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls()

        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            last_success_at=parse_ts(raw["last_success_at"]) if raw.get("last_success_at") else None,
            last_attempt_at=parse_ts(raw["last_attempt_at"]) if raw.get("last_attempt_at") else None,
            last_known_reset_at=parse_ts(raw["last_known_reset_at"]) if raw.get("last_known_reset_at") else None,
            last_exit_code=raw.get("last_exit_code"),
            last_stdout=raw.get("last_stdout"),
            last_stderr=raw.get("last_stderr"),
        )

    def save(self, path: Path) -> None:
        payload: dict[str, Any] = {
            "last_success_at": format_ts(self.last_success_at) if self.last_success_at else None,
            "last_attempt_at": format_ts(self.last_attempt_at) if self.last_attempt_at else None,
            "last_known_reset_at": format_ts(self.last_known_reset_at) if self.last_known_reset_at else None,
            "last_exit_code": self.last_exit_code,
            "last_stdout": self.last_stdout,
            "last_stderr": self.last_stderr,
        }
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


class WebSocketClient:
    def __init__(self, host: str, port: int, path: str = "/") -> None:
        self.host = host
        self.port = port
        self.path = path
        self.sock: socket.socket | None = None

    def __enter__(self) -> "WebSocketClient":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def connect(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")

        sock = socket.create_connection((self.host, self.port), timeout=10)
        sock.sendall(request)
        response = self._read_http_response(sock)

        accept_expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if "101" not in response.splitlines()[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response.splitlines()[0]}")
        if f"Sec-WebSocket-Accept: {accept_expected}".lower() not in response.lower():
            raise RuntimeError("WebSocket handshake missing expected Sec-WebSocket-Accept")

        self.sock = sock

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self.send_text("", opcode=0x8)
        except OSError:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    def send_json(self, payload: dict[str, Any]) -> None:
        self.send_text(json.dumps(payload, separators=(",", ":")))

    def send_text(self, text: str, opcode: int = 0x1) -> None:
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")

        data = text.encode("utf-8")
        first_byte = 0x80 | opcode
        mask_key = secrets.token_bytes(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))

        header = bytearray([first_byte])
        length = len(masked)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        self.sock.sendall(bytes(header) + masked)

    def recv_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self.recv_frame()
            if opcode == 0x1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 0x8:
                raise RuntimeError("WebSocket server closed the connection")
            if opcode == 0x9:
                self._send_pong(payload)

    def recv_frame(self) -> tuple[int, bytes]:
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")

        first_two = self._recv_exact(2)
        first_byte, second_byte = first_two[0], first_two[1]
        opcode = first_byte & 0x0F
        masked = bool(second_byte & 0x80)
        length = second_byte & 0x7F

        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]

        mask_key = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _send_pong(self, payload: bytes) -> None:
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")

        first_byte = 0x80 | 0xA
        mask_key = secrets.token_bytes(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        header = bytearray([first_byte])
        length = len(masked)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise RuntimeError("WebSocket is not connected")

        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("Socket closed while reading WebSocket frame")
            chunks.extend(chunk)
        return bytes(chunks)

    @staticmethod
    def _read_http_response(sock: socket.socket) -> str:
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
        return response.decode("utf-8", errors="replace")


def start_app_server(codex_bin: str, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [codex_bin, "app-server", "--listen", f"ws://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def choose_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def query_reset_at(args: argparse.Namespace) -> datetime:
    codex_bin = resolve_codex_bin(args.codex_bin)
    port = choose_free_port()
    server = start_app_server(codex_bin, port)

    try:
        deadline = time.time() + args.app_server_start_timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            if server.poll() is not None:
                stderr = (server.stderr.read() or "").strip()
                raise RuntimeError(f"codex app-server exited early: {stderr or 'no stderr'}")
            try:
                with WebSocketClient("127.0.0.1", port) as ws:
                    ws.send_json(
                        {
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "clientInfo": {
                                    "name": "codex-auto-ping",
                                    "title": "codex-auto-ping",
                                    "version": "0.1",
                                },
                                "capabilities": {
                                    "experimentalApi": True,
                                    "optOutNotificationMethods": [],
                                },
                            },
                        }
                    )
                    wait_for_response(ws, 1)

                    ws.send_json({"id": 2, "method": "account/rateLimits/read", "params": None})
                    response = wait_for_response(ws, 2)
                    rate_limits = response["result"]["rateLimitsByLimitId"][args.limit_id]
                    resets_at = rate_limits["primary"]["resetsAt"]
                    if resets_at is None:
                        raise RuntimeError("Primary rate limit window does not have resetsAt")
                    return epoch_to_local(int(resets_at))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.25)

        raise RuntimeError(f"Could not query rate limits from Codex: {last_error}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def wait_for_response(ws: WebSocketClient, request_id: int) -> dict[str, Any]:
    while True:
        message = ws.recv_json()
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(f"app-server request failed: {message['error']}")
            return message


def inferred_next_due(anchor: datetime, offset_minutes: int) -> datetime:
    return anchor + timedelta(hours=WINDOW_HOURS, minutes=offset_minutes)


def live_next_due(args: argparse.Namespace, state: State) -> datetime:
    try:
        print(f"[{format_ts(now_local())}] querying live reset time from Codex", flush=True)
        reset_at = query_reset_at(args)
        state.last_known_reset_at = reset_at
        print(f"last reset at {format_ts(reset_at)}", flush=True)
        return reset_at + timedelta(minutes=args.offset_minutes)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: failed to read live reset time: {exc}", flush=True)
        if state.last_known_reset_at is not None:
            print(f"falling back to last known reset at {format_ts(state.last_known_reset_at)}", flush=True)
            return state.last_known_reset_at + timedelta(minutes=args.offset_minutes)
        if state.last_success_at is not None:
            print(f"falling back to inferred schedule from last success at {format_ts(state.last_success_at)}", flush=True)
            return inferred_next_due(state.last_success_at, args.offset_minutes)
        raise


def choose_next_due(args: argparse.Namespace, state: State, manual_pending: bool) -> tuple[datetime, str]:
    now = now_local()
    if manual_pending:
        assert args.manual_at is not None
        return args.manual_at, "manual"
    if args.daily_start is not None:
        if in_daily_quiet_hours(now, args.daily_start):
            return next_daily_start(now, args.daily_start), "daily-start"

        try:
            periodic_due = live_next_due(args, state)
        except Exception:
            print("no active reset time available after daily start; attempting activation now", flush=True)
            return now, "daily-start"

        if periodic_due.date() != now.date():
            return next_daily_start(now, args.daily_start), "daily-start"
        tomorrow_start = combine_local(now.date() + timedelta(days=1), args.daily_start)
        if periodic_due >= tomorrow_start:
            return tomorrow_start, "daily-start"
        return periodic_due, "periodic"

    return live_next_due(args, state), "periodic"


def describe_run_mode(args: argparse.Namespace) -> str:
    if args.daily_start is not None:
        return (
            "mode: daily-start "
            f"({args.daily_start.strftime(MANUAL_TIME_SHORT_FORMAT)} local start, "
            "back-to-back during the day, paused between 00:00 and daily start)"
        )
    if args.manual_at is not None:
        return f"mode: periodic with one manual trigger at {format_ts(args.manual_at)}"
    return "mode: periodic back-to-back"


def run_ping(args: argparse.Namespace, state: State) -> bool:
    started_at = now_local()
    state.last_attempt_at = started_at

    command = [
        resolve_codex_bin(args.codex_bin),
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--cd",
        str(args.workspace),
        args.prompt,
    ]

    print(f"[{format_ts(started_at)}] running: {' '.join(command[:-1])} <prompt>", flush=True)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    state.last_exit_code = result.returncode
    state.last_stdout = result.stdout.strip()[-1000:] or None
    state.last_stderr = result.stderr.strip()[-1000:] or None

    if result.returncode == 0:
        state.last_success_at = started_at
        print(f"[{format_ts(now_local())}] ping succeeded", flush=True)
        if state.last_stdout:
            print(f"stdout: {state.last_stdout}", flush=True)
        return True

    print(f"[{format_ts(now_local())}] ping failed with exit code {result.returncode}", flush=True)
    if state.last_stderr:
        print(f"stderr: {state.last_stderr}", flush=True)
    if state.last_stdout:
        print(f"stdout: {state.last_stdout}", flush=True)
    return False


def sleep_until(target: datetime, poll_seconds: int) -> None:
    while True:
        remaining = (target - now_local()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, poll_seconds))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read Codex's real 5h reset time from the local app-server protocol and send a low-cost "
            "request 1 minute after reset so the next window starts immediately."
        )
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Directory passed to `codex exec --cd`. Default: current directory.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(DEFAULT_STATE_FILE),
        help=f"Path to the local state file. Default: .\\{DEFAULT_STATE_FILE}",
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex CLI executable name or full path. Default: codex",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help=f"Prompt sent to `codex exec`. Default: {DEFAULT_PROMPT!r}",
    )
    parser.add_argument(
        "--limit-id",
        default=DEFAULT_LIMIT_ID,
        help=f"Rate limit bucket to read from app-server. Default: {DEFAULT_LIMIT_ID}",
    )
    parser.add_argument(
        "--offset-minutes",
        type=int,
        default=1,
        help="How long after the reset time to send the ping. Default: 1",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=20,
        help="Sleep granularity while waiting for the next due time. Default: 20",
    )
    parser.add_argument(
        "--retry-minutes",
        type=int,
        default=5,
        help="Retry delay after a failed due ping. Default: 5",
    )
    parser.add_argument(
        "--app-server-start-timeout",
        type=int,
        default=10,
        help="Seconds to wait for `codex app-server` to come up. Default: 10",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run at most one due ping and exit.",
    )
    parser.add_argument(
        "--print-next",
        action="store_true",
        help="Print the next due time and exit without sending a request.",
    )
    parser.add_argument(
        "--manual-at",
        type=parse_manual_local_ts,
        help=(
            "Schedule one manual ping at local time YYYY-MM-DD-HH-MM or HH:MM, then resume normal "
            "periodic pinging afterward. Examples: 2026-05-09-15-09 or 15:09"
        ),
    )
    parser.add_argument(
        "--daily-start",
        type=parse_time_of_day,
        help=(
            "Activate one workday cycle at local time HH:MM, then keep back-to-back pinging for the rest "
            "of the day. Between 00:00 and the next daily start, periodic pinging is paused."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.workspace = args.workspace.resolve()
    args.state_file = args.state_file.resolve()
    args.state_file.parent.mkdir(parents=True, exist_ok=True)

    state = State.load(args.state_file)
    print("codex_auto_ping.py started", flush=True)
    print(f"now: {format_ts(now_local())}", flush=True)
    print(f"workspace: {args.workspace}", flush=True)
    print(f"state file: {args.state_file}", flush=True)
    print(describe_run_mode(args), flush=True)
    print(f"last success at {describe_ts(state.last_success_at)}", flush=True)
    print(f"last known reset at {describe_ts(state.last_known_reset_at)}", flush=True)
    print(f"last attempt at {describe_ts(state.last_attempt_at)}", flush=True)
    if state.last_exit_code is not None:
        print(f"last exit code: {state.last_exit_code}", flush=True)
    if args.manual_at is not None:
        print(f"manual one-shot due at {format_ts(args.manual_at)}", flush=True)
    if args.daily_start is not None:
        print(f"daily start at {args.daily_start.strftime(MANUAL_TIME_SHORT_FORMAT)}", flush=True)

    if args.print_next:
        manual_pending = args.manual_at is not None and now_local() < args.manual_at
        due, mode = choose_next_due(args, state, manual_pending)
        if mode == "periodic":
            state.save(args.state_file)
        print(format_ts(due))
        return 0

    manual_pending = args.manual_at is not None and now_local() < args.manual_at
    while True:
        due, mode = choose_next_due(args, state, manual_pending)
        state.save(args.state_file)
        print(f"next {mode} due at {format_ts(due)}", flush=True)

        if args.once and now_local() < due:
            return 0

        sleep_until(due, max(args.poll_seconds, 1))
        success = run_ping(args, state)
        state.save(args.state_file)
        if mode == "manual":
            manual_pending = False

        if args.once:
            return 0 if success else 1

        if not success:
            retry_at = now_local() + timedelta(minutes=args.retry_minutes)
            print(f"retry due at {format_ts(retry_at)}", flush=True)
            sleep_until(retry_at, max(args.poll_seconds, 1))


if __name__ == "__main__":
    sys.exit(main())
