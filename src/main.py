from __future__ import annotations

import re

from imap_tools import MailBox

from cache_store import SenderCacheStore
from classifier import EmailClassifier
from config import load_settings
from imap_reader import fetch_in_chunks
from logging_setup import RunLogger, setup_app_logger
from policy_engine import (
    DomainCacheStore,
    SpamSenderCacheStore,
    downgrade_blocked_spam,
    extract_domain_from_sender,
    extract_sender_email,
    extract_url_domains,
    is_obvious_spam,
)


def _move_to_category_folder(box, msg, categorie: str, settings, logger, run_logger, ensured_folders: set[str]) -> None:
    if not settings.imap_move_by_category:
        return
    uid = getattr(msg, "uid", None)
    if not uid:
        return

    prefix = settings.imap_category_prefix or ""
    folder_delim = "/"
    try:
        inbox_info = box.folder.list("", "INBOX")
        if inbox_info and getattr(inbox_info[0], "delim", None):
            folder_delim = inbox_info[0].delim
    except Exception:
        pass
    normalized_prefix = re.sub(r"[\\/]+", folder_delim, prefix)
    primary_folder = f"{normalized_prefix}{categorie}"

    def ensure_and_move(target_folder: str) -> None:
        if target_folder not in ensured_folders:
            if not box.folder.exists(target_folder):
                box.folder.create(target_folder)
                try:
                    box.folder.subscribe(target_folder, True)
                except Exception:
                    pass
            ensured_folders.add(target_folder)
        box.move(uid, target_folder)

    try:
        ensure_and_move(primary_folder)
    except Exception as exc:
        err = str(exc)
        needs_inbox_prefix = (
            "nonexistent namespace" in err.lower()
            or "prefixed with: inbox" in err.lower()
        )
        if needs_inbox_prefix and not primary_folder.upper().startswith("INBOX" + folder_delim):
            fallback_folder = f"INBOX{folder_delim}{primary_folder}"
            try:
                ensure_and_move(fallback_folder)
                run_logger.event("imap_move_retry", f"{uid} -> {fallback_folder} (fallback from {primary_folder})")
                logger.info("IMAP move fallback gebruikt: %s -> %s", uid, fallback_folder)
                return
            except Exception as exc2:
                run_logger.event("imap_move", f"{uid} -> {fallback_folder}: {exc2}")
                logger.warning("IMAP move fallback mislukt: %s -> %s (%s)", uid, fallback_folder, exc2)
                return
        run_logger.event("imap_move", f"{uid} -> {primary_folder}: {exc}")
        logger.warning("IMAP move mislukt: %s -> %s (%s)", uid, primary_folder, exc)


