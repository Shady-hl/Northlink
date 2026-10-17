"""Cached MET Norway MetAlerts 2.0 connector (GeoJSON).

- Fetches only when called explicitly (UI Refresh button); never at import/startup.
- Bounded timeout; every failure is recorded and returned, never raised into the UI.
- Saves the original response bytes unchanged, plus retrieval time and headers.
- Honours the server's Expires header: a refresh before then reuses the cache.
- Sends If-Modified-Since; a 304 records a successful check without new content.
- Keeps real alerts with their own geometry. It does NOT map alerts onto the
  synthetic corridors C1-C3 (no verified mapping exists).

Docs: https://api.met.no/weatherapi/metalerts/2.0/documentation
Terms: https://docs.api.met.no/doc/TermsOfService.html (identifying User-Agent required;
data licensed by MET Norway, attribution required).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

import requests

BASE = "https://api.met.no/weatherapi/metalerts/2.0"
ENDPOINTS = {"current": "current.json", "example": "example.json", "test": "test.json"}
# Post-2024 county numbers for Northern Norway.
COUNTIES = {"18": "Nordland", "55": "Troms", "56": "Finnmark"}
TIMEOUT_S = (5, 15)
UA_VAR = "NORTHLINK_MET_USER_AGENT"
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "met_cache"
ORIGIN = "met-metalerts"

SCHEMA = """
CREATE TABLE IF NOT EXISTS met_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL, attempted_at TEXT NOT NULL,
    successful INTEGER NOT NULL, http_status INTEGER,
    error TEXT, raw_path TEXT, sha256 TEXT,
    last_modified TEXT, expires TEXT, not_modified INTEGER NOT NULL DEFAULT 0);
