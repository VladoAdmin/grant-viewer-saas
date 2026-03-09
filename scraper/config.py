"""Configuration and environment variables for the scraper."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(Path.home() / ".openclaw" / ".env")  # fallback for shared keys

# Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# OpenAI
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Embedding config
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072
EMBED_BATCH_SIZE = 96

# Metadata / Rerank / Completeness model
METADATA_MODEL = "gpt-4o-mini"

# Chunker config
CHUNK_TARGET_TOKENS = 768
CHUNK_MAX_TOKENS = 1024
CHUNK_MIN_TOKENS = 256

# Scraper config
STORAGE_PATH = os.environ.get("STORAGE_PATH", str(PROJECT_ROOT / "storage"))
MAX_PDF_PAGES = 25
REQUEST_DELAY = 0.5  # seconds between requests (be nice)
REQUEST_TIMEOUT = 30  # seconds
MAX_FILE_SIZE_MB = 50

# API base URLs
ITMS21_API_BASE = "https://api.itms21.sk/public/v1"

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def validate_config():
    """Validate required configuration."""
    errors = []
    if not SUPABASE_URL:
        errors.append("SUPABASE_URL is not set")
    if not SUPABASE_KEY:
        errors.append("SUPABASE_SERVICE_ROLE_KEY is not set")
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY is not set")
    return errors