def process_batch(batch, box, classifier, exact_cache, domain_cache, spam_cache, settings, logger, run_logger) -> None:
    unknown_items = []
    final_results = {}
    should_save_exact = False
    should_save_spam_cache = False
    ensured_folders: set[str] = set()

    for idx, msg in enumerate(batch):
        payload = classifier.build_email_payload(msg, idx)
        sender = extract_sender_email(msg.from_ or "")
        from_domain = extract_domain_from_sender(sender)
        headers = payload.get("headers", {}) or {}
        body_snippet = payload.get("body_snippet", "")
        url_domains = extract_url_domains(payload.get("urls", []))

        domain_decision = domain_cache.evaluate(from_domain)
        spam_forbidden = domain_decision.spam_forbidden

        if domain_decision.forced_category:
            final_results[idx] = {"categorie": domain_decision.forced_category, "bron": "domain_cache", "sender": sender}
            continue

        cached_category = exact_cache.get_category(sender)
        if cached_category:
            final_results[idx] = {"categorie": cached_category, "bron": "exact_cache", "sender": sender}
            continue

        if settings.use_spam_sender_cache and spam_cache.eligible_spam(sender, settings.spam_hits_threshold):
            if spam_forbidden:
                downgraded = downgrade_blocked_spam(headers)
                final_results[idx] = {
                    "categorie": downgraded,
                    "bron": "spam_blocked_by_domain_cache",
                    "sender": sender,
                }
            else:
                final_results[idx] = {"categorie": "spam", "bron": "spam_cache", "sender": sender}
            continue

        if is_obvious_spam(from_domain, msg.subject or "", body_snippet, url_domains):
            if spam_forbidden:
                downgraded = downgrade_blocked_spam(headers)
                final_results[idx] = {
                    "categorie": downgraded,
                    "bron": "spam_blocked_by_domain_cache",
                    "sender": sender,
                }
            else:
                final_results[idx] = {"categorie": "spam", "bron": "guardrail", "sender": sender}
                if settings.use_spam_sender_cache:
                    hits = spam_cache.increment_spam_hit(sender, msg.subject or "")
                    should_save_spam_cache = True
                    run_logger.event("spam_hits_incremented", f"{sender};hits={hits};bron=guardrail")
            continue

        unknown_items.append(
            (
                idx,
                msg,
                sender,
                spam_forbidden,
                headers,
            )
        )

    if unknown_items:
        unknown_batch = [item[1] for item in unknown_items]
        gpt_results = classifier.batch_classify(unknown_batch)
        if gpt_results is None:
            run_logger.event("batch_fail", "GPT batch kon niet worden geclassificeerd")
            logger.warning("GPT batch kon niet worden geclassificeerd")
            gpt_results = {}

        for local_idx, unknown_data in enumerate(unknown_items):
            orig_idx, _orig_msg, sender, spam_forbidden, headers = unknown_data
            category = gpt_results.get(local_idx, "onbekend")
            bron = "llm"
            if category == "spam":
                if spam_forbidden:
                    category = downgrade_blocked_spam(headers)
                    bron = "spam_blocked_by_domain_cache"
                else:
                    if settings.use_spam_sender_cache:
                        hits = spam_cache.increment_spam_hit(sender, (_orig_msg.subject or ""))
                        should_save_spam_cache = True
                        run_logger.event("spam_hits_incremented", f"{sender};hits={hits};bron=llm")
            final_results[orig_idx] = {"categorie": category, "bron": bron, "sender": sender}

    for idx, msg in enumerate(batch):
        cat_info = final_results.get(idx, {"categorie": "onbekend", "bron": "onbekend", "sender": extract_sender_email(msg.from_ or "")})
        categorie = cat_info["categorie"]
        bron = cat_info["bron"]
        onderwerp = msg.subject or ""
        afzender = cat_info["sender"] or extract_sender_email(msg.from_ or "")

        if categorie not in {"spam", "onbekend", ""}:
            exact_cache.update(afzender, categorie, onderwerp)
            should_save_exact = True

        run_logger.email(
            email_datum=msg.date,
            categorie=categorie,
            afzender=afzender,
            onderwerp=onderwerp,
            bron=bron,
        )
        logger.info("[%s] %s -> %s (%s)", categorie, onderwerp[:60], afzender, bron)
        _move_to_category_folder(box, msg, categorie, settings, logger, run_logger, ensured_folders)

    if should_save_exact:
        exact_cache.save()
    if should_save_spam_cache:
        spam_cache.save()


def main() -> int:
    settings = load_settings()
    logger = setup_app_logger(settings)
    run_logger = RunLogger(settings)
    exact_cache = SenderCacheStore(settings.cache_file, logger=logger, run_logger=run_logger)
    domain_cache = DomainCacheStore(settings.domain_cache_file)
    spam_cache = SpamSenderCacheStore(settings.sender_spam_cache_file, run_logger=run_logger)
    spam_cache.apply_startup_reconciliation(exact_cache, domain_cache)
    classifier = EmailClassifier(settings, logger=logger, run_logger=run_logger)

    logger.info("Verbinden met mailbox")
    logger.info(
        "IMAP move by category=%s prefix=%s",
        settings.imap_move_by_category,
        settings.imap_category_prefix,
    )
    try:
        with MailBox(settings.imap_host).login(settings.imap_user, settings.imap_password) as box:
            for chunk in fetch_in_chunks(
                box=box,
                date_from=settings.date_from,
                date_to=settings.date_to,
                step_days=settings.chunk_days,
                logger=logger,
                run_logger=run_logger,
            ):
                if not chunk:
                    continue
                for start in range(0, len(chunk), settings.batch_size):
                    batch = chunk[start : start + settings.batch_size]
                    process_batch(
                        batch=batch,
                        box=box,
                        classifier=classifier,
                        exact_cache=exact_cache,
                        domain_cache=domain_cache,
                        spam_cache=spam_cache,
                        settings=settings,
                        logger=logger,
                        run_logger=run_logger,
                    )
        return 0
    except Exception as exc:
        run_logger.event("main_exception", str(exc))
        logger.exception("Onverwachte fout in main")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
