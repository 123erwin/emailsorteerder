#basis script voor het ophalen van e-mails van een IMAP-server met datumfiltering

from imap_tools import MailBox, AND
from dotenv import load_dotenv
import os
from datetime import date

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

MAX_EMAILS = 10


DATE_FROM = "2025-01-01"
DATE_TO   = "2025-02-01"


def main():
    print("Verbinden met mailbox...")

    with MailBox(IMAP_HOST).login(IMAP_USER, IMAP_PASSWORD) as mailbox:
        emails = mailbox.fetch(
    AND(
        date_gte=date.fromisoformat(DATE_FROM),
        date_lt=date.fromisoformat(DATE_TO)
    ),
    reverse=True
)
        
        count = 0
        for msg in emails:

            # Hard limit toepassen
            if count >= MAX_EMAILS:
                break

            print("-----")
            print("Datum:", msg.date)
            print("Onderwerp:", msg.subject)
            print("from", msg.from_)
            print("to", msg.to)

            body = msg.text or msg.html or ""
            body = body.strip().replace("\n", " ")
            short_body = body[:400]
            print("body:", short_body)

            count += 1


        print(f"Klaar. {count} berichten opgehaald.")


if __name__ == "__main__":
    main()
