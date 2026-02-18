# ======================================================================
# Email Sorteerder v5.6 – Turbo Edition (Balanced Mode)
#
# DEEL 1/3:
# - Imports
# - Config
# - Pad-structuur
# - Sender-cache + auto-upgrade
# - Logging (console + CSV + GPT payload)
# - HTML → text cleaning
# - URL extractie uit HTML + plaintext
# - Header extractie (relevante headers)
#
# ======================================================================

from imap_tools import MailBox, AND
from dotenv import load_dotenv
from openai import OpenAI

import os
import csv
import json
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

load_dotenv()

# ------------------------------------------------------------
# CONFIG SWITCHES
# ------------------------------------------------------------

LOG_GPT_PAYLOAD = True    # Zet op True voor JSON+prompt logging
LOG_TO_CONSOLE  = True     # Extra console logging
MAX_BODY_CHARS  = 250      # Snippet grootte (cheap, snel)

# ------------------------------------------------------------
# PADEN / DIRECTORIES
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

CACHE_FILE = CACHE_DIR / "sender_exact.json"

DEFAULT_LOG_DIR = Path(r"C:\Temp\LogEmailSorteerder")
LOG_DIR = Path(os.getenv("LOG_DIR", DEFAULT_LOG_DIR))
LOG_DIR.mkdir(parents=True, exist_ok=True)

RUNSTAMP = os.getenv("RUNSTAMP") or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

CSV_FILE = LOG_DIR / f"log_{RUNSTAMP}.csv"
ERR_FILE = LOG_DIR / f"errors_{RUNSTAMP}.csv"
GPT_PAYLOAD_FILE = LOG_DIR / f"gpt_payload_{RUNSTAMP}.txt"

# ------------------------------------------------------------
# SENDER CACHE LADEN + AUTO UPGRADE
# ------------------------------------------------------------

def upgrade_cache_structure(cache):
    """
    Upgradet oude sender_cache van:
        "info@x.com": "reclame"
    naar:
        "info@x.com": { "categorie": "reclame", "subject": "..." }
    """
    upgraded = {}
    changed = False

    for sender, value in cache.items():
        if isinstance(value, str):
            upgraded[sender] = {
                "categorie": value,
                "subject": "(onbekend)"
            }
            changed = True
        elif isinstance(value, dict):
            if "categorie" not in value:
                value["categorie"] = "onbekend"
            if "subject" not in value:
                value["subject"] = "(onbekend)"
            upgraded[sender] = value
        else:
            upgraded[sender] = {
                "categorie": "onbekend",
                "subject": "(onbekend)"
            }
            changed = True

    return upgraded, changed


if CACHE_FILE.is_file():
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        raw_cache = json.load(f)
else:
    raw_cache = {}

SENDER_CACHE, changed = upgrade_cache_structure(raw_cache)

if changed:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(SENDER_CACHE, f, indent=2, ensure_ascii=False)
    print(">>> Cache automatisch geüpgraded naar nieuwe structuur.")


def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(SENDER_CACHE, f, indent=2, ensure_ascii=False)

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------

def _format_datetime_for_csv(value):
    """
    Normaliseert datums naar hetzelfde CSV-formaat als log_datum.
    """
    if isinstance(value, datetime):
        return value.strftime(DATETIME_FMT)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime(DATETIME_FMT)
    return value or ""


def event(context, message):
    """Logt errors en events."""
    file_exists = ERR_FILE.is_file()
    with open(ERR_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=';')
        if not file_exists:
            w.writerow(["tijd", "context", "event"])

        w.writerow([
            datetime.now().strftime(DATETIME_FMT),
            context,
            message
        ])

    if LOG_TO_CONSOLE:
        print(f"[{context}] {message}")


def log_email(email_datum, categorie, afzender, onderwerp, bron):
    file_exists = CSV_FILE.is_file()
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=';')
        if not file_exists:
            w.writerow([
                "log_datum", "email_datum", "categorie", "afzender", "onderwerp", "bron"
            ])

        email_datum_str = _format_datetime_for_csv(email_datum)

        w.writerow([
            datetime.now().strftime(DATETIME_FMT),
            email_datum_str,
            categorie,
            afzender,
            onderwerp,
            bron
        ])


def log_gpt_payload(prompt_json, final_user_prompt):
    if not LOG_GPT_PAYLOAD:
        return

    with open(GPT_PAYLOAD_FILE, "a", encoding="utf-8") as f:
        f.write("\n===============================================\n")
        f.write("GPT PAYLOAD\n")
        f.write("===============================================\n\n")

        f.write("JSON:\n")
        f.write(prompt_json)
        f.write("\n\nPROMPT:\n")
        f.write(final_user_prompt)
        f.write("\n\n")

# ----------- -------------------------------------------------
# HTML → TEXT
# ------------------------------------------------------------

