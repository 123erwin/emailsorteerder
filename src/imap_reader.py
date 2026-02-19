from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

from imap_tools import AND, MailBox


def mailbox_connection(host: str, user: str, password: str) -> MailBox:
    return MailBox(host).login(user, password)


def fetch_in_chunks(
    box: MailBox,
    date_from: str,
    date_to: str,
    step_days: int,
    logger,
    run_logger,
) -> Iterator[list]:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)

    current = start
    while current < end:
        segment_end = min(current + timedelta(days=step_days), end)
        logger.info("Chunk %s -> %s", current.isoformat(), segment_end.isoformat())

        try:
            mails = list(
                box.fetch(
                    AND(
                        date_gte=current,
                        date_lt=segment_end,
                    ),
                    reverse=True,
                )
            )
        except Exception as exc:
            run_logger.event("imap_fetch", f"IMAP fetch error: {exc}")
            logger.exception("IMAP fetch error")
            mails = []

        logger.info("%s mails in chunk", len(mails))
        yield mails
        current = segment_end
