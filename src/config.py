import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class FirebirdConfig:
    host: str = os.getenv("FIREBIRD_HOST", "localhost")
    port: int = int(os.getenv("FIREBIRD_PORT", "3050"))
    database: str = os.getenv("FIREBIRD_DATABASE", "")
    user: str = os.getenv("FIREBIRD_USER", "SYSDBA")
    password: str = os.getenv("FIREBIRD_PASSWORD", "masterkey")
    client_library: str = os.getenv("FIREBIRD_CLIENT_LIBRARY", "lib/fbclient64.dll")


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


NCM_DB_PATH = BASE_DIR / os.getenv("NCM_DB_PATH", "data/ncm.db")

firebird_config = FirebirdConfig()
ollama_config = OllamaConfig()
