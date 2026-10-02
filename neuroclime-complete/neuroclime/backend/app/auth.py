"""
Auth dependency for FastAPI routes.

Real mode: validates the Supabase JWT passed in the Authorization header
and checks the `role` claim (citizen/authority/admin), per TRD 2.3.5.
Supabase Postgres RLS is the primary guard on data access; this is the
second guard for endpoints (ward ranking, reports, admin) that use the
service-role key internally and therefore bypass RLS.

Demo mode (DEMO_MODE=true, no Supabase project configured): full Supabase
Auth (email/OTP for citizens, invite-based provisioning for authority) needs
a live Supabase project to issue real JWTs, which this handoff intentionally
does not require just to run the app. Instead, a demo request identifies
itself with an `X-Demo-Role: citizen|authority|admin` header (the frontend's
role switcher sets this). This path is automatically disabled the moment
real Supabase credentials are configured, so it can never be used to bypass
auth in a real deployment.
"""
import jwt
from fastapi import Header, HTTPException, Depends
from typing import Optional

from app.config import settings
from app.db import is_demo_mode


def get_current_user(
    authorization: Optional[str] = Header(None),
    x_demo_role: Optional[str] = Header(None),
    x_demo_user_id: Optional[str] = Header(None),
    x_demo_jurisdiction: Optional[str] = Header(None),
):
    if is_demo_mode():
        role = x_demo_role or "citizen"
        jurisdiction = [w.strip() for w in x_demo_jurisdiction.split(",")] if x_demo_jurisdiction else []
        return {
            "role": role,
            "sub": x_demo_user_id or f"demo-{role}",
            "jurisdiction_ward_ids": jurisdiction,
        }

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated"
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}")
    return payload


def require_role(*allowed_roles: str):
    def dependency(user: dict = Depends(get_current_user)):
        role = user.get("role") or user.get("app_metadata", {}).get("role")
        if role not in allowed_roles:
            raise HTTPException(403, f"Requires one of roles: {allowed_roles}")
        return user

    return dependency
