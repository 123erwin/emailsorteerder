from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    project_root: Path
    prompts_dir: Path
    log_dir: Path
    cache_file: Path
    system_prompt_file: Path
    classify_prompt_file: Path
    runstamp: str

    imap_host: str
    imap_user: str
    imap_password: str
    openai_api_key: str

    gpt_model: str
    date_from: str
    date_to: str
    batch_size: int
    chunk_days: int
    max_body_chars: int
    log_gpt_payload: bool
    log_to_console: bool


def load_settings() -> Settings:
    log_dir = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))
    cache_dir = Path(os.getenv("CACHE_DIR", str(PROJECT_ROOT / "cache")))
    prompts_dir = Path(os.getenv("PROMPTS_DIR", str(PROJECT_ROOT / "prompts")))

    cache_file = Path(os.getenv("CACHE_FILE", str(cache_dir / "sender_exact.json")))
    system_prompt_file = Path(os.getenv("SYSTEM_PROMPT_FILE", str(prompts_dir / "system_prompt.txt")))
    classify_prompt_file = Path(os.getenv("CLASSIFY_PROMPT_FILE", str(prompts_dir / "classify_prompt.txt")))

    runstamp = os.getenv("RUNSTAMP") or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    settings = Settings(
        project_root=PROJECT_ROOT,
        prompts_dir=prompts_dir,
        log_dir=log_dir,
        cache_file=cache_file,
        system_prompt_file=system_prompt_file,
        classify_prompt_file=classify_prompt_file,
        runstamp=runstamp,
        imap_host=os.getenv("IMAP_HOST", ""),
        imap_user=os.getenv("IMAP_USER", ""),
        imap_password=os.getenv("IMAP_PASSWORD", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        gpt_model=os.getenv("GPTMODEL", "gpt-4.1-mini"),
        date_from=os.getenv("DATE_FROM", "2025-01-01"),
        date_to=os.getenv("DATE_TO", "2025-01-08"),
        batch_size=max(1, _env_int("BATCH_SIZE", 30)),
        chunk_days=max(1, _env_int("CHUNK_DAYS", 3)),
        max_body_chars=max(50, _env_int("MAX_BODY_CHARS", 250)),
        log_gpt_payload=_env_bool("LOG_GPT_PAYLOAD", True),
        log_to_console=_env_bool("LOG_TO_CONSOLE", True),
    )
    _validate_required(settings)
    return settings


def _validate_required(settings: Settings) -> None:
    missing = []
    if not settings.imap_host:
        missing.append("IMAP_HOST")
    if not settings.imap_user:
        missing.append("IMAP_USER")
    if not settings.imap_password:
        missing.append("IMAP_PASSWORD")
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Ontbrekende verplichte configuratie: {names}")
