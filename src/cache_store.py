from __future__ import annotations

import json
from pathlib import Path

import logging

from logging_setup import RunLogger


class SenderCacheStore:
    def __init__(self, cache_file: Path, logger: logging.Logger, run_logger: RunLogger) -> None:
        self.cache_file = cache_file
        self.logger = logger
        self.run_logger = run_logger
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load_and_upgrade()

    def get_category(self, sender: str) -> str | None:
        item = self._data.get(sender)
        if not item:
            return None
        return item.get("categorie")

    def update(self, sender: str, categorie: str, subject: str) -> None:
        self._data[sender] = {
            "categorie": categorie or "onbekend",
            "subject": subject or "(geen subject)",
        }

    def save(self) -> None:
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def _load_and_upgrade(self) -> dict[str, dict[str, str]]:
        if self.cache_file.is_file():
            with self.cache_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = {}

        upgraded = {}
        changed = False

        for sender, value in raw.items():
            if isinstance(value, str):
                upgraded[sender] = {"categorie": value, "subject": "(onbekend)"}
                changed = True
            elif isinstance(value, dict):
                categorie = value.get("categorie", "onbekend")
                subject = value.get("subject", "(onbekend)")
                upgraded[sender] = {"categorie": categorie, "subject": subject}
                if "categorie" not in value or "subject" not in value:
                    changed = True
            else:
                upgraded[sender] = {"categorie": "onbekend", "subject": "(onbekend)"}
                changed = True

        if changed:
            self.logger.info("Cache automatisch geupgrade naar nieuwe structuur")
            self.run_logger.event("cache_upgrade", "Cache structuur geupgrade")
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(upgraded, f, indent=2, ensure_ascii=False)

        return upgraded
