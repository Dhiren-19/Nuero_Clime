"""
Local, file-backed stand-in for the Supabase client.

Why this exists: the PRD/TRD specify Supabase (Postgres + PostGIS) as the
system of record, and the real client (`app.db.get_client`) is used whenever
SUPABASE_URL/SUPABASE_SERVICE_KEY are configured. But requiring a live cloud
project just to *look at* NeuroClime defeats the purpose of a self-contained
handoff. When DEMO_MODE=true (the default) or no Supabase credentials are
present, the app instead uses this local JSON-file store, which implements
the same tiny slice of the chainable supabase-py query builder that the
routers and pipeline scripts actually call:

    db.table("predictions").select("*").eq("hex_id", x).order(...).limit(n).execute()
    db.table("scenarios").insert({...}).execute()
    db.table("hex_zones").upsert(rows, on_conflict="hex_id").execute()

This is intentionally NOT a general Postgres/PostGIS emulator — no spatial
indexing, no RLS. Row Level Security is a Postgres-level concept and is
implemented for real in infra/schema.sql; the FastAPI-level role checks in
app/auth.py are what actually gate this local store's admin/authority
endpoints during a demo run.

Swap DEMO_MODE=false with real Supabase keys in .env to switch every router
to the live database with zero code changes (see app/db.py).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


class _Result:
    def __init__(self, data: Any):
        self.data = data


class _Query:
    def __init__(self, store: "LocalTable", op: str = "select", cols: str = "*"):
        self.store = store
        self.op = op
        self.cols = cols
        self.filters: list[tuple[str, str, Any]] = []  # (kind, col, val)
        self._order_col = None
        self._order_desc = False
        self._limit = None
        self._payload = None
        self._on_conflict = None

    # --- filters -----------------------------------------------------
    def eq(self, col: str, val: Any) -> "_Query":
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col: str, vals: list) -> "_Query":
        self.filters.append(("in", col, vals))
        return self

    def gte(self, col: str, val: Any) -> "_Query":
        self.filters.append(("gte", col, val))
        return self

    def lte(self, col: str, val: Any) -> "_Query":
        self.filters.append(("lte", col, val))
        return self

    # --- shaping -------------------------------------------------------
    def order(self, col: str, desc: bool = False) -> "_Query":
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "_Query":
        self._limit = n
        return self

    # --- writes ----------------------------------------------------------
    def insert(self, payload) -> "_Query":
        self.op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None) -> "_Query":
        self.op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def update(self, payload) -> "_Query":
        self.op = "update"
        self._payload = payload
        return self

    def delete(self) -> "_Query":
        self.op = "delete"
        return self

    # --- execution -----------------------------------------------------
    def execute(self) -> _Result:
        with _LOCK:
            rows = self.store._read()
            if self.op == "select":
                rows = self._apply_filters(rows)
                if self._order_col:
                    rows = sorted(
                        rows,
                        key=lambda r: (r.get(self._order_col) is None, r.get(self._order_col)),
                        reverse=self._order_desc,
                    )
                if self._limit is not None:
                    rows = rows[: self._limit]
                if self.cols != "*":
                    wanted = [c.strip() for c in self.cols.split(",")]
                    rows = [{k: r.get(k) for k in wanted} for r in rows]
                return _Result(rows)

            if self.op == "insert":
                payload = self._payload if isinstance(self._payload, list) else [self._payload]
                for row in payload:
                    row.setdefault("id", self.store._next_id())
                    rows.append(row)
                self.store._write(rows)
                return _Result(payload)

            if self.op == "upsert":
                payload = self._payload if isinstance(self._payload, list) else [self._payload]
                key = self._on_conflict or "id"
                index = {r.get(key): i for i, r in enumerate(rows)}
                for row in payload:
                    if row.get(key) in index:
                        rows[index[row.get(key)]] = row
                    else:
                        rows.append(row)
                self.store._write(rows)
                return _Result(payload)

            if self.op == "update":
                target = self._apply_filters(rows)
                ids = {id(r) for r in target}
                for r in rows:
                    if id(r) in ids:
                        r.update(self._payload)
                self.store._write(rows)
                return _Result(target)

            if self.op == "delete":
                target = self._apply_filters(rows)
                ids = {id(r) for r in target}
                remaining = [r for r in rows if id(r) not in ids]
                self.store._write(remaining)
                return _Result(target)

            raise ValueError(f"Unsupported op {self.op}")

    def _apply_filters(self, rows):
        out = rows
        for kind, col, val in self.filters:
            if kind == "eq":
                out = [r for r in out if r.get(col) == val]
            elif kind == "in":
                out = [r for r in out if r.get(col) in val]
            elif kind == "gte":
                out = [r for r in out if r.get(col) is not None and r.get(col) >= val]
            elif kind == "lte":
                out = [r for r in out if r.get(col) is not None and r.get(col) <= val]
        return out


class LocalTable:
    def __init__(self, path: Path):
        self.path = path
        if not self.path.exists():
            self.path.write_text("[]")

    def _read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text() or "[]")
        except json.JSONDecodeError:
            return []

    def _write(self, rows: list[dict]) -> None:
        self.path.write_text(json.dumps(rows, indent=2, default=str))

    def _next_id(self) -> int:
        rows = self._read()
        ints = [r["id"] for r in rows if isinstance(r.get("id"), int)]
        return (max(ints) + 1) if ints else 1

    def select(self, cols: str = "*") -> _Query:
        return _Query(self, op="select", cols=cols)

    def insert(self, payload) -> _Query:
        return _Query(self).insert(payload)

    def upsert(self, payload, on_conflict: str | None = None) -> _Query:
        return _Query(self).upsert(payload, on_conflict=on_conflict)

    def update(self, payload) -> _Query:
        return _Query(self).update(payload)

    def delete(self) -> _Query:
        return _Query(self)._replace_op_delete() if False else _Query(self).delete()


class LocalClient:
    """Drop-in stand-in for supabase.Client covering .table(name)."""

    TABLES = (
        "cities",
        "wards",
        "hex_zones",
        "sensor_readings",
        "satellite_features",
        "predictions",
        "users",
        "alerts",
        "scenarios",
        "reports",
        "pipeline_runs",
        "translations",
    )

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._tables = {name: LocalTable(self.data_dir / f"{name}.json") for name in self.TABLES}

    def table(self, name: str) -> LocalTable:
        if name not in self._tables:
            self._tables[name] = LocalTable(self.data_dir / f"{name}.json")
        return self._tables[name]
