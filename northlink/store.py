"""SQLite persistence: append-only records, review history and audit log.

Every write path validates first and then commits in one transaction
(BEGIN IMMEDIATE ... COMMIT), so a failure leaves existing state untouched.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import Coverage, Delivery, DeliveryPlan, Event, Packet

DEFAULT_DB = Path(os.environ.get("NORTHLINK_DB") or Path(__file__).resolve().parent.parent / "data" / "northlink.db")
DEFAULT_SCENARIO_START = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packets (
    packet_id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT,
    retrieved_at TEXT NOT NULL, imported_at TEXT NOT NULL,
    canonical TEXT NOT NULL, content_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    origin TEXT NOT NULL, event_id TEXT NOT NULL, revision INTEGER NOT NULL,
    packet_id TEXT NOT NULL REFERENCES packets(packet_id),
    canonical TEXT NOT NULL, content_hash TEXT NOT NULL, imported_at TEXT NOT NULL,
    PRIMARY KEY (origin, event_id, revision));
CREATE TABLE IF NOT EXISTS coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_id TEXT NOT NULL REFERENCES packets(packet_id),
    origin TEXT NOT NULL, scope_id TEXT NOT NULL,
    source_retrieved_at TEXT NOT NULL, successful INTEGER NOT NULL,
    imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT,
    canonical TEXT NOT NULL, content_hash TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
    canonical TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY, delivery_id TEXT NOT NULL,
    person TEXT NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL,
    created_wall TEXT NOT NULL, scenario_time TEXT NOT NULL,
    category TEXT NOT NULL,
    evidence TEXT NOT NULL,       -- JSON [{origin,event_id,revision,content_hash}]
    fingerprint TEXT NOT NULL,    -- JSON material fields, used for reopening
    stale_at_review TEXT NOT NULL,-- JSON list of stale reasons at decision time
    previous_review_id TEXT REFERENCES reviews(review_id));
CREATE TABLE IF NOT EXISTS review_cases (
    delivery_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('reviewed','reopened')),
    current_review_id TEXT NOT NULL REFERENCES reviews(review_id),
    reopened_reason TEXT, updated_wall TEXT NOT NULL, updated_scenario TEXT NOT NULL);
-- Reviews received from another laptop's handover: display only.
CREATE TABLE IF NOT EXISTS foreign_reviews (
    handover_id TEXT NOT NULL, review_id TEXT NOT NULL, delivery_id TEXT NOT NULL,
    payload TEXT NOT NULL, imported_at TEXT NOT NULL,
    PRIMARY KEY (handover_id, review_id));
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wall_time TEXT NOT NULL, scenario_time TEXT NOT NULL,
    action TEXT NOT NULL, subject TEXT, detail TEXT NOT NULL);
"""


def now_wall() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    if conn.execute("SELECT 1 FROM meta WHERE key='scenario_time'").fetchone() is None:
        conn.execute("INSERT INTO meta VALUES ('scenario_time', ?)", (iso(DEFAULT_SCENARIO_START),))
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def audit(conn, action: str, subject: str | None, detail: dict, scenario: datetime | None = None) -> None:
    conn.execute(
        "INSERT INTO audit (wall_time, scenario_time, action, subject, detail) VALUES (?,?,?,?,?)",
        (iso(now_wall()), iso(scenario or scenario_time(conn)), action, subject,
         json.dumps(detail, sort_keys=True)),
    )


# ---- scenario clock -------------------------------------------------------

def scenario_time(conn) -> datetime:
    return parse(conn.execute("SELECT value FROM meta WHERE key='scenario_time'").fetchone()[0])


def set_scenario_time_tx(conn, t: datetime) -> None:
    """Caller holds a transaction."""
    old = scenario_time(conn)
    conn.execute("UPDATE meta SET value=? WHERE key='scenario_time'", (iso(t),))
    audit(conn, "clock_set", None, {"from": iso(old), "to": iso(t)}, scenario=t)


# ---- reads ----------------------------------------------------------------

def all_events(conn) -> list[Event]:
    return [Event.model_validate_json(r[0]) for r in conn.execute("SELECT canonical FROM events")]


def event_rows(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT e.*, p.kind AS packet_kind, p.label AS packet_label FROM events e "
        "JOIN packets p USING (packet_id) ORDER BY origin, event_id, revision").fetchall()


def all_coverage(conn) -> list[Coverage]:
    return [Coverage(origin=r["origin"], scope_id=r["scope_id"],
                     source_retrieved_at=parse(r["source_retrieved_at"]),
                     successful=bool(r["successful"]))
            for r in conn.execute("SELECT * FROM coverage")]


def deliveries(conn) -> list[Delivery]:
    return [Delivery.model_validate_json(r[0])
            for r in conn.execute("SELECT canonical FROM deliveries ORDER BY delivery_id")]


def packets(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT packet_id, kind, label, retrieved_at, imported_at, content_hash "
                        "FROM packets ORDER BY imported_at, packet_id").fetchall()


def plans(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT plan_id, kind, label, imported_at FROM plans").fetchall()


def event_packet_kind(conn) -> dict[tuple[str, str, int], str]:
    return {(r["origin"], r["event_id"], r["revision"]): r["packet_kind"] for r in event_rows(conn)}


def event_hashes(conn) -> dict[tuple[str, str, int], str]:
    return {(r["origin"], r["event_id"], r["revision"]): r["content_hash"]
            for r in conn.execute("SELECT origin, event_id, revision, content_hash FROM events")}


def review_case(conn, delivery_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM review_cases WHERE delivery_id=?", (delivery_id,)).fetchone()


def review_cases(conn) -> dict[str, sqlite3.Row]:
    return {r["delivery_id"]: r for r in conn.execute("SELECT * FROM review_cases")}


def review(conn, review_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()


def review_history(conn, delivery_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM reviews WHERE delivery_id=? ORDER BY created_wall, CAST(SUBSTR(review_id, 2) AS INTEGER)",
                        (delivery_id,)).fetchall()


def audit_log(conn, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def next_review_id(conn) -> str:
    n = conn.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(review_id, 2) AS INTEGER)), 0) FROM reviews "
        "WHERE review_id GLOB 'R[0-9]*' AND SUBSTR(review_id, 2) NOT GLOB '*[^0-9]*'").fetchone()[0]
    return f"R{n + 1}"
