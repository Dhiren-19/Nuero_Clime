"""
Central configuration for NeuroClime.

Loads environment variables from (in order, later wins):
  1. <repo-root>/.env
  2. <repo-root>/backend/.env

This is the single place that reads os.environ so every other module just
imports `settings`. See .env.example / .env for the full list of keys.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../backend
_REPO_ROOT = _BACKEND_DIR.parent  # .../neuroclime

load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_BACKEND_DIR / ".env", override=True)


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # Run mode
    DEMO_MODE: bool = _bool("DEMO_MODE", True)
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")

    # Supabase
    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")
    SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")
    SUPABASE_JWT_SECRET: str = os.environ.get("SUPABASE_JWT_SECRET", "")

    # Sensor sources
    CPCB_API_BASE_URL: str = os.environ.get("CPCB_API_BASE_URL", "")
    CPCB_API_KEY: str = os.environ.get("CPCB_API_KEY", "")
    IMD_API_BASE_URL: str = os.environ.get("IMD_API_BASE_URL", "")
    IMD_API_KEY: str = os.environ.get("IMD_API_KEY", "")

    # Satellite sources
    MOSDAC_USERNAME: str = os.environ.get("MOSDAC_USERNAME", "")
    MOSDAC_PASSWORD: str = os.environ.get("MOSDAC_PASSWORD", "")
    NASA_EARTHDATA_USERNAME: str = os.environ.get("NASA_EARTHDATA_USERNAME", "")
    NASA_EARTHDATA_TOKEN: str = os.environ.get("NASA_EARTHDATA_TOKEN", "")
    CDS_API_URL: str = os.environ.get("CDS_API_URL", "")
    CDS_API_KEY: str = os.environ.get("CDS_API_KEY", "")
    GEE_SERVICE_ACCOUNT_EMAIL: str = os.environ.get("GEE_SERVICE_ACCOUNT_EMAIL", "")
    GEE_SERVICE_ACCOUNT_KEY_PATH: str = os.environ.get("GEE_SERVICE_ACCOUNT_KEY_PATH", "")
    GEE_PROJECT_ID: str = os.environ.get("GEE_PROJECT_ID", "")

    # Bhashini
    BHASHINI_API_BASE_URL: str = os.environ.get("BHASHINI_API_BASE_URL", "")
    BHASHINI_USER_ID: str = os.environ.get("BHASHINI_USER_ID", "")
    BHASHINI_API_KEY: str = os.environ.get("BHASHINI_API_KEY", "")
    BHASHINI_DEFAULT_LANGUAGES: list = os.environ.get("BHASHINI_DEFAULT_LANGUAGES", "en,hi,mr").split(",")

    # Model / inference
    MODEL_ARTIFACT_DIR: str = os.environ.get("MODEL_ARTIFACT_DIR", "./pipeline/artifacts")
    MODEL_VERSION: str = os.environ.get("MODEL_VERSION", "v0.1.0-rf-baseline")
    INFERENCE_REFRESH_MINUTES: int = int(os.environ.get("INFERENCE_REFRESH_MINUTES", "15"))

    # Backend
    BACKEND_HOST: str = os.environ.get("BACKEND_HOST", "0.0.0.0")
    BACKEND_PORT: int = int(os.environ.get("BACKEND_PORT", "8000"))
    CORS_ALLOWED_ORIGINS: list = [
        o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",") if o.strip()
    ] or ["*"]

    # Local demo-mode data store
    LOCAL_DATA_DIR: Path = _BACKEND_DIR / "app" / "data"


settings = Settings()