def extract_text(msg):
    """Haalt plain text uit HTML of plaintext, met opschoning."""
    body = msg.text or msg.html or ""
    is_html = any(tag in body.lower() for tag in ["<html", "<body", "<div", "<table", "<span"])

    if is_html:
        try:
            soup = BeautifulSoup(body, "html.parser")
            for s in soup(["script", "style"]):
                s.extract()
            text = soup.get_text(" ")
        except Exception as e:
            event("extract_text", f"HTML parse error: {e}")
            text = body
    else:
        text = body

    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_BODY_CHARS]

# ------------------------------------------------------------
# URL EXTRACTIE
# ------------------------------------------------------------

URL_REGEX = re.compile(
    r"(https?://[^\s\"'>)]+)",
    re.IGNORECASE
)

def extract_urls(body, html):
    """Haalt URLs uit zowel text als HTML."""
    urls = set()

    # URLs in plaintext
    for m in URL_REGEX.findall(body or ""):
        urls.add(m.strip())

    # URLs in HTML href
    if html:
        for match in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            urls.add(match.strip())

    return list(urls)

# ------------------------------------------------------------
# RELEVANTE HEADERS EXTRACTIE
# ------------------------------------------------------------

def extract_relevant_headers(msg):
    """
    Houdt het licht, snel en toch krachtig.
    """
    h = msg.headers

    def norm(v):
        if not v:
            return ""
        return str(v).strip().lower()

    return {
        "spf": norm(h.get("Authentication-Results")),
        "dkim": norm(h.get("DKIM-Signature")),
        "dmarc": norm(h.get("DMARC-Filter")),
        "return_path": norm(h.get("Return-Path")),
        "message_id": norm(h.get("Message-ID")),
        "list_id": norm(h.get("List-ID")),
        "list_unsubscribe": norm(h.get("List-Unsubscribe")),
        "precedence": norm(h.get("Precedence")),
        "x_mailer": norm(h.get("X-Mailer")),
        "x_spam_flag": norm(h.get("X-Spam-Flag")),
        "x_spam_status": norm(h.get("X-Spam-Status"))
    }


# ======================================================================
# Email Sorteerder v5.6 – Turbo Edition (Balanced Mode)
#
# DEEL 2/3:
# - Laden system_prompt.txt + classify_prompt.txt
# - GPT-payload builder
# - batch_classify()
# - parsing van index=<n>; categorie=<x>
# ======================================================================

# ------------------------------------------------------------
# PROMPTS INLADEN
# ------------------------------------------------------------

with open(BASE_DIR / "prompts/system_prompt.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

with open(BASE_DIR / "prompts/classify_prompt.txt", "r", encoding="utf-8") as f:
    CLASSIFY_PROMPT = f.read()

# ------------------------------------------------------------
# OPENAI CLIENT
# ------------------------------------------------------------

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GPTMODEL = os.getenv("GPTMODEL", "gpt-4.1-mini")

try:
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "30"))
except ValueError:
    BATCH_SIZE = 30

client = OpenAI(api_key=OPENAI_API_KEY)

DATE_FROM = os.getenv("DATE_FROM", "2025-01-01")
DATE_TO   = os.getenv("DATE_TO", "2025-01-08")

# ------------------------------------------------------------
# BUILD GPT PAYLOAD
# ------------------------------------------------------------

def build_gpt_payload(batch):
    """
    Bouwt de JSON payload voor GPT, met:
    - subject
    - from / to / cc
    - body extract
    - urls
    - relevante headers
    """
    payload = []

    for idx, msg in enumerate(batch):

        body_snippet = extract_text(msg)
        html_raw = msg.html or ""
        urls = extract_urls(body_snippet, html_raw)
        headers = extract_relevant_headers(msg)

        payload.append({
            "index": idx,
            "subject": msg.subject or "",
            "from": msg.from_,
            "to": msg.to,
            "cc": msg.cc,
            "date": msg.date.isoformat() if msg.date else "",
            "body_snippet": body_snippet,
            "urls": urls,
            "headers": headers
        })

    return payload

# ------------------------------------------------------------
# GPT CLASSIFIER
# ------------------------------------------------------------

def batch_classify(batch):
    """
    Stuurt batch mails naar GPT en haalt classificaties op.
    """
    try:
        email_list = build_gpt_payload(batch)

        json_data = json.dumps(email_list, ensure_ascii=False)
        user_prompt = CLASSIFY_PROMPT.format(emails_json=json_data)

        # Optional logging
        log_gpt_payload(json_data, user_prompt)

        event("gpt_call", f"Batch size={len(batch)}")

        r = client.chat.completions.create(
            model=GPTMODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt}
            ]
        )

        raw = r.choices[0].message.content.strip()
        lines = raw.split("\n")

        results = {}

        for line in lines:
            if not line.lower().startswith("index="):
                continue

            try:
                part1, part2 = line.split(";")
                idx = int(part1.split("=")[1])
                cat = part2.split("=")[1].strip().lower()
                results[idx] = cat
            except Exception as e:
                event("parse", f"Parse error: {line} | {e}")

        event("gpt_ok", f"Classified {len(results)}/{len(batch)} mails")
        return results

    except Exception as e:
        event("gpt_exception", str(e))
        return None
