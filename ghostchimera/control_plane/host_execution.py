"""Explicit host execution and self-edit runtime for Ghost Console.

This module is intentionally separate from the normal sandboxed runtime.  It is
off by default, requires an exact confirmation phrase, and writes local audit
artifacts for every command or source mutation.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIRMATION_PHRASE = "I ACCEPT HOST EXECUTION RISK"
SECRET_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization", "confirmation")


@dataclass
class HostExecutionSettings:
    unrestricted_host_mode: bool = False
    allowed_root: str = ""
    audit_dir: str = ""
    max_command_seconds: int = 120
    allow_network_commands: bool = True
    allow_source_mutation: bool = True
    disclaimer_acknowledged: bool = False
    armed_at: float = 0.0
    secret_fields_configured: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


def _now() -> float:
    return time.time()


def _stable_id(*parts: object, length: int = 16) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_MARKERS):
                redacted[str(key)] = "[redacted]" if item else ""
            else:
                redacted[str(key)] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _settings_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "host_execution_settings.json"


def _events_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "host_execution_events.jsonl"


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class HostExecutionStore:
    """Local JSON-backed host execution store."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()

    def _default_settings(self) -> HostExecutionSettings:
        root = Path.cwd().resolve()
        return HostExecutionSettings(
            allowed_root=str(root),
            audit_dir=str(self.state_dir / "host_execution_audit"),
            max_command_seconds=120,
        )

    def settings(self) -> dict[str, Any]:
        path = _settings_path(self.state_dir)
        if not path.exists():
            return self._default_settings().to_dict()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_settings().to_dict()
        if not isinstance(data, dict):
            return self._default_settings().to_dict()
        merged = {**asdict(self._default_settings()), **data}
        return _redact_value(merged)

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = {**asdict(self._default_settings()), **self._raw_settings()}
        confirmation = str(payload.get("confirmation_phrase") or "").strip()
        wants_unrestricted = bool(payload.get("unrestricted_host_mode", current.get("unrestricted_host_mode", False)))
        if wants_unrestricted and confirmation != CONFIRMATION_PHRASE:
            return {
                "ok": False,
                "error": f"Type the exact confirmation phrase to arm host execution: {CONFIRMATION_PHRASE}",
            }
        for key in ("unrestricted_host_mode", "allow_network_commands", "allow_source_mutation", "disclaimer_acknowledged"):
            if key in payload:
                current[key] = bool(payload[key])
        if payload.get("allowed_root"):
            current["allowed_root"] = str(Path(str(payload["allowed_root"])).expanduser().resolve())
        if payload.get("audit_dir"):
            current["audit_dir"] = str(Path(str(payload["audit_dir"])).expanduser().resolve())
        if "max_command_seconds" in payload:
            try:
                current["max_command_seconds"] = max(1, min(int(payload["max_command_seconds"]), 1800))
            except (TypeError, ValueError):
                current["max_command_seconds"] = 120
        if current.get("unrestricted_host_mode"):
            current["armed_at"] = current.get("armed_at") or _now()
            current["disclaimer_acknowledged"] = True
            current["secret_fields_configured"] = ["confirmation_phrase"]
        else:
            current["armed_at"] = 0.0
            current["secret_fields_configured"] = []
        self._save_settings(current)
        self._event(
            "host_execution_settings_updated",
            {
                "unrestricted_host_mode": bool(current.get("unrestricted_host_mode")),
                "allowed_root": current.get("allowed_root"),
                "allow_source_mutation": bool(current.get("allow_source_mutation")),
            },
        )
        return {"ok": True, "settings": self.settings()}

    def run_command(
        self,
        command: list[str],
        *,
        purpose: str = "",
        cwd: str | Path | None = None,
        input_text: str = "",
    ) -> dict[str, Any]:
        ready = self._require_armed()
        if ready:
            return ready
        settings = self._raw_settings()
        if not command or not all(isinstance(part, str) and part for part in command):
            return {"ok": False, "error": "command must be a non-empty list of strings"}
        root = Path(str(settings["allowed_root"])).expanduser().resolve()
        workdir = Path(cwd).expanduser().resolve() if cwd else root
        if not _is_under(workdir, root):
            return {"ok": False, "error": f"cwd is outside allowed root: {workdir}"}
        run_id = _stable_id("host-command", _now(), command, purpose)
        audit = self._audit_dir() / run_id
        audit.mkdir(parents=True, exist_ok=True)
        started = _now()
        try:
            completed = subprocess.run(
                command,
                cwd=str(workdir),
                input=input_text or None,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(settings.get("max_command_seconds") or 120),
                check=False,
            )
            payload = {
                "ok": completed.returncode == 0,
                "run_id": run_id,
                "purpose": purpose,
                "command": command,
                "cwd": str(workdir),
                "returncode": completed.returncode,
                "stdout": completed.stdout[-12000:],
                "stderr": completed.stderr[-12000:],
                "duration_ms": int((_now() - started) * 1000),
                "audit_dir": str(audit),
            }
        except subprocess.TimeoutExpired as exc:
            payload = {
                "ok": False,
                "run_id": run_id,
                "purpose": purpose,
                "command": command,
                "cwd": str(workdir),
                "error": f"Command timed out after {settings.get('max_command_seconds')} seconds",
                "stdout": str(exc.stdout or "")[-12000:],
                "stderr": str(exc.stderr or "")[-12000:],
                "duration_ms": int((_now() - started) * 1000),
                "audit_dir": str(audit),
            }
        (audit / "result.json").write_text(json.dumps(_redact_value(payload), indent=2, sort_keys=True), encoding="utf-8")
        self._event("host_command_run", {"run_id": run_id, "purpose": purpose, "ok": bool(payload.get("ok"))})
        return _redact_value(payload)

    def apply_self_edit(self, patch_text: str, *, objective: str = "") -> dict[str, Any]:
        ready = self._require_armed(require_source_mutation=True)
        if ready:
            return ready
        settings = self._raw_settings()
        root = Path(str(settings["allowed_root"])).expanduser().resolve()
        run_id = _stable_id("self-edit", _now(), objective, patch_text[:500])
        audit = self._audit_dir() / run_id
        audit.mkdir(parents=True, exist_ok=True)
        (audit / "requested.patch").write_text(patch_text, encoding="utf-8")
        try:
            file_patches = _parse_unified_diff(patch_text)
            changes = _apply_file_patches(root, file_patches)
        except ValueError as exc:
            payload = {"ok": False, "error": str(exc), "run_id": run_id, "audit_dir": str(audit)}
            (audit / "result.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            self._event("host_self_edit_rejected", {"run_id": run_id, "error": str(exc)[:240]})
            return payload
        revert_parts: list[str] = []
        applied_parts: list[str] = []
        for change in changes:
            rel = change["path"]
            before = change["before"]
            after = change["after"]
            revert_parts.extend(
                difflib.unified_diff(after, before, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="")
            )
            applied_parts.extend(
                difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="")
            )
        applied_patch = audit / "applied.patch"
        revert_patch = audit / "revert.patch"
        applied_patch.write_text("\n".join(applied_parts) + ("\n" if applied_parts else ""), encoding="utf-8")
        revert_patch.write_text("\n".join(revert_parts) + ("\n" if revert_parts else ""), encoding="utf-8")
        payload = {
            "ok": True,
            "run_id": run_id,
            "objective": objective,
            "changed_files": [change["path"] for change in changes],
            "audit": {
                "dir": str(audit),
                "requested_patch": str(audit / "requested.patch"),
                "applied_patch": str(applied_patch),
                "revert_patch": str(revert_patch),
            },
            "policy": {
                "unrestricted_host_mode": True,
                "allowed_root": str(root),
                "source_mutation": "enabled",
            },
        }
        (audit / "result.json").write_text(json.dumps(_redact_value(payload), indent=2, sort_keys=True), encoding="utf-8")
        self._event("host_self_edit_applied", {"run_id": run_id, "changed_files": payload["changed_files"]})
        return _redact_value(payload)

    def _raw_settings(self) -> dict[str, Any]:
        path = _settings_path(self.state_dir)
        if not path.exists():
            return asdict(self._default_settings())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return asdict(self._default_settings())
        if not isinstance(data, dict):
            return asdict(self._default_settings())
        return {**asdict(self._default_settings()), **data}

    def _save_settings(self, data: dict[str, Any]) -> None:
        path = _settings_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_redact_value(data), indent=2, sort_keys=True), encoding="utf-8")

    def _audit_dir(self) -> Path:
        settings = self._raw_settings()
        audit = Path(str(settings.get("audit_dir") or self.state_dir / "host_execution_audit")).expanduser().resolve()
        audit.mkdir(parents=True, exist_ok=True)
        return audit

    def _event(self, event_type: str, detail: dict[str, Any]) -> None:
        path = _events_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "id": _stable_id(event_type, _now(), detail),
            "timestamp": _now(),
            "event_type": event_type,
            "detail": _redact_value(detail),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _require_armed(self, *, require_source_mutation: bool = False) -> dict[str, Any] | None:
        settings = self._raw_settings()
        if not settings.get("unrestricted_host_mode"):
            return {"ok": False, "error": "Host execution is not armed. Enable unrestricted host mode first."}
        if require_source_mutation and not settings.get("allow_source_mutation", True):
            return {"ok": False, "error": "Source mutation is disabled in host execution settings."}
        return None


