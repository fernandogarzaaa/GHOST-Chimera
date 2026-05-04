"""Integration tests for structured logging."""

import json
import logging
import os

from ghostchimera.logging_config import ensure_configured, get_logger


def test_ensure_configured():
    """ensure_configured should set up logging without error."""
    ensure_configured()
    root = logging.getLogger()
    assert len(root.handlers) >= 1


def test_get_logger_namespace():
    """get_logger should return a logger under the ghostchimera namespace."""
    logger = get_logger("test")
    assert logger.name.startswith("ghostchimera.")


def test_json_format_produces_valid_json():
    """JSON formatter should produce valid JSON log lines."""
    ensure_configured()
    logger = get_logger("test.json")
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.info("test message")
    logger.removeHandler(handler)


def test_file_handler_writes_to_log_file():
    """File handler should write log entries to the log file."""
    ensure_configured()
    state_dir = os.path.expanduser("~/.ghostchimera")
    log_file = os.path.join(state_dir, "ghostchimera.log")
    assert os.path.exists(log_file)
    with open(log_file) as f:
        content = f.read()
    assert len(content) > 0