"""


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_date(v: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(v) if v else None
    except (TypeError, ValueError):
        return None


def user_agent(env_file: Path = ENV_FILE) -> str | None:
    """MET terms require an identifying User-Agent. Read it from the process
    environment, else from the project .env (local file read, no network).
    Returns None when not configured; refresh() then refuses to send."""
    v = os.environ.get(UA_VAR)
    if not v and env_file.exists():
        from dotenv import dotenv_values
        v = dotenv_values(env_file).get(UA_VAR)
    v = (v or "").strip()
    return v or None


def build_url(endpoint: str = "current", county: str | None = "55", lang: str = "en") -> str:
    q = [f"lang={lang}"]
    if endpoint == "current" and county:
        q += ["geographicDomain=land", f"county={county}"]
    return f"{BASE}/{ENDPOINTS[endpoint]}?{'&'.join(q)}"


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


@dataclass
class FetchResult:
    ok: bool
    message: str
    from_cache: bool = False


def last_success(conn, url: str):
    ensure_schema(conn)
    return conn.execute("SELECT * FROM met_fetches WHERE url=? AND successful=1 ORDER BY id DESC LIMIT 1",
                        (url,)).fetchone()


def last_with_body(conn, url: str):
    ensure_schema(conn)
    return conn.execute("SELECT * FROM met_fetches WHERE url=? AND successful=1 AND raw_path IS NOT NULL "
                        "ORDER BY id DESC LIMIT 1", (url,)).fetchone()


def last_attempt(conn, url: str):
    ensure_schema(conn)
    return conn.execute("SELECT * FROM met_fetches WHERE url=? ORDER BY id DESC LIMIT 1", (url,)).fetchone()


def _record(conn, **kw) -> None:
    cols = ", ".join(kw)
    conn.execute(f"INSERT INTO met_fetches ({cols}) VALUES ({', '.join('?' * len(kw))})", tuple(kw.values()))


def refresh(conn, url: str, *, session=None, now: datetime | None = None,
            cache_dir: Path = CACHE_DIR, force: bool = False) -> FetchResult:
    """Explicit fetch only. Requires a configured identifying User-Agent."""
    ensure_schema(conn)
    now = now or datetime.now(timezone.utc)
    prev = last_with_body(conn, url)
    if prev and not force and prev["expires"]:
        exp = datetime.fromisoformat(prev["expires"].replace("Z", "+00:00"))
        if now < exp:
            return FetchResult(True, f"Cached response is valid until {prev['expires']} (server Expires); not re-fetched.", True)
    ua = user_agent()
    if ua is None:
        return FetchResult(False, f"Not sent: set {UA_VAR} in .env (app name and team contact, "
                                  "required by MET's terms). Saved data is still shown.")
    headers = {"User-Agent": ua}
    if prev and prev["last_modified"]:
        headers["If-Modified-Since"] = format_datetime(
            datetime.fromisoformat(prev["last_modified"].replace("Z", "+00:00")), usegmt=True)
    s = session or requests
    try:
        r = s.get(url, headers=headers, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        _record(conn, url=url, attempted_at=_iso(now), successful=0, error=f"{type(exc).__name__}: {exc}"[:500])
        return FetchResult(False, f"Fetch failed ({type(exc).__name__}); last successful retrieval kept.")
    lm, ex = _http_date(r.headers.get("Last-Modified")), _http_date(r.headers.get("Expires"))
    common = dict(url=url, attempted_at=_iso(now), http_status=r.status_code,
                  last_modified=_iso(lm) if lm else None, expires=_iso(ex) if ex else None)
    if r.status_code == 304 and prev:
        _record(conn, successful=1, not_modified=1, raw_path=prev["raw_path"], sha256=prev["sha256"], **common)
        return FetchResult(True, "Checked: not modified since last retrieval.")
    if r.status_code != 200:
        hint = " (403 usually means a missing/invalid User-Agent)" if r.status_code == 403 else ""
        _record(conn, successful=0, error=f"HTTP {r.status_code}{hint}", **common)
        return FetchResult(False, f"MET returned HTTP {r.status_code}{hint}; last successful retrieval kept.")
    body = r.content
    try:
        data = json.loads(body)
        if not isinstance(data.get("features"), list):
            raise ValueError("no 'features' list")
    except ValueError as exc:
        _record(conn, successful=0, error=f"Unexpected response: {exc}"[:500], **common)
        return FetchResult(False, "Response was not the expected GeoJSON; last successful retrieval kept.")
    sha = hashlib.sha256(body).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{now:%Y%m%dT%H%M%SZ}-{sha[:12]}.json"
    path.write_bytes(body)
    _record(conn, successful=1, raw_path=str(path), sha256=sha, **common)
    return FetchResult(True, f"Retrieved {len(data['features'])} alert(s); original response saved.")


@dataclass
class Alert:
    id: str
    title: str
    area: str
    event: str
    level: str
    msg_type: str
    status: str          # "Actual" or "Test"
    onset: str | None
    ends: str | None
    certainty: str
    geometry_type: str
    bbox: tuple[float, float, float, float] | None
    description: str
    cap_uri: str | None


def _bbox(geom) -> tuple[float, float, float, float] | None:
    pts = []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            pts.append(c)
        else:
            for x in c or []:
                walk(x)
    walk((geom or {}).get("coordinates"))
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def parse_alerts(data: dict) -> list[Alert]:
    out = []
    for f in data.get("features", []):
        p, when = f.get("properties", {}), f.get("when", {}).get("interval", [None, None])
        cap = next((r.get("uri") for r in p.get("resources", []) if r.get("mimeType") == "application/xml"), None)
        out.append(Alert(
            id=p.get("id", "?"), title=p.get("title", ""), area=p.get("area", ""), event=p.get("event", ""),
            level=p.get("awareness_level", ""), msg_type=p.get("type", ""), status=p.get("status", ""),
            onset=when[0] if when else None, ends=when[1] if len(when) > 1 else None,
            certainty=p.get("certainty", ""), geometry_type=(f.get("geometry") or {}).get("type", "none"),
            bbox=_bbox(f.get("geometry")), description=p.get("description", ""), cap_uri=cap))
    return out


def load_cached(conn, url: str) -> tuple[dict | None, object]:
    """Latest saved response for this URL (works offline)."""
    row = last_with_body(conn, url)
    if row is None or not row["raw_path"] or not Path(row["raw_path"]).exists():
        return None, row
    return json.loads(Path(row["raw_path"]).read_bytes()), row
