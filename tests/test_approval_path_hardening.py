"""Tests for approval-path hardening: fail-closed cleanup, observable audit.

Covers the behavioral fixes from the approval-gates hardening workstream:
  * browser_vault._shred_temp_copy fails closed when a credential copy
    cannot be removed (never leaves browser login material on disk silently)
  * AuditTrail.record never crashes its caller but logs lost writes instead
    of swallowing them
  * AutomationsEngine._notify logs an unavailable audit engine instead of
    swallowing the failure
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ghostchimera.connectors.audit_trail import AuditTrail
from ghostchimera.connectors.automations import AutomationsEngine
from ghostchimera.connectors.browser_vault import (
    BrowserVaultError,
    _read_rows,
    _shred_temp_copy,
)


class ShredTempCopyTests(unittest.TestCase):
    def test_shreds_and_removes(self):
        with tempfile.NamedTemporaryFile(prefix="shred-test-", delete=False) as handle:
            handle.write(b"secret-material-12345")
            tmp = handle.name
        try:
            _shred_temp_copy(tmp)
            self.assertFalse(os.path.exists(tmp), "temp copy must be removed")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_already_gone_is_fine(self):
        _shred_temp_copy("/tmp/ghostchimera-shred-test-does-not-exist-12345")

    def test_removal_failure_raises(self):
        """Fail closed: file still present after failed removal -> raise."""
        with tempfile.NamedTemporaryFile(prefix="shred-test-", delete=False) as handle:
            handle.write(b"secret")
            tmp = handle.name
        try:
            with mock.patch("os.remove", side_effect=PermissionError("denied")):
                with self.assertRaises(BrowserVaultError):
                    _shred_temp_copy(tmp)
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_file_not_found_does_not_raise(self):
        """Already-gone file (FileNotFoundError race) must not raise."""
        with tempfile.NamedTemporaryFile(prefix="shred-test-", delete=False) as handle:
            handle.write(b"secret")
            tmp = handle.name
        try:
            with mock.patch("os.remove", side_effect=FileNotFoundError("gone")):
                _shred_temp_copy(tmp)  # must not raise
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_shred_overwrite_zeroes_before_remove(self):
        """The overwrite must actually happen: content is zeroed pre-remove."""
        with tempfile.NamedTemporaryFile(prefix="shred-test-", delete=False) as handle:
            handle.write(b"secret-material-12345")
            tmp = handle.name
        try:
            with mock.patch("os.remove", return_value=None):
                _shred_temp_copy(tmp)
            with open(tmp, "rb") as handle:
                content = handle.read()
            self.assertTrue(content, "file must still exist when remove is mocked")
            self.assertEqual(content, b"\x00" * len(content))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_overwrite_failure_still_removes(self):
        """A failed shred overwrite must not prevent removal."""
        with tempfile.NamedTemporaryFile(prefix="shred-test-", delete=False) as handle:
            handle.write(b"secret")
            tmp = handle.name
        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            if "r+b" in mode:
                raise OSError("shred write failed")
            return real_open(path, mode, *args, **kwargs)

        try:
            with mock.patch("builtins.open", side_effect=fake_open):
                _shred_temp_copy(tmp)
            self.assertFalse(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class AuditTrailFailureTests(unittest.TestCase):
    def test_record_never_raises_but_logs(self):
        with tempfile.TemporaryDirectory() as state_dir:
            trail = AuditTrail(state_dir)
            with mock.patch("builtins.open", side_effect=OSError("disk full")):
                with self.assertLogs("ghostchimera.audit_trail", level="WARNING") as logs:
                    trail.record("approval.denied", entity_id="e1")  # must not raise
        self.assertTrue(any("audit trail write failed" in m for m in logs.output))

    def test_record_unserializable_detail_does_not_raise(self):
        """Unserializable detail is dropped, never raised (no deep recursion)."""

        class _BadStr:
            def __str__(self):  # noqa: D105
                raise ValueError("bad __str__")

        with tempfile.TemporaryDirectory() as state_dir:
            trail = AuditTrail(state_dir)
            self.assertIsNone(trail.record("approval.requested", detail={"x": _BadStr()}))
            self.assertEqual(trail.recent(limit=5), [])

    def test_record_recursion_error_does_not_raise(self):
        """A runaway _redact (e.g. circular input) is dropped, never raised."""
        with tempfile.TemporaryDirectory() as state_dir:
            trail = AuditTrail(state_dir)
            with mock.patch(
                "ghostchimera.connectors.audit_trail._redact",
                side_effect=RecursionError("deep"),
            ):
                self.assertIsNone(trail.record("approval.requested", detail={"x": 1}))
            self.assertEqual(trail.recent(limit=5), [])

    def test_record_still_appends_normally(self):
        with tempfile.TemporaryDirectory() as state_dir:
            trail = AuditTrail(state_dir)
            trail.record("approval.requested", entity_id="e1", provider="p")
            recent = trail.recent(limit=5)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["event"], "approval.requested")
        self.assertEqual(recent[0]["entity_id"], "e1")
        self.assertEqual(recent[0]["provider"], "p")


def _make_engine_with_email_automation(
    state_dir: str, **trigger_overrides: object
) -> tuple[AutomationsEngine, str]:
    engine = AutomationsEngine(state_dir)
    trigger: dict[str, object] = {"type": "email", "key_id": "test-key"}
    trigger.update(trigger_overrides)
    record = engine.create(
        name="inbox-watch",
        instruction="watch",
        trigger=trigger,  # type: ignore[arg-type]
        action={"type": "log"},
        notify="neither",
    )
    return engine, record["id"]


def _mail_mocks(messages: list[dict[str, object]] | None = None):
    """Mock mail_basic + auth engine for _check_email tests."""
    fetch_result = {"messages": messages if messages is not None else []}
    return (
        mock.patch(
            "ghostchimera.integrations.mail_basic.resolve_app_password",
            return_value={"email": "u@x.test", "secret": "s"},
        ),
        mock.patch(
            "ghostchimera.integrations.mail_basic.fetch_inbox",
            return_value=fetch_result,
        ),
        mock.patch("ghostchimera.connectors.auth_engine.CustomAuthEngine"),
    )


class CheckEmailTests(unittest.TestCase):
    """_check_email: polling filters, dedup, and failure handling."""

    def test_missing_credentials_returns_no_runs(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(state_dir)
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks()
            with rap, fi, cae:
                with mock.patch(
                    "ghostchimera.integrations.mail_basic.resolve_app_password",
                    side_effect=ValueError("nope"),
                ):
                    self.assertEqual(engine._check_email(automation), [])

    def test_fetch_failure_returns_no_runs(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(state_dir)
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks()
            with rap, cae:
                with mock.patch(
                    "ghostchimera.integrations.mail_basic.fetch_inbox",
                    side_effect=ValueError("nope"),
                ):
                    self.assertEqual(engine._check_email(automation), [])

    def test_new_message_fires_run(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(state_dir)
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks(
                [{"uid": "u1", "from": "boss@x.test", "subject": "hello"}]
            )
            with rap, fi, cae:
                runs = engine._check_email(automation)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["trigger"]["uid"], "u1")
        self.assertEqual(runs[0]["status"], "complete")

    def test_seen_uid_not_refired(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(state_dir)
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks(
                [{"uid": "u1", "from": "boss@x.test", "subject": "hello"}]
            )
            with rap, fi, cae:
                self.assertEqual(len(engine._check_email(automation)), 1)
                self.assertEqual(engine._check_email(automation), [])

    def test_sender_filter_skips_non_matching(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(
                state_dir, sender="ceo@x.test"
            )
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks(
                [{"uid": "u1", "from": "boss@x.test", "subject": "hello"}]
            )
            with rap, fi, cae:
                self.assertEqual(engine._check_email(automation), [])

    def test_subject_filter_skips_non_matching(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(
                state_dir, subject="urgent"
            )
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks(
                [{"uid": "u1", "from": "boss@x.test", "subject": "hello"}]
            )
            with rap, fi, cae:
                self.assertEqual(engine._check_email(automation), [])

    def test_message_without_uid_skipped(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(state_dir)
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks([{"from": "boss@x.test", "subject": "hi"}])
            with rap, fi, cae:
                self.assertEqual(engine._check_email(automation), [])

    def test_deleted_automation_returns_no_runs(self):
        from ghostchimera.connectors.automations import AutomationError

        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_email_automation(state_dir)
            automation = engine._find_mutable(auto_id)
            rap, fi, cae = _mail_mocks()
            with rap, fi, cae:
                with mock.patch.object(
                    AutomationsEngine,
                    "_find_mutable",
                    side_effect=AutomationError("gone"),
                ):
                    self.assertEqual(engine._check_email(automation), [])


class NotifyFailureTests(unittest.TestCase):
    def test_notify_logs_unavailable_engine(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine = AutomationsEngine(state_dir)
            with mock.patch(
                "ghostchimera.connectors.auth_engine.CustomAuthEngine",
                side_effect=RuntimeError("boom"),
            ):
                with self.assertLogs("ghostchimera.automations", level="WARNING") as logs:
                    result = engine._notify(
                        {"name": "nightly"},
                        {"run_id": "r1", "status": "complete", "summary": "ok"},
                    )
        self.assertIsNone(result)
        self.assertTrue(any("audit engine unavailable" in m for m in logs.output))

    def test_notify_neither_skips_silently(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine = AutomationsEngine(state_dir)
            result = engine._notify(
                {"name": "nightly", "notify": "neither"},
                {"run_id": "r1", "status": "complete", "summary": "ok"},
            )
        self.assertIsNone(result)

    def test_notify_success_records_and_closes(self):
        """_notify wiring: audit.record called with truncated fields, engine closed."""
        with tempfile.TemporaryDirectory() as state_dir:
            engine = AutomationsEngine(state_dir)
            fake_audit = mock.Mock()
            fake_engine = mock.Mock()
            fake_engine.audit = fake_audit
            with mock.patch(
                "ghostchimera.connectors.auth_engine.CustomAuthEngine",
                return_value=fake_engine,
            ):
                engine._notify(
                    {"name": "n" * 70},
                    {"run_id": "r1", "status": "complete", "summary": "s" * 300},
                )
        fake_audit.record.assert_called_once()
        args, kwargs = fake_audit.record.call_args
        self.assertEqual(args[0], "automation.ran")
        self.assertEqual(kwargs["entity_id"], "console-user")
        self.assertEqual(kwargs["provider"], "n" * 60)
        self.assertEqual(len(kwargs["detail"]["summary"]), 200)
        self.assertEqual(kwargs["detail"]["run_id"], "r1")
        fake_engine.close.assert_called_once()


def _make_engine_with_log_automation(state_dir: str) -> tuple[AutomationsEngine, str]:
    from ghostchimera.connectors.automations import AutomationError  # noqa: F401

    engine = AutomationsEngine(state_dir)
    record = engine.create(
        name="nightly",
        instruction="observe",
        trigger={"type": "email", "key_id": "test-key"},
        action={"type": "log"},
        notify="neither",
    )
    return engine, record["id"]


class AutomationFireTests(unittest.TestCase):
    """fire() is the approval-gated execution path for scheduled work."""

    def test_paused_automation_refuses_to_fire(self):
        from ghostchimera.connectors.automations import AutomationError

        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            engine.set_enabled(auto_id, enabled=False)
            with self.assertRaisesRegex(AutomationError, "paused"):
                engine.fire(auto_id)

    def test_successful_log_run(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            run = engine.fire(auto_id, trigger_context={"type": "manual"})
        self.assertEqual(run["status"], "complete")
        self.assertIn("trigger observed", run["summary"])
        self.assertEqual(run["trigger"], {"type": "manual"})
        self.assertGreater(run["finished_at"], 0)

    def test_run_bookkeeping_recorded(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            engine.fire(auto_id)
            record = engine._find_mutable(auto_id)
        self.assertEqual(record["run_count"], 1)
        self.assertGreater(record["last_run_at"], 0)

    def test_failing_action_marks_run_failed(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            with mock.patch.object(
                AutomationsEngine, "_execute_action", side_effect=RuntimeError("boom")
            ):
                run = engine.fire(auto_id)
        self.assertEqual(run["status"], "failed")
        self.assertTrue(run["summary"].startswith("RuntimeError: boom"))

    def test_long_summaries_are_truncated(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            with mock.patch.object(
                AutomationsEngine,
                "_execute_action",
                return_value={"summary": "s" * 2000},
            ):
                run = engine.fire(auto_id)
            with mock.patch.object(
                AutomationsEngine,
                "_execute_action",
                side_effect=ValueError("e" * 2000),
            ):
                failed = engine.fire(auto_id)
        self.assertEqual(len(run["summary"]), 1000)
        self.assertEqual(len(failed["summary"]), 500)

    def test_long_note_is_truncated(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            run = engine.fire(auto_id, note="n" * 600)
        self.assertEqual(len(run["note"]), 500)

    def test_bookkeeping_survives_concurrent_delete(self):
        """Bookkeeping for a concurrently deleted automation is moot, not fatal."""
        from ghostchimera.connectors.automations import AutomationError

        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            record = engine._find_mutable(auto_id)
            with mock.patch.object(
                AutomationsEngine,
                "_find_mutable",
                side_effect=[record, AutomationError("gone")],
            ):
                with self.assertLogs("ghostchimera.automations", level="DEBUG") as logs:
                    run = engine.fire(auto_id)
        self.assertEqual(run["status"], "complete")
        self.assertTrue(any("skipping bookkeeping" in m for m in logs.output))

    def test_run_count_default_survives_legacy_record(self):
        """A store record missing run_count (legacy) still counts from zero."""
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            record = engine._find_mutable(auto_id)
            del record["run_count"]
            engine._save()
            fresh = AutomationsEngine(state_dir)
            fresh.fire(auto_id)
            record = fresh._find_mutable(auto_id)
        self.assertEqual(record["run_count"], 1)

    def test_bookkeeping_persisted_across_engines(self):
        """_save must persist; a fresh engine sees the run count."""
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            engine.fire(auto_id)
            fresh = AutomationsEngine(state_dir)
            record = fresh._find_mutable(auto_id)
        self.assertEqual(record["run_count"], 1)

    def test_run_history_recorded(self):
        """_record_run must append; runs() lists the finished run."""
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            run = engine.fire(auto_id)
            history = engine.runs(auto_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["run_id"], run["run_id"])
        self.assertEqual(history[0]["status"], "complete")

    def test_notify_called_after_run(self):
        """_notify wiring must exist; removing the call is caught."""
        with tempfile.TemporaryDirectory() as state_dir:
            engine, auto_id = _make_engine_with_log_automation(state_dir)
            with mock.patch.object(AutomationsEngine, "_notify") as notify:
                engine.fire(auto_id)
        notify.assert_called_once()
        self.assertEqual(notify.call_args[0][1]["status"], "complete")


def _make_login_db(path: Path, rows: list[tuple[str, str, bytes]]) -> None:
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE logins (origin_url TEXT, username_value TEXT,"
        " password_value BLOB, blacklisted_by_user INTEGER)"
    )
    conn.executemany(
        "INSERT INTO logins VALUES (?,?,?,0)",
        [(url, user, blob) for url, user, blob in rows],
    )
    conn.commit()
    conn.close()


class ReadRowsTests(unittest.TestCase):
    """_read_rows must fail loudly on corrupt stores, never silently."""

    def test_empty_db_returns_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [])
            self.assertEqual(_read_rows(db, b"fake-key", with_passwords=False), [])

    def test_empty_credentials_rows_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [("https://x.test", "", b"")])
            self.assertEqual(_read_rows(db, b"fake-key", with_passwords=False), [])

    def test_corrupt_db_raises_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            db.write_text("not a database", encoding="utf-8")
            with self.assertRaises(BrowserVaultError):
                _read_rows(db, b"fake-key", with_passwords=False)

    def test_undecryptable_password_degrades_to_empty(self):
        """A password that cannot be decrypted degrades; the read survives."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [("https://x.test", "alice", b"legacy-blob")])
            rows = _read_rows(db, b"fake-key", with_passwords=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["password"], "")

    def test_row_with_username_is_returned(self):
        """A row with a username is not skipped; guards the read-only URI."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [("https://x.test", "alice", b"")])
            rows = _read_rows(db, b"fake-key", with_passwords=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "alice")
        self.assertEqual(rows[0]["url"], "https://x.test")

    def test_long_fields_are_truncated(self):
        """URL/username truncation bounds are exact, not advisory."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [("https://x.test/" + "u" * 400, "a" * 200, b"")])
            rows = _read_rows(db, b"fake-key", with_passwords=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["url"]), 300)
        self.assertEqual(len(rows[0]["username"]), 160)

    def test_temp_copy_is_shredded(self):
        """The temp DB copy must not survive the read (credential hygiene)."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [])
            with mock.patch.object(tempfile, "tempdir", tmp):
                _read_rows(db, b"fake-key", with_passwords=False)
            leftovers = [p for p in Path(tmp).iterdir() if p.name.startswith("ghost-logins-")]
        self.assertEqual(leftovers, [])

    def test_no_fd_leak(self):
        """mkstemp fd and sqlite connection must both be closed."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Login Data"
            _make_login_db(db, [])
            before = set(os.listdir("/proc/self/fd"))
            _read_rows(db, b"fake-key", with_passwords=False)
            after = set(os.listdir("/proc/self/fd"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
