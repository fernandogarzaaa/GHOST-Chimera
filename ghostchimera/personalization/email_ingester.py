"""Email ingestion for Ghost Chimera personal memory.

Parses .eml files, .mbox archives, and raw RFC 2822 email text, then
stores the extracted content in a :class:`~ghostchimera.memory_layer.store.MemoryStore`
for later retrieval by the personal-context pipeline.

All extraction relies only on the Python standard library (``email``,
``mailbox``, ``re``).  No network access is performed.
"""

from __future__ import annotations

import email
import email.header
import email.policy
import mailbox
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory_layer.store import MemoryStore

_MAX_BODY_PREVIEW_CHARS: int = 2_000


@dataclass(frozen=True)
class EmailRecord:
    """Extracted fields from a single email message."""

    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str
    body: str
    source_path: str
    message_id: str = ""

    def to_memory_content(self) -> str:
        """Return a flat text representation suitable for FTS indexing."""
        parts: list[str] = []
        if self.subject:
            parts.append(f"Subject: {self.subject}")
        if self.sender:
            parts.append(f"From: {self.sender}")
        if self.recipients:
            parts.append(f"To: {', '.join(self.recipients)}")
        if self.date:
            parts.append(f"Date: {self.date}")
        if self.body:
            parts.append(f"\n{self.body[:_MAX_BODY_PREVIEW_CHARS]}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "sender": self.sender,
            "recipients": list(self.recipients),
            "date": self.date,
            "body": self.body[:500],
            "source_path": self.source_path,
            "message_id": self.message_id,
        }


@dataclass
class EmailIngestResult:
    """Summary of an email ingestion operation."""

    ingested: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    records: list[EmailRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingested": self.ingested,
            "skipped": self.skipped,
            "errors": self.errors,
            "records": [r.to_dict() for r in self.records],
        }


# ── Internal helpers ─────────────────────────────────────────────────────────


def _decode_header_value(value: str | None) -> str:
    """Decode an email header value, handling RFC 2047 encoded words."""
    if not value:
        return ""
    decoded_parts = email.header.decode_header(str(value))
    parts: list[str] = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                parts.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                parts.append(part.decode("utf-8", errors="replace"))
        else:
            parts.append(str(part))
    return " ".join(parts).strip()


def _extract_body(msg: email.message.Message) -> str:
    """Extract the plain-text body from an email message."""
    body_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body_parts.append(payload.decode(charset, errors="replace"))
                except Exception:  # noqa: BLE001
                    pass
    else:
        content_type = msg.get_content_type()
        if content_type in ("text/plain", "text/html"):
            try:
                charset = msg.get_content_charset() or "utf-8"
                payload = msg.get_payload(decode=True)
                if isinstance(payload, bytes):
                    text = payload.decode(charset, errors="replace")
                    if content_type == "text/html":
                        text = re.sub(r"<[^>]+>", " ", text)
                        text = re.sub(r"\s+", " ", text)
                    body_parts.append(text)
            except Exception:  # noqa: BLE001
                pass
    return "\n\n".join(body_parts).strip()


def _msg_to_record(msg: email.message.Message, source_path: str) -> EmailRecord:
    subject = _decode_header_value(str(msg.get("Subject") or ""))
    sender = _decode_header_value(str(msg.get("From") or ""))
    to = _decode_header_value(str(msg.get("To") or ""))
    date = _decode_header_value(str(msg.get("Date") or ""))
    message_id = _decode_header_value(str(msg.get("Message-ID") or ""))
    recipients = tuple(r.strip() for r in to.split(",") if r.strip())
    body = _extract_body(msg)
    return EmailRecord(
        subject=subject,
        sender=sender,
        recipients=recipients,
        date=date,
        body=body,
        source_path=source_path,
        message_id=message_id,
    )


# ── Public class ─────────────────────────────────────────────────────────────


