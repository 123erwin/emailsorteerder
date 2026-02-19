from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from openai import OpenAI

from config import Settings
from logging_setup import RunLogger


URL_REGEX = re.compile(r"(https?://[^\s\"'>)]+)", re.IGNORECASE)


class EmailClassifier:
    def __init__(self, settings: Settings, logger, run_logger: RunLogger) -> None:
        self.settings = settings
        self.logger = logger
        self.run_logger = run_logger
        self.system_prompt = _read_prompt(settings.system_prompt_file)
        self.classify_prompt = _read_prompt(settings.classify_prompt_file)
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def batch_classify(self, batch: list) -> dict[int, str] | None:
        if not batch:
            return {}
        if self.client is None:
            self.run_logger.event("gpt_exception", "OPENAI_API_KEY ontbreekt")
            self.logger.error("OPENAI_API_KEY ontbreekt; GPT classificatie overgeslagen")
            return None

        try:
            email_list = self._build_payload(batch)
            json_data = json.dumps(email_list, ensure_ascii=False)
            user_prompt = self.classify_prompt.format(emails_json=json_data)
            self.run_logger.gpt_payload(json_data, user_prompt)
            self.run_logger.event("gpt_call", f"Batch size={len(batch)}")

            response = self.client.chat.completions.create(
                model=self.settings.gpt_model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            raw = (response.choices[0].message.content or "").strip()
            results = self._parse_results(raw)
            self.run_logger.event("gpt_ok", f"Classified {len(results)}/{len(batch)} mails")
            return results
        except Exception as exc:
            self.run_logger.event("gpt_exception", str(exc))
            self.logger.exception("GPT classificatie fout")
            return None

    def _build_payload(self, batch: list) -> list[dict]:
        payload = []
        for idx, msg in enumerate(batch):
            body_snippet = _extract_text(msg, self.settings.max_body_chars)
            html_raw = msg.html or ""
            payload.append(
                {
                    "index": idx,
                    "subject": msg.subject or "",
                    "from": msg.from_,
                    "to": msg.to,
                    "cc": msg.cc,
                    "date": msg.date.isoformat() if msg.date else "",
                    "body_snippet": body_snippet,
                    "urls": _extract_urls(body_snippet, html_raw),
                    "headers": _extract_relevant_headers(msg),
                }
            )
        return payload

    @staticmethod
    def _parse_results(raw: str) -> dict[int, str]:
        results: dict[int, str] = {}
        for line in raw.splitlines():
            if not line.lower().startswith("index="):
                continue
            try:
                part1, part2 = line.split(";")
                idx = int(part1.split("=")[1].strip())
                cat = part2.split("=")[1].strip().lower()
                results[idx] = cat
            except Exception:
                continue
        return results


def _read_prompt(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def _extract_text(msg, max_chars: int) -> str:
    body = msg.text or msg.html or ""
    is_html = any(tag in body.lower() for tag in ("<html", "<body", "<div", "<table", "<span"))

    if is_html:
        try:
            soup = BeautifulSoup(body, "html.parser")
            for node in soup(("script", "style")):
                node.extract()
            text = soup.get_text(" ")
        except Exception:
            text = body
    else:
        text = body

    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_urls(body: str, html: str) -> list[str]:
    urls = set()
    for match in URL_REGEX.findall(body or ""):
        urls.add(match.strip())
    if html:
        for match in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            urls.add(match.strip())
    return list(urls)


def _extract_relevant_headers(msg) -> dict[str, str]:
    headers = msg.headers

    def norm(value) -> str:
        if not value:
            return ""
        return str(value).strip().lower()

    return {
        "spf": norm(headers.get("Authentication-Results")),
        "dkim": norm(headers.get("DKIM-Signature")),
        "dmarc": norm(headers.get("DMARC-Filter")),
        "return_path": norm(headers.get("Return-Path")),
        "message_id": norm(headers.get("Message-ID")),
        "list_id": norm(headers.get("List-ID")),
        "list_unsubscribe": norm(headers.get("List-Unsubscribe")),
        "precedence": norm(headers.get("Precedence")),
        "x_mailer": norm(headers.get("X-Mailer")),
        "x_spam_flag": norm(headers.get("X-Spam-Flag")),
        "x_spam_status": norm(headers.get("X-Spam-Status")),
    }
