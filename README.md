# EmailSorteerder

Modulaire e-mailsorteerder met 1 entrypoint: `src/main.py`.

## Structuur

```text
emailsorteerder/
├── src/
│   ├── main.py
│   ├── config.py
│   ├── imap_reader.py
│   ├── classifier.py
│   ├── cache_store.py
│   └── logging_setup.py
├── prompts/
├── config/
│   └── example.env
├── cache/          (ignored)
├── logs/           (ignored)
├── requirements.txt
├── .gitignore
└── README.md
```

## Configuratie

1. Maak een lokale `.env` in de projectroot (niet in Git), gebaseerd op `config/example.env`.
2. Voor Azure App Service kun je dezelfde keys als App Settings zetten; environment variables overrulen `.env`.

Verplicht:
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_PASSWORD`

Voor GPT-classificatie:
- `OPENAI_API_KEY`

## Run

```bash
python src/main.py
```

## Logging en runtime data

- Runtime logs: `logs/`
- Sender cache: `cache/sender_exact.json`
- Beide staan in `.gitignore`.