def _parse_unified_diff(patch_text: str) -> list[dict[str, Any]]:
    lines = patch_text.splitlines()
    patches: list[dict[str, Any]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line.startswith("--- "):
            idx += 1
            continue
        old_name = line[4:].strip()
        idx += 1
        if idx >= len(lines) or not lines[idx].startswith("+++ "):
            raise ValueError("Malformed unified diff: missing +++ file header")
        new_name = lines[idx][4:].strip()
        path = _normalize_patch_path(new_name if new_name != "/dev/null" else old_name)
        idx += 1
        hunks: list[list[str]] = []
        while idx < len(lines) and not lines[idx].startswith("--- "):
            if lines[idx].startswith("@@ "):
                hunk: list[str] = [lines[idx]]
                idx += 1
                while idx < len(lines) and not lines[idx].startswith("@@ ") and not lines[idx].startswith("--- "):
                    hunk.append(lines[idx])
                    idx += 1
                hunks.append(hunk)
            else:
                idx += 1
        if not hunks:
            raise ValueError(f"Malformed unified diff: no hunks for {path}")
        patches.append({"path": path, "hunks": hunks})
    if not patches:
        raise ValueError("No unified diff file changes found")
    return patches


def _normalize_patch_path(raw: str) -> str:
    value = raw.strip().split("\t", 1)[0]
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    path = Path(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"Patch path is outside allowed root: {raw}")
    if not value or value == "/dev/null":
        raise ValueError("Patch path is empty")
    return value.replace("\\", "/")


def _apply_file_patches(root: Path, patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for patch in patches:
        rel = str(patch["path"])
        target = (root / rel).resolve()
        if not _is_under(target, root):
            raise ValueError(f"Patch target is outside allowed root: {rel}")
        before = target.read_text(encoding="utf-8").splitlines(keepends=True) if target.exists() else []
        current = list(before)
        cursor = 0
        for hunk in patch["hunks"]:
            old_block: list[str] = []
            new_block: list[str] = []
            for line in hunk[1:]:
                if not line:
                    marker = " "
                    body = ""
                else:
                    marker = line[0]
                    body = line[1:]
                if marker == "\\":
                    continue
                normalized = body + "\n"
                if marker in {" ", "-"}:
                    old_block.append(normalized)
                if marker in {" ", "+"}:
                    new_block.append(normalized)
                if marker not in {" ", "-", "+"}:
                    raise ValueError(f"Unsupported patch line marker: {marker}")
            position = _find_block(current, old_block, start=cursor)
            if position < 0:
                raise ValueError(f"Patch hunk does not match current file: {rel}")
            current[position : position + len(old_block)] = new_block
            cursor = position + len(new_block)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(current), encoding="utf-8")
        changes.append({"path": rel, "before": before, "after": current})
    return changes


def _find_block(lines: list[str], block: list[str], *, start: int = 0) -> int:
    if not block:
        return max(0, min(start, len(lines)))
    for idx in range(max(0, start), len(lines) - len(block) + 1):
        if lines[idx : idx + len(block)] == block:
            return idx
    for idx in range(0, max(0, start)):
        if lines[idx : idx + len(block)] == block:
            return idx
    return -1
