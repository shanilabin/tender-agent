import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Local default: SQLite file. Production: the Supabase Postgres connection string
# (postgresql+psycopg://...).
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'local.db'}")

# Protects every write endpoint (toggles, decisions, run). Must be long and random.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Default recipient for the daily email; can be changed from the admin UI.
DEFAULT_RECIPIENT = os.getenv("DEFAULT_RECIPIENT", "")

# Sender address for the email (with Gmail SMTP it must be the Gmail account n8n logs in with).
EMAIL_FROM = os.getenv("EMAIL_FROM", DEFAULT_RECIPIENT)

# Public address of the admin UI, used for links inside the email.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

USER_AGENT = "tender-agents/0.1 (daily tender check for a catering business; contact via site owner)"

PROFILE_PATH = ROOT / "config" / "profile.json"
