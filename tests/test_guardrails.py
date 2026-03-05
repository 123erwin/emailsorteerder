from __future__ import annotations

from policy_engine import is_obvious_spam


def test_guardrail_gambling_keyword_triggers():
    assert is_obvious_spam("random-domain.com", "Huge Jackpot Today", "Claim your bonus now", []) is True


def test_guardrail_you_won_crypto_giveaway_triggers():
    assert is_obvious_spam("random-domain.com", "You won", "Join this crypto-giveaway now", []) is True


def test_guardrail_phone_trick_pattern_triggers():
    body = "Urgent verify needed. Call immediately at +31 6 12345678 to complete payment."
    assert is_obvious_spam("safe-domain.com", "Account issue", body, []) is True


def test_guardrail_receipt_plus_rare_domain_triggers():
    body = "Payment completed. Keep your document pdf token for bookkeeping."
    assert is_obvious_spam("invoice-9988777-xz.com", "Receipt", body, []) is True


def test_guardrail_legitimate_message_not_triggered():
    body = "Your package is onderweg. Bekijk de tracking in je account."
    assert is_obvious_spam("bol.com", "Bestelling update", body, ["https://bol.com/track"]) is False
