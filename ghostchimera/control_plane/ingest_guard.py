"""Path confinement for console file-ingest routes (redteam P0-2).

``/api/console/memory/ingest-file`` and ``ingest-email`` accept a host path.
Without a jail the console token alone could ingest ``console_secrets.json``
(token + host-execution arming phrase), ``~/.ssh/config`` or any ``.env``-like
JSON into memory, where search hands it back. Every path is therefore:

- resolved (symlinks followed) and required to sit under an allowed root:
  the directory the console was started in, plus any directories listed in
  ``GHOSTCHIMERA_INGEST_ROOTS`` (``os.pathsep``-separated);
- refused when it is inside the Ghost state directory;
- refused when any component below the root is a dotfile/dot-directory
  (``.ssh``, ``.env``, ``.git``, ``.aws`` ...) or the name looks like a secret
  store (``console_secrets.json``, ``*.pem``, ``id_rsa``, ``credentials`` ...).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

INGEST_ROOTS_ENV = "GHOSTCHIMERA_INGEST_ROOTS"

_SECRET_NAME_RE = re.compile(
    r"(?i)(?:secret|credential|passw|(?:^|[_.-])tokens?(?:[_.-]|$)|private[_-]?key|api[_-]?key|\.pem$|\.key$|\.p12$|\.pfx$|\.kdbx$|"
    r"^id_(?:rsa|dsa|ecdsa|ed25519)|^authorized_keys$|^known_hosts$|^\.?netrc$|^\.?pgpass$|^\.env)"
)


_ARMING_PHRASE_RE = re.compile(
    r"I\s+ACCEPT\s+HOST\s+EXECUTION\s+RISK(?:\s+[A-Za-z0-9]{2,}(?:-[A-Za-z0-9]{2,})*)?", re.I
)


def redact_for_storage(text: str) -> str:
    """Scrub credentials (and any host-execution arming phrase) before a chunk is stored."""
    from ..redaction import redact_secrets_text

    return _ARMING_PHRASE_RE.sub("[redacted:arming-phrase]", redact_secrets_text(str(text)))


class RedactingMemoryStore:
    """Proxy over a MemoryStore that redacts document content on the way in."""

    def __init__(self, store: object) -> None:
        self._store = store

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def _clean_meta(self, metadata: object) -> object:
        if isinstance(metadata, dict):
            return {k: redact_for_storage(v) if isinstance(v, str) else v for k, v in metadata.items()}
        return metadata

    def add_document_once(self, source: str, content: str, *args: object, **kwargs: object) -> object:
        if "metadata" in kwargs:
            kwargs["metadata"] = self._clean_meta(kwargs["metadata"])
        return self._store.add_document_once(source, redact_for_storage(content), *args, **kwargs)  # type: ignore[attr-defined]

    def add_document(self, source: str, content: str, *args: object, **kwargs: object) -> object:
        if "metadata" in kwargs:
            kwargs["metadata"] = self._clean_meta(kwargs["metadata"])
        return self._store.add_document(source, redact_for_storage(content), *args, **kwargs)  # type: ignore[attr-defined]


class IngestPathError(PermissionError):
    """A requested ingest path is outside the allowed roots or sensitive."""


def allowed_roots(extra: Iterable[str | Path] = ()) -> list[Path]:
    roots: list[Path] = [Path.cwd().resolve()]
    for raw in os.environ.get(INGEST_ROOTS_ENV, "").split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw.strip()).expanduser().resolve())
    roots.extend(Path(item).expanduser().resolve() for item in extra)
    # "/" (or a drive root) as an ingest root would re-open the whole host.
    return [root for root in roots if root.parent != root]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_sensitive_name(name: str) -> bool:
    return name.startswith(".") or bool(_SECRET_NAME_RE.search(name))


def _denied_dirs(state_dir: str | Path | Iterable[str | Path]) -> list[Path]:
    items = [state_dir] if isinstance(state_dir, (str, Path)) else list(state_dir)
    items.append(Path.home() / ".ghostchimera")
    env_state = os.environ.get("GHOSTCHIMERA_STATE_DIR", "").strip()
    if env_state:
        items.append(env_state)
    return [Path(item).expanduser().resolve() for item in items]


def check_ingest_path(
    path: str | Path,
    *,
    state_dir: str | Path | Iterable[str | Path],
    roots: list[Path] | None = None,
) -> Path:
    """Return the resolved path, or raise :class:`IngestPathError`."""
    raw = Path(str(path)).expanduser()
    resolved = raw.resolve()
    for denied in _denied_dirs(state_dir):
        # A directory that merely *contains* the state dir is fine: each file
        # is re-checked by iter_allowed_files, so state files are skipped.
        if _is_under(resolved, denied):
            raise IngestPathError("ingest from the Ghost state directory is not allowed")
    candidates = roots if roots is not None else allowed_roots()
    root = next((r for r in candidates if _is_under(resolved, r)), None)
    if root is None:
        raise IngestPathError(
            f"path is outside the allowed ingest roots (the console's working directory or {INGEST_ROOTS_ENV})"
        )
    for part in resolved.relative_to(root).parts:
        if is_sensitive_name(part):
            raise IngestPathError(f"refusing to ingest a hidden or secret-looking path component: {part}")
    return resolved


def iter_allowed_files(
    directory: Path, *, state_dir: str | Path | Iterable[str | Path], roots: list[Path], limit: int
) -> list[Path]:
    """Files under *directory* that pass :func:`check_ingest_path` (symlinks re-checked)."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not is_sensitive_name(d))
        for name in sorted(filenames):
            if len(out) >= limit:
                return out
            try:
                out.append(check_ingest_path(Path(dirpath) / name, state_dir=state_dir, roots=roots))
            except IngestPathError:
                continue
    return out


__all__ = [
    "INGEST_ROOTS_ENV",
    "IngestPathError",
    "allowed_roots",
    "check_ingest_path",
    "RedactingMemoryStore",
    "is_sensitive_name",
    "redact_for_storage",
    "iter_allowed_files",
]
