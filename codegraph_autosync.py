#!/usr/bin/env python3
"""Keep a CodeGraph index fresh with native Windows notifications.

On Windows the watcher uses ``ReadDirectoryChangesW`` with subtree monitoring, so
normal changes are delivered by the operating system rather than found by a full
recursive scan. A short debounce window collapses editor save bursts into one
``codegraph sync`` invocation. If native notifications are unavailable, the
watcher falls back to polling snapshots. A missing ``.codegraph`` directory is
initialized automatically before watching begins.

Examples:
    cd D:\\work\\my-repo
    python D:\\jutils\\codegraph_autosync.py
    python D:\\jutils\\codegraph_autosync.py --poll-interval 2 --debounce 2
    python D:\\jutils\\codegraph_autosync.py --sync-on-start
"""

from __future__ import annotations

import argparse
import ctypes
import fnmatch
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


LOGGER = logging.getLogger("codegraph-autosync")
DEFAULT_IGNORE_DIRS = frozenset(
    {
        ".codegraph",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
    }
)
DEFAULT_IGNORE_PATTERNS = ("*.pyc", "*.pyo", "*.swp", "*.swo", "~$*")
FileSignature = tuple[int, int, int]
Snapshot = dict[str, FileSignature]


def _kernel32():
    """Return a typed Kernel32 wrapper with reliable last-error handling."""

    if os.name != "nt":
        raise OSError("Kernel32 is only available on Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.ReadDirectoryChangesW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.ReadDirectoryChangesW.restype = ctypes.c_int
    kernel32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.CancelIoEx.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


class WindowsChangeSource:
    """ReadDirectoryChangesW source; no directory scan is performed per event."""

    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_NOTIFY_CHANGE = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 | 0x00000010 | 0x00000040
    _ERROR_NOTIFY_ENUM_DIR = 1022
    _ERROR_INVALID_PARAMETER = 87

    def __init__(self, root: Path, ignore_dirs: Iterable[str], ignore_patterns: Iterable[str]) -> None:
        if os.name != "nt":
            raise OSError("ReadDirectoryChangesW is only available on Windows")
        self.root = root.resolve()
        self.ignore_dirs = set(ignore_dirs)
        self.ignore_patterns = tuple(ignore_patterns)
        self._events: queue.Queue[tuple[str, set[str]]] = queue.Queue()
        self._stop = threading.Event()
        self._handle: int | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        kernel32 = _kernel32()
        handle = kernel32.CreateFileW(
            str(self.root),
            self._FILE_LIST_DIRECTORY,
            self._FILE_SHARE_READ | self._FILE_SHARE_WRITE | self._FILE_SHARE_DELETE,
            None,
            self._OPEN_EXISTING,
            self._FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_last_error(), f"Cannot open directory watch handle: {self.root}")
        self._handle = int(handle)
        self._thread = threading.Thread(target=self._read_loop, name="codegraph-read-directory", daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        kernel32 = _kernel32()
        buffer = ctypes.create_string_buffer(64 * 1024)
        bytes_returned = ctypes.c_uint32()
        while not self._stop.is_set() and self._handle is not None:
            ok = kernel32.ReadDirectoryChangesW(
                ctypes.c_void_p(self._handle),
                ctypes.byref(buffer),
                ctypes.sizeof(buffer),
                True,
                self._FILE_NOTIFY_CHANGE,
                ctypes.byref(bytes_returned),
                None,
                None,
            )
            if not ok:
                error = ctypes.get_last_error()
                if self._stop.is_set():
                    return
                if error in (self._ERROR_NOTIFY_ENUM_DIR, self._ERROR_INVALID_PARAMETER):
                    self._events.put(("overflow", set()))
                    continue
                self._events.put(("error", {str(error)}))
                return
            if bytes_returned.value == 0:
                continue
            try:
                changes = self._parse_buffer(buffer, bytes_returned.value)
            except (IndexError, ValueError) as exc:
                self._events.put(("error", {f"invalid notification buffer: {exc}"}))
                return
            self._events.put(("changes", changes))

    def _parse_buffer(self, buffer: ctypes.Array[ctypes.c_char], size: int) -> set[str]:
        changes: set[str] = set()
        offset = 0
        base = ctypes.addressof(buffer)
        while offset < size:
            remaining = size - offset
            if remaining < 12:
                raise ValueError("truncated notification header")
            next_offset = int.from_bytes(ctypes.string_at(base + offset, 4), "little")
            name_length = int.from_bytes(ctypes.string_at(base + offset + 8, 4), "little")
            if name_length % 2 or 12 + name_length > remaining:
                raise ValueError("invalid file name length")
            name = ctypes.wstring_at(base + offset + 12, name_length // 2)
            relative = Path(name)
            if not _matches_ignore(relative, self.ignore_dirs, self.ignore_patterns):
                changes.add(relative.as_posix())
            if next_offset == 0:
                break
            if next_offset < 12 or next_offset > remaining:
                raise ValueError("invalid next entry offset")
            offset += next_offset
        return changes

    def get(self, timeout: float) -> tuple[str, set[str]] | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        if self._handle is not None:
            kernel32 = _kernel32()
            # Closing a handle from another thread does not reliably interrupt a
            # synchronous ReadDirectoryChangesW call. CancelIoEx does.
            kernel32.CancelIoEx(ctypes.c_void_p(self._handle), None)
            kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)


@dataclass(frozen=True)
class WatchConfig:
    root: Path
    poll_interval: float = 1.0
    debounce: float = 1.5
    retry_delay: float = 10.0
    sync_timeout: float = 120.0
    codegraph_bin: str = "codegraph"
    sync_args: tuple[str, ...] = ()
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS
    ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
    sync_on_start: bool = False
    once: bool = False


def _matches_ignore(relative_path: Path, ignore_dirs: Iterable[str], ignore_patterns: Iterable[str]) -> bool:
    """Return whether a path should be excluded from the watched snapshot."""

    parts = relative_path.parts
    ignored_dirs = {directory.casefold() for directory in ignore_dirs}
    # Windows can report the ignored directory itself, not only files below it.
    if any(part.casefold() in ignored_dirs for part in parts):
        return True

    relative_posix = relative_path.as_posix().casefold()
    name = relative_path.name.casefold()
    return any(
        fnmatch.fnmatch(name, pattern.casefold()) or fnmatch.fnmatch(relative_posix, pattern.casefold())
        for pattern in ignore_patterns
    )


def build_snapshot(
    root: Path,
    *,
    ignore_dirs: Iterable[str] = DEFAULT_IGNORE_DIRS,
    ignore_patterns: Iterable[str] = DEFAULT_IGNORE_PATTERNS,
) -> Snapshot:
    """Build a deterministic file snapshot below *root*.

    Only regular files are included. The signature uses nanosecond timestamps and
    size, which catches normal edits and atomic replacement saves without reading
    file contents. Native Windows events remain the primary path.
    """

    root = root.resolve()
    ignored_dirs = {directory.casefold() for directory in ignore_dirs}
    ignored_patterns = tuple(ignore_patterns)
    snapshot: Snapshot = {}

    for current_root, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current_root)
        relative_root = current_path.relative_to(root)
        dir_names[:] = [
            directory
            for directory in dir_names
            if directory.casefold() not in ignored_dirs
            and not _matches_ignore(relative_root / directory, ignored_dirs, ignored_patterns)
        ]

        for file_name in file_names:
            path = current_path / file_name
            relative_path = path.relative_to(root)
            if _matches_ignore(relative_path, ignored_dirs, ignored_patterns):
                continue
            try:
                stat = path.stat()
            except (FileNotFoundError, PermissionError, OSError):
                # A file can disappear between os.walk and stat during a save.
                continue
            if not path.is_file():
                continue
            snapshot[relative_path.as_posix()] = (
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_size,
            )

    return snapshot


def changed_paths(previous: Mapping[str, FileSignature], current: Mapping[str, FileSignature]) -> set[str]:
    """Return added, removed, or modified relative paths."""

    all_paths = set(previous) | set(current)
    return {path for path in all_paths if previous.get(path) != current.get(path)}


def resolve_codegraph_bin(value: str) -> str:
    """Resolve a command or explicit executable path for subprocess execution."""

    explicit = Path(value).expanduser()
    if explicit.is_file():
        return str(explicit.resolve())

    candidates = (value, f"{value}.cmd", f"{value}.exe")
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError(f"Cannot find CodeGraph command `{value}`. Install CodeGraph or use --codegraph-bin.")


def _run_codegraph(
    root: Path,
    codegraph_bin: str,
    arguments: Sequence[str],
    *,
    timeout: float,
    action: str,
) -> bool:
    command = [codegraph_bin, *arguments]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            check=False,
            creationflags=creationflags,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        LOGGER.error("CodeGraph %s timed out after %.1f seconds.", action, timeout)
        return False
    except OSError as exc:
        LOGGER.error("Failed to start CodeGraph %s: %s", action, exc)
        return False
    if completed.returncode != 0:
        LOGGER.error("CodeGraph %s failed (exit code %s).", action, completed.returncode)
        return False
    return True


def run_init(root: Path, codegraph_bin: str, *, timeout: float = 120.0) -> bool:
    """Initialize a missing CodeGraph index in *root*."""

    LOGGER.info("CodeGraph index not found; initializing.")
    return _run_codegraph(root, codegraph_bin, ("init", "."), timeout=timeout, action="init")


def run_sync(root: Path, codegraph_bin: str, sync_args: Sequence[str] = (), *, timeout: float = 120.0) -> bool:
    """Run ``codegraph sync`` in the repository root and return success."""

    return _run_codegraph(root, codegraph_bin, ("sync", *sync_args), timeout=timeout, action="sync")


class AutoSyncWatcher:
    """Debounced watcher that prefers native Windows events and has a polling fallback."""

    def __init__(
        self,
        config: WatchConfig,
        *,
        snapshot_fn: Callable[..., Snapshot] = build_snapshot,
        sync_fn: Callable[[Path, str, Sequence[str]], bool] = run_sync,
    ) -> None:
        self.config = config
        self.snapshot_fn = snapshot_fn
        self.sync_fn = sync_fn
        self._stop = False

    def stop(self, *_: object) -> None:
        self._stop = True

    def _snapshot(self) -> Snapshot:
        return self.snapshot_fn(
            self.config.root,
            ignore_dirs=self.config.ignore_dirs,
            ignore_patterns=self.config.ignore_patterns,
        )

    def watch(self) -> int:
        if os.name == "nt":
            try:
                return self._watch_windows()
            except OSError as exc:
                LOGGER.warning("Native Windows file notifications unavailable; falling back to polling: %s", exc)
        return self._watch_polling()

    def _watch_windows(self) -> int:
        # One baseline is only needed to recover from the rare Windows notification
        # buffer overflow. Normal changes arrive as paths from the OS and do not scan.
        self._last_snapshot = self._snapshot()
        source = WindowsChangeSource(
            self.config.root,
            self.config.ignore_dirs,
            self.config.ignore_patterns,
        )
        source.start()
        pending_since: float | None = time.monotonic() if self.config.sync_on_start else None
        retry_at = 0.0
        pending_paths: set[str] = {"<startup>"} if self.config.sync_on_start else set()

        LOGGER.info("Watching directory: %s", self.config.root)
        LOGGER.info("Using Windows ReadDirectoryChangesW (event-driven); debounce %.1fs; press Ctrl+C to stop.", self.config.debounce)
        try:
            while not self._stop:
                event = source.get(timeout=min(0.5, max(self.config.poll_interval, 0.05)))
                if event is not None:
                    kind, paths = event
                    if kind == "error":
                        raise OSError(f"ReadDirectoryChangesW failed, error code: {', '.join(sorted(paths))}")
                    if kind == "overflow":
                        LOGGER.warning("Windows notification buffer overflow; running one snapshot reconciliation.")
                        current = self._snapshot()
                        paths = changed_paths(self._last_snapshot, current) if hasattr(self, "_last_snapshot") else set()
                        self._last_snapshot = current
                    if paths:
                        was_pending = pending_since is not None
                        pending_paths.update(paths)
                        pending_since = pending_since or time.monotonic()
                        retry_at = 0.0
                        if not was_pending:
                            LOGGER.info("Changes detected; CodeGraph index update scheduled.")

                if pending_since is None:
                    continue
                now = time.monotonic()
                if now - pending_since < self.config.debounce or now < retry_at:
                    continue
                LOGGER.info("Updating CodeGraph index.")
                if self.sync_fn(self.config.root, self.config.codegraph_bin, self.config.sync_args):
                    LOGGER.info("CodeGraph index updated.")
                    pending_since = None
                    pending_paths.clear()
                    retry_at = 0.0
                    if self.config.once:
                        return 0
                else:
                    retry_at = time.monotonic() + self.config.retry_delay
        finally:
            source.stop()
        LOGGER.info("Stopped watching.")
        return 0

    def _watch_polling(self) -> int:
        previous = self._snapshot()
        pending_since: float | None = time.monotonic() if self.config.sync_on_start else None
        retry_at = 0.0
        pending_paths: set[str] = {"<startup>"} if self.config.sync_on_start else set()

        LOGGER.info("Watching directory: %s", self.config.root)
        LOGGER.info("Using polling fallback (every %.1fs); debounce %.1fs; press Ctrl+C to stop.", self.config.poll_interval, self.config.debounce)
        if self.config.sync_on_start:
            LOGGER.info("Initial sync enabled.")

        while not self._stop:
            time.sleep(self.config.poll_interval)
            current = self._snapshot()
            changes = changed_paths(previous, current)
            previous = current
            if changes:
                was_pending = pending_since is not None
                pending_paths.update(changes)
                pending_since = pending_since or time.monotonic()
                retry_at = 0.0
                if not was_pending:
                    LOGGER.info("Changes detected; CodeGraph index update scheduled.")

            if pending_since is None:
                continue
            now = time.monotonic()
            if now - pending_since < self.config.debounce or now < retry_at:
                continue

            LOGGER.info("Updating CodeGraph index.")
            if self.sync_fn(self.config.root, self.config.codegraph_bin, self.config.sync_args):
                LOGGER.info("CodeGraph index updated.")
                previous = self._snapshot()
                pending_since = None
                pending_paths.clear()
                retry_at = 0.0
                if self.config.once:
                    return 0
            else:
                retry_at = time.monotonic() + self.config.retry_delay

        LOGGER.info("Stopped watching.")
        return 0


def _parse_args(argv: Sequence[str] | None = None) -> WatchConfig:
    parser = argparse.ArgumentParser(description="Watch a directory and automatically run codegraph sync")
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Repository root to watch (defaults to the current directory)",
    )
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval for fallback mode in seconds (default: 1)")
    parser.add_argument("--debounce", type=float, default=1.5, help="Seconds to wait for changes to settle (default: 1.5)")
    parser.add_argument("--retry-delay", type=float, default=10.0, help="Retry delay after a failed sync (default: 10)")
    parser.add_argument("--sync-timeout", type=float, default=120.0, help="Timeout for init/sync commands in seconds (default: 120)")
    parser.add_argument("--codegraph-bin", default="codegraph", help="CodeGraph executable or command name")
    parser.add_argument("--ignore-dir", action="append", default=[], help="Additional directory name to ignore (repeatable)")
    parser.add_argument("--ignore", dest="ignore_patterns", action="append", default=[], help="Additional file glob to ignore (repeatable)")
    parser.add_argument("--sync-on-start", action="store_true", help="Run one sync when the watcher starts")
    parser.add_argument("--once", action="store_true", help="Exit after one successful sync")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        parser.error(f"Watch directory does not exist or is not a directory: {args.root}")
    if args.poll_interval <= 0 or args.debounce < 0 or args.retry_delay < 0 or args.sync_timeout <= 0:
        parser.error("--poll-interval must be positive; --debounce/--retry-delay cannot be negative; --sync-timeout must be positive")

    ignore_dirs = frozenset(DEFAULT_IGNORE_DIRS | set(args.ignore_dir))
    ignore_patterns = (*DEFAULT_IGNORE_PATTERNS, *args.ignore_patterns)
    return WatchConfig(
        root=args.root.resolve(),
        poll_interval=args.poll_interval,
        debounce=args.debounce,
        retry_delay=args.retry_delay,
        sync_timeout=args.sync_timeout,
        codegraph_bin=args.codegraph_bin,
        ignore_dirs=ignore_dirs,
        ignore_patterns=ignore_patterns,
        sync_on_start=args.sync_on_start,
        once=args.once,
    )


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass
    config = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if "--verbose" in (argv or sys.argv[1:]) else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        config = WatchConfig(**{**config.__dict__, "codegraph_bin": resolve_codegraph_bin(config.codegraph_bin)})
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2
    if not (config.root / ".codegraph").is_dir() and not run_init(
        config.root,
        config.codegraph_bin,
        timeout=config.sync_timeout,
    ):
        return 1

    sync_runner = lambda root, codegraph_bin, sync_args: run_sync(
        root,
        codegraph_bin,
        sync_args,
        timeout=config.sync_timeout,
    )
    watcher = AutoSyncWatcher(config, sync_fn=sync_runner)
    signal.signal(signal.SIGINT, watcher.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, watcher.stop)
    try:
        return watcher.watch()
    except KeyboardInterrupt:
        watcher.stop()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
