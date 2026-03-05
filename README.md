# EmailSorteerder

Sorteert e-mails uit een IMAP mailbox met een combinatie van regels, cache en (optioneel) GPT.

## Wat doet dit project?
- Leest e-mails uit een datumrange via IMAP.
- Probeert per e-mail een categorie te bepalen.
- Gebruikt eerst snelle lokale regels/caches, en pas daarna GPT.
- Schrijft resultaten naar logbestanden.
- Kan e-mails optioneel direct verplaatsen naar IMAP mappen per categorie.

## Snelle start
1. Installeer dependencies:
```bash
pip install -r requirements.txt
```
2. Maak `.env` in de projectroot op basis van `config/example.env`.
3. Vul minimaal deze 3 waarden in:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`
4. Start:
```bash
python src/main.py
```

## Belangrijkste settings

### Verplicht
- `IMAP_HOST`: IMAP server, bv. `imap.provider.com`
- `IMAP_USER`: je mailbox-gebruiker
- `IMAP_PASSWORD`: je wachtwoord of app-password

### Voor GPT-classificatie
- `OPENAI_API_KEY`: zonder deze key wordt GPT overgeslagen
- `GPTMODEL`: standaard `gpt-4.1-mini`

### Runtime gedrag
- `DATE_FROM`: startdatum (inclusief), formaat `YYYY-MM-DD`
- `DATE_TO`: einddatum (exclusief), formaat `YYYY-MM-DD`
- `BATCH_SIZE`: aantal mails per GPT-batch (standaard `30`)
- `CHUNK_DAYS`: aantal dagen per IMAP-fetch-chunk (standaard `3`)
- `MAX_BODY_CHARS`: max lengte body snippet voor classificatie (standaard `250`)

### Logging
- `LOG_TO_CONSOLE`: `true/false`, ook naar terminal loggen
- `LOG_GPT_PAYLOAD`: `true/false`, prompt/payload opslaan in logfile

### Caches
- `USE_SPAM_SENDER_CACHE`: spam-sender cache aan/uit
- `SPAM_HITS_THRESHOLD`: vanaf hoeveel spam-hits een afzender direct spam wordt
- `CACHE_FILE`: exact sender->categorie cache
- `DOMAIN_CACHE_FILE`: domeinbeleid (force categorie / spam blokkeren)
- `SENDER_SPAM_CACHE_FILE`: spam-hits per afzender

### IMAP verplaatsen (optioneel)
- `IMAP_MOVE_BY_CATEGORY`: `true/false` om mails te verplaatsen
- `IMAP_CATEGORY_PREFIX`: map-prefix, standaard `AI/`
  Voorbeeld: categorie `facturen` wordt map `AI/facturen`.

## Gedrag (simpel uitgelegd)
Per e-mail gebeurt dit in volgorde:
1. Check `DOMAIN_CACHE_FILE`.
   Als domein geforceerd is naar een categorie, dan is dat direct de uitkomst.
2. Check `CACHE_FILE` op exact afzender.
   Als bekend, dan wordt die categorie gebruikt.
3. Check spam sender cache (`SENDER_SPAM_CACHE_FILE`).
   Bij genoeg hits -> direct `spam` (tenzij domein spam niet mag).
4. Draai guardrails (`is_obvious_spam`) op onderwerp/body/url.
   Duidelijke spam -> `spam` (tenzij domein spam niet mag).
5. Alleen onbekende rest gaat naar GPT.
6. Resultaten worden gelogd; non-spam categorieen gaan terug de exact cache in.

Als een domein `spam` verbiedt, wordt spam afgezwakt naar:
- `updates` voor mailinglist-achtige signalen
- anders `promotions`

## Bestanden en output
- Run log (app): `logs/app_<runstamp>.log`
- Classificatie CSV: `logs/log_<runstamp>.csv`
- Events/errors CSV: `logs/errors_<runstamp>.csv`
- GPT payload (optioneel): `logs/gpt_payload_<runstamp>.txt`

Cachebestanden (standaard):
- `cache/sender_exact.json`
- `cache/domain_cache.json`
- `cache/sender_spam_cache.json`

## Handige tips
- `DATE_TO` is exclusief. Voor 1 dag verwerken: zet `DATE_TO` op de volgende dag.
- Zonder `OPENAI_API_KEY` werkt het script nog steeds, maar alleen met regels en caches.
- Zet `IMAP_MOVE_BY_CATEGORY=false` als je eerst alleen wilt classificeren zonder mailbox-wijzigingen.
