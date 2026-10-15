"""Small helpers shared by the reader and the SQLite writer."""

import base64
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"


def timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be text")
    if value.isdigit():
        if len(value) != 14:
            raise ValueError("HL7 time needs YYYYMMDDhhmmss")
        # The supplied hospital batch is from March, before the DST change.
        result = datetime.strptime(value, "%Y%m%d%H%M%S")
        result = result.replace(tzinfo=timezone(timedelta(hours=1)))
    else:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp needs a UTC offset")
    return result.isoformat()


def calendar_date(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Date must be text")
    if value.isdigit() and len(value) == 8:
        value = datetime.strptime(value, "%Y%m%d").date().isoformat()
    return date.fromisoformat(value).isoformat()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def reject(out: Path, stage: str, number: int, reason: str, raw: Any) -> None:
    if isinstance(raw, bytes):
        raw = {"base64": base64.b64encode(raw).decode("ascii")}
    save_json(out / "dlq" / stage / f"{number:03d}.json", {"reason": reason, "raw": raw})
    print(f"{stage} record {number}: {reason}")


def new_event(source: str, source_id: str, time: str, raw: Any) -> dict[str, Any]:
    return {"source": source, "source_id": source_id, "time": timestamp(time),
            "patient": None, "visit": None, "conditions": [],
            "observations": [], "medications": [], "warnings": [], "extra": [], "raw": raw}


def read_json(text: str) -> Any:
    def invalid_number(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(text, parse_constant=invalid_number)


def validate(event: dict[str, Any]) -> None:
    """Check the fields used by the writer, including its disk input."""
    if not isinstance(event, dict) or event.get("source") not in ("hl7", "fhir"):
        raise ValueError("Expected an HL7/FHIR canonical record")
    timestamp(event["time"])
    for name in ("conditions", "observations", "medications", "warnings", "extra"):
        if not isinstance(event[name], list):
            raise ValueError(f"{name} must be a list")
    patient = event["patient"]
    if not isinstance(patient["mrn"], str) or not patient["mrn"]:
        raise ValueError("Missing patient identifier")
    if patient["birth_date"] is not None:
        calendar_date(patient["birth_date"])
    if patient["gender"] not in ("male", "female", "other", "unknown"):
        raise ValueError("Invalid administrative gender")
    visit = event["visit"]
    if visit:
        start = timestamp(visit["start"])
        if not isinstance(visit["key"], str) or not isinstance(visit["class"], str):
            raise ValueError("Visit needs a key and a class")
        if visit["end"] and datetime.fromisoformat(timestamp(visit["end"])) < datetime.fromisoformat(start):
            raise ValueError("Visit ends before its start")
    for condition in event["conditions"]:
        if not isinstance(condition["code"], str) or not condition["code"]:
            raise ValueError("Diagnosis needs a code")
        if not isinstance(condition["vocabulary"], str) or not condition["vocabulary"]:
            raise ValueError("Diagnosis needs a vocabulary")
        calendar_date(condition["date"])
        if condition["date"] > event["time"][:10]:
            raise ValueError("Diagnosis date is after the source snapshot")
        if condition["visit_key"] is not None and not isinstance(condition["visit_key"], str):
            raise ValueError("Invalid diagnosis visit reference")
    json.dumps(event, allow_nan=False)
