from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlparse

from cache_store import SenderCacheStore
from logging_setup import RunLogger


def extract_sender_email(raw_sender: str) -> str:
    _, email = parseaddr(raw_sender or "")
    return (email or raw_sender or "").strip().lower()


def extract_domain_from_sender(raw_sender: str) -> str:
    sender = extract_sender_email(raw_sender)
    if "@" not in sender:
        return ""
    return sender.split("@", 1)[1].strip().lower()


def extract_url_domains(urls: list[str]) -> list[str]:
    result = []
    seen = set()
    for url in urls or []:
        host = (urlparse(url).hostname or "").lower().strip()
        if not host or host in seen:
            continue
        seen.add(host)
        result.append(host)
    return result


@dataclass(frozen=True)
class DomainDecision:
    forced_category: str | None
    spam_forbidden: bool


class DomainCacheStore:
    def __init__(self, cache_file: Path) -> None:
        self.cache_file = cache_file
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.cache_file.exists():
            self.cache_file.write_text("{}", encoding="utf-8")
        self._data = self._load()

    def _load(self) -> dict:
        if not self.cache_file.is_file():
            return {}
        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return raw
        except Exception:
            return {}
        return {}

    def is_spam_forbidden_domain(self, domain: str) -> bool:
        entry = self._data.get((domain or "").lower())
        if not isinstance(entry, dict):
            return False
        return entry.get("spam") is False

    def evaluate(self, domain: str) -> DomainDecision:
        entry = self._data.get((domain or "").lower())
        if not isinstance(entry, dict):
            return DomainDecision(forced_category=None, spam_forbidden=False)

        spam = entry.get("spam")
        category = entry.get("category")
        if spam is True:
            return DomainDecision(forced_category="spam", spam_forbidden=False)
        if spam is False and category:
            return DomainDecision(forced_category=str(category).strip().lower(), spam_forbidden=True)
        if spam is False:
            return DomainDecision(forced_category=None, spam_forbidden=True)
        return DomainDecision(forced_category=None, spam_forbidden=False)


class SpamSenderCacheStore:
    def __init__(self, cache_file: Path, run_logger: RunLogger | None = None) -> None:
        self.cache_file = cache_file
        self.run_logger = run_logger
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.cache_file.exists():
            self.cache_file.write_text("{}", encoding="utf-8")
        self._data = self._load_and_upgrade()

    def _load_and_upgrade(self) -> dict[str, dict]:
        if not self.cache_file.is_file():
            return {}
        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return {}

        if not isinstance(raw, dict):
            return {}

        data = {}
        for sender, value in raw.items():
            if isinstance(value, dict):
                data[sender.lower()] = {
                    "spam_hits": int(value.get("spam_hits", 0) or 0),
                    "last_seen": str(value.get("last_seen", "")),
                    "manual_override": value.get("manual_override"),
                    "subject": str(value.get("subject", "(geen subject)") or "(geen subject)"),
                }
            else:
                data[sender.lower()] = {
                    "spam_hits": 0,
                    "last_seen": "",
                    "manual_override": None,
                    "subject": "(geen subject)",
                }
        return data

    def save(self) -> None:
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def eligible_spam(self, sender: str, threshold: int) -> bool:
        entry = self._data.get(sender.lower())
        if not entry:
            return False
        if entry.get("manual_override") not in (None, "", "spam"):
            return False
        return int(entry.get("spam_hits", 0) or 0) >= threshold

    def increment_spam_hit(self, sender: str, subject: str) -> int:
        key = sender.lower()
        entry = self._data.setdefault(
            key,
            {"spam_hits": 0, "last_seen": "", "manual_override": None, "subject": "(geen subject)"},
        )
        entry["spam_hits"] = int(entry.get("spam_hits", 0) or 0) + 1
        entry["last_seen"] = datetime.now().date().isoformat()
        entry["subject"] = (subject or "(geen subject)").strip() or "(geen subject)"
        return entry["spam_hits"]

    def apply_startup_reconciliation(
        self,
        sender_exact_cache: SenderCacheStore,
        domain_cache: DomainCacheStore,
    ) -> tuple[int, int]:
        moved_overrides = 0
        removed_domain_entries = 0
        senders_to_remove = []

        for sender, value in list(self._data.items()):
            manual_override = (value.get("manual_override") or "").strip().lower()
            if manual_override and manual_override != "spam":
                sender_exact_cache.update(sender, manual_override, "(manual_override)")
                senders_to_remove.append(sender)
                moved_overrides += 1
                continue

            domain = extract_domain_from_sender(sender)
            if domain and domain_cache.is_spam_forbidden_domain(domain):
                senders_to_remove.append(sender)
                removed_domain_entries += 1

        for sender in senders_to_remove:
            self._data.pop(sender, None)

        if moved_overrides or removed_domain_entries:
            sender_exact_cache.save()
            self.save()
            if self.run_logger:
                if moved_overrides:
                    self.run_logger.event("startup_reconcile", f"manual_override->exact: {moved_overrides}")
                if removed_domain_entries:
                    self.run_logger.event("startup_reconcile", f"spam_cache_removed_by_domain: {removed_domain_entries}")

        return moved_overrides, removed_domain_entries


def _is_rare_domain(domain: str) -> bool:
    if not domain:
        return True
    common = {
        "gmail.com",
        "outlook.com",
        "hotmail.com",
        "yahoo.com",
        "icloud.com",
        "google.com",
        "microsoft.com",
        "apple.com",
        "paypal.com",
        "amazon.com",
        "bol.com",
    }
    d = domain.lower()
    if d in common:
        return False
    if d.count("-") >= 2:
        return True
    return bool(re.search(r"\d{3,}", d))


def is_obvious_spam(from_domain: str, subject: str, body_snippet: str, url_domains: list[str]) -> bool:
    text = f"{subject or ''} {body_snippet or ''}".lower()

    gambling_terms = [
        "casino",
        "bet",
        "winplay",
        "luckythrillz",
        "gowinspin",
        "zodiacbet",
        "bonus",
        "jackpot",
        "you won",
        "crypto-giveaway",
    ]
    if any(term in text for term in gambling_terms):
        return True

    has_phone = bool(re.search(r"(?:\+?\d[\d\s\-()]{7,}\d)", text))
    has_call_now = any(term in text for term in ["call now", "call immediately", "bel nu", "bel direct"])
    has_urgent_payment_verify = any(term in text for term in ["urgent", "betaal", "betaling", "verify", "verifieer"])
    if has_phone and has_call_now and has_urgent_payment_verify:
        return True

    receipt_terms = [
        "receipt",
        "payment completed",
        "pdf token",
        "bookkeeping",
        "keep your document pdf",
    ]
    if any(term in text for term in receipt_terms):
        if _is_rare_domain(from_domain) or any(_is_rare_domain(d) for d in (url_domains or [])):
            return True

    return False


def downgrade_blocked_spam(headers: dict[str, str]) -> str:
    list_unsubscribe = (headers or {}).get("list_unsubscribe", "") or ""
    list_id = (headers or {}).get("list_id", "") or ""
    precedence = (headers or {}).get("precedence", "") or ""
    if list_unsubscribe.strip() or list_id.strip() or "bulk" in precedence.lower():
        return "updates"
    return "promotions"
