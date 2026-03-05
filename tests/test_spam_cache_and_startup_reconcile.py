from __future__ import annotations

import json
import logging

from cache_store import SenderCacheStore
from policy_engine import DomainCacheStore, SpamSenderCacheStore


class DummyRunLogger:
    def event(self, _context: str, _message: str) -> None:
        return


def test_spam_cache_threshold(tmp_path):
    spam_file = tmp_path / "sender_spam_cache.json"
    spam_file.write_text(
        json.dumps(
            {
                "sender@example.com": {"spam_hits": 1, "last_seen": "2026-02-20", "manual_override": None},
                "trusted@example.com": {"spam_hits": 10, "last_seen": "2026-02-20", "manual_override": "updates"},
            }
        ),
        encoding="utf-8",
    )
    store = SpamSenderCacheStore(spam_file)

    assert store.eligible_spam("sender@example.com", threshold=2) is False
    assert store.eligible_spam("sender@example.com", threshold=1) is True
    assert store.eligible_spam("trusted@example.com", threshold=2) is False


def test_increment_spam_hit_logs_subject(tmp_path):
    spam_file = tmp_path / "sender_spam_cache.json"
    spam_file.write_text("{}", encoding="utf-8")
    store = SpamSenderCacheStore(spam_file)

    hits = store.increment_spam_hit("sender@example.com", "Act now bonus")
    store.save()
    data = json.loads(spam_file.read_text(encoding="utf-8"))

    assert hits == 1
    assert data["sender@example.com"]["subject"] == "Act now bonus"


def test_startup_manual_override_moves_to_exact_and_removes_spam_entry(tmp_path):
    exact_file = tmp_path / "sender_exact.json"
    domain_file = tmp_path / "domain_cache.json"
    spam_file = tmp_path / "sender_spam_cache.json"

    exact_file.write_text("{}", encoding="utf-8")
    domain_file.write_text(json.dumps({"clean-domain.com": {"spam": False, "category": None}}), encoding="utf-8")
    spam_file.write_text(
        json.dumps(
            {
                "manual@example.com": {"spam_hits": 2, "last_seen": "2026-02-20", "manual_override": "purchases"},
                "blocked@clean-domain.com": {"spam_hits": 4, "last_seen": "2026-02-20", "manual_override": None},
                "keep@other-domain.com": {"spam_hits": 5, "last_seen": "2026-02-20", "manual_override": None},
            }
        ),
        encoding="utf-8",
    )

    run_logger = DummyRunLogger()
    exact_store = SenderCacheStore(exact_file, logger=logging.getLogger("test"), run_logger=run_logger)
    domain_store = DomainCacheStore(domain_file)
    spam_store = SpamSenderCacheStore(spam_file, run_logger=run_logger)

    moved_overrides, removed_domain_entries = spam_store.apply_startup_reconciliation(exact_store, domain_store)

    assert moved_overrides == 1
    assert removed_domain_entries == 1

    exact_data = json.loads(exact_file.read_text(encoding="utf-8"))
    spam_data = json.loads(spam_file.read_text(encoding="utf-8"))

    assert exact_data["manual@example.com"]["categorie"] == "purchases"
    assert "manual@example.com" not in spam_data
    assert "blocked@clean-domain.com" not in spam_data
    assert "keep@other-domain.com" in spam_data
