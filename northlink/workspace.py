"""Workspace isolation for imports. Pure classification plus one guarded entry point.

Two exercise workspaces use separate databases:
- "finnmark": recorded MET replay with fictional deliveries at FN-* exercise points.
- "synthetic": fictional C1-C3 corridors with demo-* sources.

Every plan, delivery, packet, event and coverage row in an import is classified.
A payload is rejected *before any write* when it contains records of the other
workspace or a mixture of both. Records with no workspace signal (for example a
live MET packet without exercise corridors) are neutral and follow the normal
integrity rules.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from .models import DeliveryPlan, Packet
from .reconcile import IntegrityError, import_packet, import_plan

FINNMARK = "finnmark"
SYNTHETIC = "synthetic"
NAMES = {FINNMARK: "Finnmark · recorded weather", SYNTHETIC: "Synthetic exercise"}
RECORDED_ORIGIN = "met-metalerts-recorded"   # mirrors replay.ORIGIN without importing replay
FINNMARK_PACKET_PREFIX = "recorded-finnmark-"


def _corridor_label(corridor: Any) -> str | None:
    if not isinstance(corridor, str) or not corridor:
        return None
    if corridor.startswith(("FN-", "OUTSIDE:FN-")):
        return FINNMARK
    return SYNTHETIC


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _items(value: Any) -> Iterable:
    return value if isinstance(value, (list, tuple)) else ()


def _plan_labels(plan: Any) -> set[str]:
    """Every delivery is classified by its scope: FN-* belongs to Finnmark; any
    other scope is a synthetic corridor. (The Finnmark plan is itself marked
    kind='synthetic' because its deliveries are fictional, so plan kind alone
    cannot decide.)"""
    labels = set()
    for d in _items(_get(plan, "deliveries")):
        label = _corridor_label(_get(d, "corridor_id"))
        if label:
            labels.add(label)
    return labels


def _packet_labels(packet: Any) -> set[str]:
    labels = set()
    kind = _get(packet, "kind")
    if kind == SYNTHETIC:
        labels.add(SYNTHETIC)
    packet_id = _get(packet, "packet_id")
    if isinstance(packet_id, str) and packet_id.startswith(FINNMARK_PACKET_PREFIX):
        labels.add(FINNMARK)
    for e in _items(_get(packet, "events")):
        origin = _get(e, "origin")
        if origin == RECORDED_ORIGIN:
            labels.add(FINNMARK)
        elif isinstance(origin, str) and origin.startswith("demo-"):
            labels.add(SYNTHETIC)
        corridor = _get(e, "corridor_id")
        if isinstance(corridor, str) and corridor.startswith(("FN-", "OUTSIDE:FN-")):
            labels.add(FINNMARK)
        elif kind == SYNTHETIC and corridor:
            labels.add(SYNTHETIC)
    for c in _items(_get(packet, "coverage")):
        origin = _get(c, "origin")
        if isinstance(origin, str) and origin.startswith("demo-"):
            labels.add(SYNTHETIC)
        elif origin == RECORDED_ORIGIN:
            labels.add(FINNMARK)
    return labels


def classify(obj: Any) -> set[str]:
    """Return the workspace labels present in a plan, packet or handover payload.

    An empty set means the payload carries no workspace signal; two labels mean
    a mixed payload that no single workspace may accept."""
    if isinstance(obj, DeliveryPlan):
        return _plan_labels(obj)
    if isinstance(obj, Packet):
        return _packet_labels(obj)
    if isinstance(obj, dict):
        labels: set[str] = set()
        for p in _items(obj.get("plans")):
            labels |= _plan_labels(p)
        for p in _items(obj.get("packets")):
            labels |= _packet_labels(p)
        return labels
    return set()


def mismatch(obj: Any, workspace: str) -> str | None:
    """Human-readable rejection reason, or None when the import may proceed."""
    labels = classify(obj)
    if len(labels) > 1:
        return ("contains both Finnmark recorded-weather records and synthetic exercise records. "
                "Mixed-workspace files are rejected; nothing changed.")
    if labels and workspace not in labels:
        other = next(iter(labels))
        return (f"belongs to the '{NAMES[other]}' workspace, not '{NAMES[workspace]}'. "
                "Switch workspace first; nothing changed.")
    return None


def guarded_import(conn: sqlite3.Connection, obj: Any, workspace: str, source: str,
                   import_handover=None) -> tuple[str, str]:
    """The single import path used by the UI. Returns (level, message).

    The workspace check runs before any database write; downstream imports are
    themselves atomic, so a rejection at any stage leaves the database unchanged."""
    if workspace not in NAMES:
        raise ValueError(f"unknown workspace {workspace!r}")
    reason = mismatch(obj, workspace)
    if reason:
        return "error", f"{source}: {reason}"
    try:
        if isinstance(obj, DeliveryPlan):
            return "success", (f"{source}: plan imported." if import_plan(conn, obj)
                               else f"{source}: identical plan already imported; nothing changed.")
        if isinstance(obj, Packet):
            return "success", f"{source}: " + import_packet(conn, obj).summary()
        if import_handover is None:
            from .handover import import_handover
        return "success", import_handover(conn, obj)
    except (IntegrityError, ValueError) as exc:
        return "error", f"{source}: {exc}"
    except sqlite3.Error as exc:
        return "error", f"{source}: database rejected the import, nothing changed ({type(exc).__name__}: {exc})"