class EmailIngester:
    """Ingest emails from files or raw text into a MemoryStore.

    Supports:

    * ``.eml`` files — single RFC 2822 message files
    * ``.mbox`` files — Unix mbox archives (e.g. Gmail Takeout exports)
    * Raw email strings — pasted directly from a mail client
    * Directories — recursively discovers ``.eml`` and ``.mbox`` files

    Duplicate content is silently skipped via
    :meth:`~ghostchimera.memory_layer.store.MemoryStore.add_document_once`.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store

    # ── Ingestion methods ────────────────────────────────────────────────

    def ingest_eml_file(self, path: str | Path) -> EmailIngestResult:
        """Parse a single ``.eml`` file and add it to memory."""
        p = Path(path).expanduser()
        result = EmailIngestResult()
        try:
            with p.open("rb") as f:
                msg = email.message_from_binary_file(f, policy=email.policy.compat32)
            record = _msg_to_record(msg, str(p))
            content = record.to_memory_content()
            if not content.strip():
                result.skipped += 1
            else:
                _, is_new = self.memory_store.add_document_once(
                    source="email",
                    content=content,
                    metadata={
                        "subject": record.subject,
                        "sender": record.sender,
                        "date": record.date,
                        "path": str(p),
                    },
                )
                if is_new:
                    result.ingested += 1
                    result.records.append(record)
                else:
                    result.skipped += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{p}: {exc}")
        return result

    def ingest_mbox_file(self, path: str | Path, *, max_messages: int = 500) -> EmailIngestResult:
        """Parse a ``.mbox`` archive and add all messages to memory."""
        p = Path(path).expanduser()
        result = EmailIngestResult()
        try:
            mbox = mailbox.mbox(str(p))
            for i, msg in enumerate(mbox):
                if i >= max_messages:
                    break
                try:
                    record = _msg_to_record(msg, str(p))
                    content = record.to_memory_content()
                    if not content.strip():
                        result.skipped += 1
                        continue
                    _, is_new = self.memory_store.add_document_once(
                        source="email",
                        content=content,
                        metadata={
                            "subject": record.subject,
                            "sender": record.sender,
                            "date": record.date,
                            "path": str(p),
                            "index": i,
                        },
                    )
                    if is_new:
                        result.ingested += 1
                        result.records.append(record)
                    else:
                        result.skipped += 1
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"message {i}: {exc}")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"mbox open: {exc}")
        return result

    def ingest_raw_email(self, raw_text: str, *, source_label: str = "email-paste") -> EmailIngestResult:
        """Parse a raw RFC 2822 email string and ingest it."""
        result = EmailIngestResult()
        try:
            msg = email.message_from_string(raw_text, policy=email.policy.compat32)
            record = _msg_to_record(msg, source_label)
            content = record.to_memory_content()
            if not content.strip():
                result.skipped += 1
            else:
                _, is_new = self.memory_store.add_document_once(
                    source="email",
                    content=content,
                    metadata={
                        "subject": record.subject,
                        "sender": record.sender,
                        "date": record.date,
                    },
                )
                if is_new:
                    result.ingested += 1
                    result.records.append(record)
                else:
                    result.skipped += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"parse error: {exc}")
        return result

    def ingest_directory(self, directory: str | Path, *, max_files: int = 1000) -> EmailIngestResult:
        """Recursively ingest all ``.eml`` and ``.mbox`` files in *directory*."""
        d = Path(directory).expanduser()
        combined = EmailIngestResult()
        count = 0
        for ext, handler in (
            (".eml", self.ingest_eml_file),
            (".mbox", self.ingest_mbox_file),
        ):
            for p in sorted(d.rglob(f"*{ext}")):
                if count >= max_files:
                    break
                sub = handler(p)  # type: ignore[operator]
                combined.ingested += sub.ingested
                combined.skipped += sub.skipped
                combined.errors.extend(sub.errors)
                combined.records.extend(sub.records)
                count += 1
        return combined