# ======================================================================
# Email Sorteerder v5.6 – Turbo Edition (Balanced Mode)
#
# DEEL 3/3:
# - IMAP chunk fetching
# - Batch slicing
# - Cache integratie
# - Classification + logging
# - main()
# ======================================================================

# ------------------------------------------------------------
# IMAP FETCH IN CHUNKS (voorkomt IMAP overload)
# ------------------------------------------------------------

def fetch_in_chunks(box, date_from, date_to, step_days=3):
    """
    Haalt kleine stukken mails op (per 1-7 dagen),
    zodat IMAP nooit in grote eenheden hoeft te werken.
    """
    start = date.fromisoformat(date_from)
    end   = date.fromisoformat(date_to)

    current = start
    while current < end:
        segment_end = min(current + timedelta(days=step_days), end)

        if LOG_TO_CONSOLE:
            print(f"\n=== Chunk {current} → {segment_end} ===")

        try:
            mails = list(
                box.fetch(
                    AND(
                        date_gte=current,
                        date_lt=segment_end
                    ),
                    reverse=True
                )
            )
        except Exception as e:
            event("imap_fetch", f"IMAP fetch error: {e}")
            mails = []

        print(f"  {len(mails)} mails in deze chunk\n")

        yield mails

        current = segment_end

# ------------------------------------------------------------
# MAIN PROCESS LOOP
# ------------------------------------------------------------

def main():
    print("Verbinden met mailbox...")

    try:
        with MailBox(IMAP_HOST).login(IMAP_USER, IMAP_PASSWORD) as box:

            for chunk in fetch_in_chunks(box, DATE_FROM, DATE_TO, step_days=3):

                if not chunk:
                    continue

                # Deel grote chunk in kleinere GPT-batches
                for batch_start in range(0, len(chunk), BATCH_SIZE):

                    batch = chunk[batch_start : batch_start + BATCH_SIZE]

                    payload_for_gpt = []
                    instant_results = {}

                    # ----------------------------
                    # 1. Cache check
                    # ----------------------------
                    for idx, msg in enumerate(batch):
                        sender = msg.from_

                        # Exact match in sender cache?
                        if sender in SENDER_CACHE:
                            instant_results[idx] = {
                                "categorie": SENDER_CACHE[sender]["categorie"],
                                "bron": "cache"
                            }
                        else:
                            payload_for_gpt.append(msg)

                    # ----------------------------
                    # 2. GPT classificatie voor onbekenden
                    # ----------------------------
                    gpt_results = {}
                    gpt_map = {}

                    if payload_for_gpt:
                        gpt_results = batch_classify(payload_for_gpt)

                        if not gpt_results:
                            event("batch_fail", "GPT batch kon niet worden geclassificeerd")
                            continue

                        # Combineer GPT result → correct verschuiven naar juiste index
                        gpt_map = {}
                        gpt_counter = 0

                        for idx, msg in enumerate(batch):
                            if msg not in payload_for_gpt:
                                continue
                            gpt_map[idx] = {
                                "categorie": gpt_results.get(gpt_counter, "onbekend"),
                                "bron": GPTMODEL
                            }
                            gpt_counter += 1

                        # Update cache
                        for idx, msg in enumerate(batch):
                            if idx in gpt_map:
                                sender = msg.from_
                                SENDER_CACHE[sender] = {
                                    "categorie": gpt_map[idx]["categorie"],
                                    "subject": msg.subject or "(geen subject)"
                                }

                        save_cache()

                    # ----------------------------
                    # 3. Combine results
                    # ----------------------------
                    final_results = {}

                    # Eerst GPT-resultaten
                    for idx, cat in gpt_map.items():
                        final_results[idx] = cat

                    # Daarna instant cache
                    for idx, cat in instant_results.items():
                        final_results[idx] = cat

                    # ----------------------------
                    # 4. Logging
                    # ----------------------------
                    for idx, msg in enumerate(batch):
                        cat_info = final_results.get(idx)
                        categorie = cat_info["categorie"] if cat_info else "onbekend"
                        bron = cat_info["bron"] if cat_info else "onbekend"

                        log_email(
                            email_datum=msg.date,
                            categorie=categorie,
                            afzender=msg.from_,
                            onderwerp=msg.subject or "",
                            bron=bron
                        )

                        print(f"[{categorie:<22}] {msg.subject[:60]}  ->  {msg.from_} ({bron})")

    except Exception as e:
        event("main_exception", str(e))


# ------------------------------------------------------------
# ENTRYPOINT
# ------------------------------------------------------------

if __name__ == "__main__":
    main()
