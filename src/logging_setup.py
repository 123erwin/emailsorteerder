from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import Settings


DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


class RunLogger:
    def __init__(self, settings: Settings) -> None:
        self.log_dir = settings.log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.csv_file = self.log_dir / f"log_{settings.runstamp}.csv"
        self.err_file = self.log_dir / f"errors_{settings.runstamp}.csv"
        self.gpt_payload_file = self.log_dir / f"gpt_payload_{settings.runstamp}.txt"
        self.log_gpt_payload_enabled = settings.log_gpt_payload

    def event(self, context: str, message: str) -> None:
        file_exists = self.err_file.is_file()
        with self.err_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            if not file_exists:
                writer.writerow(["tijd", "context", "event"])
            writer.writerow([datetime.now().strftime(DATETIME_FMT), context, message])

    def email(self, email_datum: Any, categorie: str, afzender: str, onderwerp: str, bron: str) -> None:
        file_exists = self.csv_file.is_file()
        with self.csv_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            if not file_exists:
                writer.writerow(["log_datum", "email_datum", "categorie", "afzender", "onderwerp", "bron"])
            writer.writerow(
                [
                    datetime.now().strftime(DATETIME_FMT),
                    self._format_datetime(email_datum),
                    categorie,
                    afzender,
                    onderwerp,
                    bron,
                ]
            )

    def gpt_payload(self, prompt_json: str, final_user_prompt: str) -> None:
        if not self.log_gpt_payload_enabled:
            return
        with self.gpt_payload_file.open("a", encoding="utf-8") as f:
            f.write("\n===============================================\n")
            f.write("GPT PAYLOAD\n")
            f.write("===============================================\n\n")
            f.write("JSON:\n")
            f.write(prompt_json)
            f.write("\n\nPROMPT:\n")
            f.write(final_user_prompt)
            f.write("\n\n")

    @staticmethod
    def _format_datetime(value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime(DATETIME_FMT)
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time()).strftime(DATETIME_FMT)
        return str(value or "")


def setup_app_logger(settings: Settings) -> logging.Logger:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("emailsorteerder")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(settings.log_dir / f"app_{settings.runstamp}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if settings.log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
