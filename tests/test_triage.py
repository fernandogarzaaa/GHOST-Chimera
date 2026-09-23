"""Triage scorer: buckets, VIP, digests. No network, no models."""

from __future__ import annotations

from ghostchimera.integrations.triage import (
    load_vip_senders,
    save_vip_senders,
    score_message,
    triage_messages,
)


def _msg(sender="news@x.com", subject="Weekly digest", snippet="unsubscribe here", uid="1"):
    return {"uid": uid, "from": sender, "subject": subject, "snippet": snippet}


def test_vip_urgent_scores_act_now() -> None:
    out = score_message(
        _msg(sender="Boss <boss@x.com>", subject="URGENT: deploy blocked", snippet="need approval"),
        vip_senders=["boss@x.com"],
    )
    assert out["tier"] == "act_now" and out["score"] >= 70
    assert any("VIP" in reason for reason in out["reasons"])


def test_newsletter_demoted_to_fyi() -> None:
    out = score_message(_msg())
    assert out["tier"] == "fyi" and out["score"] < 40


def test_plain_mail_lands_today_or_fyi() -> None:
    out = score_message(_msg(sender="colleague@x.com", subject="lunch?", snippet="tacos at noon"))
    assert out["tier"] in ("today", "fyi")


def test_direct_address_and_thread_boost() -> None:
    base = score_message(_msg(sender="a@x.com", subject="slides", snippet="see attached"), user_email="me@x.com")
    threaded = score_message(
        _msg(sender="a@x.com", subject="slides", snippet="see attached"), user_email="me@x.com", thread_replied=True
    )
    assert threaded["score"] > base["score"]


def test_triage_buckets_sorted_and_digested() -> None:
    messages = [
        _msg(sender="Boss <boss@x.com>", subject="URGENT: deploy", snippet="need approval now", uid="1"),
        _msg(uid="2"),
        _msg(sender="friend@x.com", subject="party saturday", snippet="bring snacks", uid="3"),
    ]
    out = triage_messages(messages, vip_senders=["boss@x.com"])
    assert out["counts"] == {"act_now": 1, "today": 0, "fyi": 2}
    assert out["buckets"]["act_now"][0]["uid"] == "1"
    assert "party saturday" in out["digest"]


def test_vip_list_round_trip(tmp_path) -> None:
    assert load_vip_senders(tmp_path) == []
    saved = save_vip_senders(tmp_path, [" boss@x.com ", "", "boss@x.com", "team@x.com"])
    assert saved == ["boss@x.com", "team@x.com"]
    assert load_vip_senders(tmp_path) == ["boss@x.com", "team@x.com"]


def test_vip_list_capped_and_missing_file(tmp_path) -> None:
    save_vip_senders(tmp_path, [f"user{i}@x.com" for i in range(150)])
    assert len(load_vip_senders(tmp_path)) == 100
