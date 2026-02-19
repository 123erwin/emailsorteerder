from __future__ import annotations

from imap_tools import MailBox

from cache_store import SenderCacheStore
from classifier import EmailClassifier
from config import load_settings
from imap_reader import fetch_in_chunks
from logging_setup import RunLogger, setup_app_logger


def process_batch(batch, classifier, cache, settings, logger, run_logger) -> None:
    unknown_items = []
    final_results = {}

    for idx, msg in enumerate(batch):
        sender = msg.from_ or ""
        cached_category = cache.get_category(sender)
        if cached_category:
            final_results[idx] = {"categorie": cached_category, "bron": "cache"}
        else:
            unknown_items.append((idx, msg))

    if unknown_items:
        unknown_batch = [item[1] for item in unknown_items]
        gpt_results = classifier.batch_classify(unknown_batch)
        if gpt_results is None:
            run_logger.event("batch_fail", "GPT batch kon niet worden geclassificeerd")
            logger.warning("GPT batch kon niet worden geclassificeerd")
            gpt_results = {}

        for local_idx, category in gpt_results.items():
            if local_idx >= len(unknown_items):
                continue
            orig_idx, orig_msg = unknown_items[local_idx]
            final_results[orig_idx] = {"categorie": category, "bron": settings.gpt_model}
            cache.update(orig_msg.from_ or "", category, orig_msg.subject or "(geen subject)")

        if gpt_results:
            cache.save()

    for idx, msg in enumerate(batch):
        cat_info = final_results.get(idx, {"categorie": "onbekend", "bron": "onbekend"})
        categorie = cat_info["categorie"]
        bron = cat_info["bron"]
        onderwerp = msg.subject or ""
        afzender = msg.from_ or ""

        run_logger.email(
            email_datum=msg.date,
            categorie=categorie,
            afzender=afzender,
            onderwerp=onderwerp,
            bron=bron,
        )
        logger.info("[%s] %s -> %s (%s)", categorie, onderwerp[:60], afzender, bron)


def main() -> int:
    settings = load_settings()
    logger = setup_app_logger(settings)
    run_logger = RunLogger(settings)
    cache = SenderCacheStore(settings.cache_file, logger=logger, run_logger=run_logger)
    classifier = EmailClassifier(settings, logger=logger, run_logger=run_logger)

    logger.info("Verbinden met mailbox")
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
                        classifier=classifier,
                        cache=cache,
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
