from __future__ import annotations

import json

from policy_engine import DomainCacheStore, downgrade_blocked_spam


def test_domain_cache_spam_true_forces_spam(tmp_path):
    cache_file = tmp_path / "domain_cache.json"
    cache_file.write_text(json.dumps({"bankrollreview.com": {"spam": True, "category": None}}), encoding="utf-8")
    store = DomainCacheStore(cache_file)

    decision = store.evaluate("bankrollreview.com")
    assert decision.forced_category == "spam"
    assert decision.spam_forbidden is False


def test_domain_cache_spam_false_with_category_forces_category(tmp_path):
    cache_file = tmp_path / "domain_cache.json"
    cache_file.write_text(json.dumps({"meijer.one": {"spam": False, "category": "persoonlijk_important"}}), encoding="utf-8")
    store = DomainCacheStore(cache_file)

    decision = store.evaluate("meijer.one")
    assert decision.forced_category == "persoonlijk_important"
    assert decision.spam_forbidden is True


def test_domain_cache_spam_false_without_category_blocks_spam_and_downgrades(tmp_path):
    cache_file = tmp_path / "domain_cache.json"
    cache_file.write_text(json.dumps({"bol.com": {"spam": False, "category": None}}), encoding="utf-8")
    store = DomainCacheStore(cache_file)

    decision = store.evaluate("bol.com")
    assert decision.forced_category is None
    assert decision.spam_forbidden is True

    downgrade_updates = downgrade_blocked_spam({"list_unsubscribe": "<mailto:abc@example.com>", "list_id": "", "precedence": ""})
    downgrade_promotions = downgrade_blocked_spam({"list_unsubscribe": "", "list_id": "", "precedence": ""})
    assert downgrade_updates == "updates"
    assert downgrade_promotions == "promotions"
