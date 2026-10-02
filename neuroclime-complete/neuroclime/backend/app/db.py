"""
Supabase client wiring.

Real endpoints (SUPABASE_URL + SUPABASE_SERVICE_KEY set, DEMO_MODE=false)
use the actual Supabase Postgres/PostGIS project with RLS applied as
appropriate. With no credentials configured, or DEMO_MODE=true (the
default — see .env), this transparently falls back to a local JSON-backed
store (app.local_db.LocalClient) implementing the same `.table(...).select()
.eq()...execute()` interface, so the whole app runs without a live cloud
project. Every router imports `get_client()` and never needs to know which
backend it got.
"""
from functools import lru_cache

from app.config import settings


@lru_cache
def get_client():
    use_local = settings.DEMO_MODE or not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)
    if use_local:
        from app.local_db import LocalClient

        return LocalClient(settings.LOCAL_DATA_DIR)

    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def is_demo_mode() -> bool:
    use_local = settings.DEMO_MODE or not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)
    return use_local
