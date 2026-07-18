"""
Minimal .env loader. Not using python-dotenv on purpose -- keeps
requirements.txt to four packages, and this is five lines of real work.
Called once at CLI startup (main.py).
"""

import os
from pathlib import Path


def load_env(path: str | Path | None = None) -> None:
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value
