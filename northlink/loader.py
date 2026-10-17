"""Parse JSON files into validated models with understandable errors."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .models import DeliveryPlan, Packet, format_validation_error

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios" / "demo"


class InputError(Exception):
    def __init__(self, source: str, problems: list[str]):
        self.source, self.problems = source, problems
        super().__init__(f"{source}: " + "; ".join(problems))


def parse_json(raw: bytes | str, source: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(source, [f"not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"]) from exc
    if not isinstance(data, dict):
        raise InputError(source, ["top level must be a JSON object"])
    return data


def parse_any(raw: bytes | str, source: str) -> Packet | DeliveryPlan | dict:
    """Packet if it has packet_id, plan if it has plan_id, handover dict if format matches."""
    data = parse_json(raw, source)
    try:
        if "packet_id" in data:
            return Packet.model_validate(data)
        if "plan_id" in data:
            return DeliveryPlan.model_validate(data)
    except ValidationError as exc:
        raise InputError(source, format_validation_error(exc)) from exc
    if data.get("format") == "northlink-handover":
        return data
    raise InputError(source, ["unrecognised file: expected a source packet (packet_id), "
                              "a delivery plan (plan_id) or a Northlink handover"])


def load_file(path: Path | str):
    p = Path(path)
    return parse_any(p.read_bytes(), p.name)
