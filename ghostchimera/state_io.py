"""Crash- and concurrency-safe primitives for Ghost Chimera's on-disk state.

Every JSON state file the package keeps (trust runtime, console chat
history, automations, standing orders, OAuth tokens, ...) goes through
the helpers here, so the guarantees are written once:

* **Atomic writes**: data goes to a *unique* temp file in the same
  directory, is flushed and fsynced, then ``os.replace``-d over the
  target. Readers never observe a half-written file and two writers never
  share a temp path.
* **Private by default, independent of umask**: files are created
  ``0o600`` from the first byte and their directory is ``0o700``
  (POSIX; Windows relies on the per-user profile ACLs).
* **Locked read-modify-write**: :func:`locked` combines a per-path,
  re-entrant in-process lock with an OS file lock on a ``<name>.lock``
  sidecar (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows), so
  threads *and* separate processes (CLI + daemon + console) serialise.
* **Never wipe on corruption**: :func:`read_json` moves an unparseable
  file aside to ``<name>.corrupt-<timestamp>-<rand>`` and returns the
  default, instead of letting the next save silently overwrite the user's
  data.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700

_MISSING = object()


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def _chmod(path: Path, mode: int) -> None:
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def ensure_private_dir(path: str | os.PathLike[str], *, mode: int = PRIVATE_DIR_MODE) -> Path:
    """Create *path* (and parents) and make the leaf directory owner-only.

    Only the leaf is chmod-ed: parents may be shared locations such as the
    user's home directory, which are not ours to tighten.
    """
    directory = Path(path).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    _chmod(directory, mode)
    return directory


def make_private(path: str | os.PathLike[str], *, mode: int = PRIVATE_FILE_MODE) -> None:
    """Best-effort chmod of an existing file to owner-only."""
    _chmod(Path(path), mode)


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def _fsync_dir(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(
    path: str | os.PathLike[str],
    data: bytes,
    *,
    mode: int = PRIVATE_FILE_MODE,
    dir_mode: int | None = PRIVATE_DIR_MODE,
) -> Path:
    """Atomically replace *path* with *data* via a unique, fsynced temp file."""
    target = Path(path).expanduser()
    if dir_mode is None:
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        ensure_private_dir(target.parent, mode=dir_mode)
    # mkstemp creates the file O_EXCL with mode 0o600 regardless of umask,
    # and the random suffix means concurrent writers never share a temp.
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        if os.name == "posix" and mode != PRIVATE_FILE_MODE:
            with contextlib.suppress(OSError):
                os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    _fsync_dir(target.parent)
    return target


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = PRIVATE_FILE_MODE,
    dir_mode: int | None = PRIVATE_DIR_MODE,
) -> Path:
    """Atomically replace *path* with *text* (owner-only by default)."""
    return atomic_write_bytes(path, text.encode(encoding), mode=mode, dir_mode=dir_mode)


def atomic_write_json(
    path: str | os.PathLike[str],
    data: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    default: Callable[[Any], Any] | None = None,
    ensure_ascii: bool = True,
    mode: int = PRIVATE_FILE_MODE,
    dir_mode: int | None = PRIVATE_DIR_MODE,
) -> Path:
    """Atomically write *data* as JSON (owner-only by default).

    Serialisation happens before the temp file is created, so an
    unserialisable payload never leaves debris or touches the target.
    """
    text = json.dumps(data, indent=indent, sort_keys=sort_keys, default=default, ensure_ascii=ensure_ascii)
    return atomic_write_text(path, text, mode=mode, dir_mode=dir_mode)


def write_private_json(path: str | os.PathLike[str], data: Any, **kwargs: Any) -> Path:
    """Write secrets/tokens: 0600 file inside a 0700 dir, atomically."""
    kwargs.setdefault("mode", PRIVATE_FILE_MODE)
    kwargs.setdefault("dir_mode", PRIVATE_DIR_MODE)
    return atomic_write_json(path, data, **kwargs)


def write_private_text(path: str | os.PathLike[str], text: str, **kwargs: Any) -> Path:
    """Write a secret text file: 0600 file inside a 0700 dir, atomically."""
    kwargs.setdefault("mode", PRIVATE_FILE_MODE)
    kwargs.setdefault("dir_mode", PRIVATE_DIR_MODE)
    return atomic_write_text(path, text, **kwargs)


def append_line(path: str | os.PathLike[str], line: str, *, encoding: str = "utf-8") -> None:
    """Append one line to *path*, creating it owner-only if missing.

    Callers that need ordering guarantees across writers (hash chains)
    must hold :func:`locked` around the read-then-append sequence.
    """
    target = Path(path).expanduser()
    ensure_private_dir(target.parent)
    if not line.endswith("\n"):
        line += "\n"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "ab") as handle:
        handle.write(line.encode(encoding))
        handle.flush()


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


class _PathLock:
    """Re-entrant thread lock + cross-process OS lock on a sidecar file."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._rlock = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    def acquire(self) -> None:
        self._rlock.acquire()
        try:
            if self._depth == 0:
                self._fd = _os_lock(self.lock_path)
            self._depth += 1
        except BaseException:
            self._rlock.release()
            raise

    def release(self) -> None:
        try:
            self._depth -= 1
            if self._depth == 0 and self._fd is not None:
                fd, self._fd = self._fd, None
                _os_unlock(fd)
        finally:
            self._rlock.release()


def _os_lock(lock_path: Path) -> int:
    ensure_private_dir(lock_path.parent)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, PRIVATE_FILE_MODE)
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI only
            import msvcrt

            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _os_unlock(fd: int) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI only
            import msvcrt

            with contextlib.suppress(OSError):
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


_LOCKS: dict[str, _PathLock] = {}
_LOCKS_GUARD = threading.Lock()


def _reset_locks_after_fork() -> None:
    # A forked child must not inherit locks held by threads that do not
    # exist in it; start with a clean registry.
    global _LOCKS_GUARD
    _LOCKS.clear()
    _LOCKS_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_locks_after_fork)


def lock_path_for(path: str | os.PathLike[str]) -> Path:
    target = Path(path).expanduser()
    return target.with_name(f"{target.name}.lock")


@contextlib.contextmanager
def locked(path: str | os.PathLike[str]) -> Iterator[None]:
    """Serialise read-modify-write of *path* across threads and processes.

    Re-entrant within a thread, so a locked method may call another locked
    method of the same store.
    """
    lock_file = lock_path_for(path)
    key = os.path.abspath(lock_file)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _PathLock(Path(key))
            _LOCKS[key] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def locked_method(path_attr: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a store method so it runs under :func:`locked` on ``self.<path_attr>``."""

    def decorator(method: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(method)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with locked(getattr(self, path_attr)):
                return method(self, *args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Reads that never wipe data
# ---------------------------------------------------------------------------


def quarantine_corrupt(path: str | os.PathLike[str]) -> Path | None:
    """Move an unreadable state file aside so it is never overwritten."""
    target = Path(path).expanduser()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    backup = target.with_name(f"{target.name}.corrupt-{stamp}-{secrets.token_hex(3)}")
    try:
        os.replace(target, backup)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("could not quarantine corrupt state file %s: %s", target, exc)
        return None
    make_private(backup)
    logger.warning("state file %s was unreadable; preserved as %s and starting fresh", target, backup)
    return backup


def read_json(
    path: str | os.PathLike[str],
    default: Any = None,
    *,
    expect: type | tuple[type, ...] | None = None,
    quarantine: bool = True,
) -> Any:
    """Load JSON from *path*, returning a fresh copy of *default* if absent.

    If the file exists but cannot be decoded (or is not of type *expect*),
    it is moved aside with :func:`quarantine_corrupt` and *default* is
    returned, so a later save cannot destroy the only copy of the data.
    I/O errors (e.g. permissions) return *default* without moving anything.
    """
    target = Path(path).expanduser()
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return copy.deepcopy(default)
    except OSError as exc:
        logger.warning("could not read state file %s: %s", target, exc)
        return copy.deepcopy(default)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if quarantine:
            quarantine_corrupt(target)
        return copy.deepcopy(default)
    if expect is not None and not isinstance(data, expect):
        if quarantine:
            quarantine_corrupt(target)
        return copy.deepcopy(default)
    return data


class AtomicJsonStore:
    """A single JSON document on disk with locked, atomic updates.

    ``load()`` never raises on a corrupt file (it is quarantined), ``save()``
    is atomic and owner-only, and ``update()`` holds the cross-process lock
    around the whole read-modify-write::

        store = AtomicJsonStore(path, default=dict)
        with store.update() as data:
            data["k"] = "v"
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        default: Callable[[], Any] = dict,
        indent: int | None = 2,
        sort_keys: bool = True,
        mode: int = PRIVATE_FILE_MODE,
    ) -> None:
        self.path = Path(path).expanduser()
        self._default = default
        self._indent = indent
        self._sort_keys = sort_keys
        self._mode = mode

    def _expect(self) -> type:
        return type(self._default())

    def load(self) -> Any:
        return read_json(self.path, self._default(), expect=self._expect())

    def save(self, data: Any) -> None:
        with locked(self.path):
            atomic_write_json(self.path, data, indent=self._indent, sort_keys=self._sort_keys, mode=self._mode)

    def lock(self) -> contextlib.AbstractContextManager[None]:
        return locked(self.path)

    @contextlib.contextmanager
    def update(self) -> Iterator[Any]:
        with locked(self.path):
            data = self.load()
            yield data
            atomic_write_json(self.path, data, indent=self._indent, sort_keys=self._sort_keys, mode=self._mode)


__all__ = [
    "PRIVATE_DIR_MODE",
    "PRIVATE_FILE_MODE",
    "AtomicJsonStore",
    "append_line",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "ensure_private_dir",
    "lock_path_for",
    "locked",
    "locked_method",
    "make_private",
    "quarantine_corrupt",
    "read_json",
    "write_private_json",
    "write_private_text",
]
