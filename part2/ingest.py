"""Read the supplied HL7 and FHIR files into one JSON object per source record."""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import DATA, ROOT, calendar_date, new_event, read_json, reject, save_json, timestamp, validate


def split_messages(data: bytes) -> list[bytes]:
    messages, current = [], []
    for line in data.splitlines(keepends=True):
        blank = not line.strip(b"\r\n\t ")
        if blank or (line.startswith(b"MSH") and current):
            if current:
                messages.append(b"".join(current).rstrip(b"\r\n"))
                current = []
        if not blank:
            current.append(line)
    if current:
        messages.append(b"".join(current).rstrip(b"\r\n"))
    return messages


def read_hl7(data: bytes) -> dict[str, Any]:
    raw = data.decode("utf-8")
    if not raw.startswith("MSH") or len(raw) < 9:
        raise ValueError("Missing MSH header")
    field = raw[3]
    encoding = raw.split(field)[1]
    if len(encoding) != 4 or len(set(field + encoding)) != 5:
        raise ValueError("Invalid MSH delimiters")
    component, repetition = encoding[:2]
    lines = re.split(r"\r\n|\r|\n", raw)
    segments: dict[str, list[list[str]]] = {}
    for line in lines:
        clean = "".join(ch for ch in line if ord(ch) >= 32)
        parts = clean.split(field)
        if not re.fullmatch(r"[A-Z0-9]{3}", parts[0]):
            raise ValueError("Invalid segment name")
        segments.setdefault(parts[0], []).append(parts)

    def get(name: str, position: int) -> str:
        row = segments[name][0]
        index = position - 1 if name == "MSH" else position
        return row[index] if index < len(row) else ""

    if len(segments.get("PID", [])) != 1 or len(segments.get("MSH", [])) != 1:
        raise ValueError("Expected one PID and one MSH")
    if get("MSH", 12) != "2.5":
        raise ValueError("Only HL7 v2.5 is supported")
    time = timestamp(get("MSH", 7))
    control = get("MSH", 10)
    if not control:
        raise ValueError("Missing MSH-10 control ID")
    key = f"{get('MSH', 3)}/{get('MSH', 4)}/{time[:10]}/{control}"
    event = new_event("hl7", key, time, raw)
    message_type = get("MSH", 9).split(component)
    if len(message_type) == 1 and component != "^":
        # One supplied message contradicts its own MSH-2, only in MSH-9.
        message_type = get("MSH", 9).split("^")
        event["warnings"].append("Fixture: MSH-9 uses ^ despite declared separator")
    family, trigger = message_type[:2]
    if (family, trigger) not in {("ADT", "A01"), ("ADT", "A04"), ("ADT", "A08"), ("ADT", "A03"), ("ORU", "R01")}:
        raise ValueError("Unsupported message type")
    identifiers = [value.split(component) for value in get("PID", 3).split(repetition)]
    mrns = [value[0] for value in identifiers if len(value) >= 5 and value[3:5] == ["SAN_ANDRES", "MR"]]
    if len(mrns) != 1 or not mrns[0]:
        raise ValueError("Expected one SAN_ANDRES MRN")
    event["patient"] = {"mrn": mrns[0], "birth_date": calendar_date(get("PID", 7)) if get("PID", 7) else None,
                        "gender": {"M": "male", "F": "female", "O": "other"}.get(get("PID", 8), "unknown")}
    event["extra"] = [line for line in lines if line[:3] not in {"MSH", "EVN", "PID", "PV1", "DG1", "OBR", "OBX"}]
    if any(ord(ch) < 32 and ch not in "\r\n" for ch in raw):
        event["warnings"].append("Control character removed for parsing; original kept")
    if family == "ADT":
        if len(segments.get("PV1", [])) != 1:
            raise ValueError("ADT needs one PV1")
        start = get("PV1", 44)
        if not start and get("PV1", 48):
            start = get("PV1", 48)
            event["warnings"].append("Fixture: admission time read from PV1-48")
        start = timestamp(start)
        number = get("PV1", 19).split(component)[0]
        if number == "VIP":
            number = ""
            event["warnings"].append("Fixture: repeated VIP is not a visit identifier")
        visit_key = f"hl7:{mrns[0]}:{number or start}"
        end = timestamp(get("PV1", 45)) if get("PV1", 45) else None
        if trigger == "A03" and end is None:
            end = timestamp(get("EVN", 2)) if "EVN" in segments else time
            event["warnings"].append("Discharge time taken from event")
        event["visit"] = {"key": visit_key, "start": start, "end": end,
                          "class": {"I": "IMP", "O": "AMB", "E": "EMER"}.get(get("PV1", 2), "unknown")}
        for row in segments.get("DG1", []):
            code, display, vocabulary = row[3].split(component)
            if vocabulary == "I10":
                vocabulary = "ICD10CM"
                event["warnings"].append("Fixture: I10 treated as the supplied ICD10CM stub")
            event["conditions"].append({"code": code, "vocabulary": vocabulary,
                                        "date": calendar_date(row[5]) if len(row) > 5 and row[5] else time[:10],
                                        "visit_key": visit_key})
    else:
        if not segments.get("OBX") or len(segments.get("OBR", [])) > 1:
            raise ValueError("Expected results from one OBR group")
        for row in segments["OBX"]:
            code = row[3].split(component)[0]
            value = float(row[5]) if row[2] == "NM" else row[5]
            status = row[11] if len(row) > 11 and row[11] else "unknown"
            event["observations"].append({"code": code, "value": value, "unit": row[6] if len(row) > 6 else None,
                                          "status": status, "date": time[:10]})
    validate(event)
    return event


def read_fhir(resource: dict[str, Any], index: dict[str, dict], time: str) -> dict[str, Any]:
    kind, identifier = resource["resourceType"], resource["id"]
    if kind not in ("Patient", "Encounter", "Condition", "Observation", "MedicationStatement") or not isinstance(identifier, str) or not identifier:
        raise ValueError("Unsupported resource or missing ID")
    event = new_event("fhir", f"{kind}/{identifier}", time, resource)

    def resolve(reference: dict, expected: str) -> dict:
        target = index[reference["reference"]]
        if target["resourceType"] != expected:
            raise ValueError("Wrong reference type")
        return target

    def mrn(patient: dict) -> str:
        values = [v["value"] for v in patient.get("identifier", []) if isinstance(v, dict) and v.get("system") == "urn:oid:2.16.724.4.40.100.1"]
        if len(values) != 1:
            raise ValueError("Expected one hospital identifier")
        return values[0]

    patient = resource if kind == "Patient" else resolve(resource["subject"], "Patient")
    event["patient"] = {"mrn": mrn(patient), "birth_date": patient.get("birthDate"), "gender": patient.get("gender", "unknown")}
    if kind == "Encounter":
        if resource["status"] not in ("finished", "in-progress"):
            raise ValueError("Encounter is not an actual visit")
        period = resource["period"]
        if resource["status"] == "finished" and not period.get("end"):
            raise ValueError("Finished encounter needs an end")
        event["visit"] = {"key": f"fhir:Encounter/{identifier}", "start": timestamp(period["start"]),
                          "end": timestamp(period["end"]) if period.get("end") else None, "class": resource["class"]["code"]}
    elif kind != "Patient":
        reference = resource.get("context") if kind == "MedicationStatement" else resource.get("encounter")
        visit_key = None
        if reference:
            visit = resolve(reference, "Encounter")
            if mrn(resolve(visit["subject"], "Patient")) != mrn(patient):
                raise ValueError("Encounter belongs to another patient")
            visit_key = f"fhir:Encounter/{visit['id']}"
        codeable = resource.get("medicationCodeableConcept") if kind == "MedicationStatement" else resource.get("code")
        systems = {"http://hl7.org/fhir/sid/icd-10-cm": "ICD10CM", "http://loinc.org": "LOINC",
                   "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm"}
        codes = [v for v in codeable["coding"] if isinstance(v, dict) and isinstance(v.get("system"), str) and v["system"] in systems]
        if len(codes) != 1:
            raise ValueError("Expected one supported coding")
        coding = codes[0]
        when = resource.get("onsetDateTime", resource.get("effectiveDateTime", time))
        fact = {"code": coding["code"], "vocabulary": systems[coding["system"]],
                "date": calendar_date(when[:10]), "visit_key": visit_key}
        if fact["date"] > time[:10]:
            event["warnings"].append("Clinical date is after the source snapshot")
        if kind == "Condition":
            verification = resource.get("verificationStatus", {})
            if not isinstance(verification, dict) or not isinstance(verification.get("coding", []), list):
                raise ValueError("Invalid condition verification status")
            verification = verification.get("coding", [])
            if any(not isinstance(v, dict) for v in verification):
                raise ValueError("Invalid verification coding")
            if any(v.get("code") in ("refuted", "entered-in-error") for v in verification):
                raise ValueError("Condition is refuted or entered in error")
            event["conditions"].append(fact)
        elif kind == "Observation":
            quantity = resource["valueQuantity"]
            if type(quantity["value"]) not in (int, float):
                raise ValueError("Expected a numeric quantity")
            fact.update(value=quantity["value"], unit=quantity.get("unit"), status=resource["status"])
            event["observations"].append(fact)
        else:
            fact.update(display=coding.get("display"), status=resource["status"])
            event["medications"].append(fact)
    validate(event)
    return event


def run(data: Path = DATA, out: Path = ROOT / "out") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    events, seen = [], {}
    report = {"accepted": 0, "rejected": 0, "duplicates": 0}
    for number, raw in enumerate(split_messages((data / "adt_feed.hl7").read_bytes()), 1):
        try:
            event = read_hl7(raw)
            key = event["source_id"]
            if key in seen:
                if seen[key] != raw:
                    raise ValueError("Control ID reused with different content")
                report["duplicates"] += 1
                continue
            seen[key] = raw
            events.append(event)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            reject(out, "hl7", number, str(error), raw)
            report["rejected"] += 1
    try:
        bundle = read_json((data / "fhir_bundle.json").read_text(encoding="utf-8"))
        if bundle["resourceType"] != "Bundle" or bundle["type"] != "collection":
            raise ValueError("Expected a collection Bundle")
        time = timestamp(bundle["timestamp"])
        entries = bundle["entry"]
        if not isinstance(entries, list):
            raise ValueError("Bundle entries must be a list")
        index, repeated = {}, set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
                continue
            resource = entry.get("resource", {})
            key = f"{resource.get('resourceType')}/{resource.get('id')}"
            if key in index:
                repeated.add(key)
            index[key] = resource
        for number, entry in enumerate(entries, 1):
            try:
                resource = entry["resource"]
                key = f"{resource['resourceType']}/{resource['id']}"
                if key in repeated:
                    raise ValueError("Repeated resource identity")
                # The fixture has no fullUrl: resolve unique relative references locally.
                usable = {k: v for k, v in index.items() if k not in repeated}
                event = read_fhir(resource, usable, time)
                if not entry.get("fullUrl"):
                    event["warnings"].append("Fixture: no fullUrl; local relative reference resolution")
                json.dumps(event, allow_nan=False)
                events.append(event)
            except (ValueError, KeyError, IndexError, TypeError) as error:
                reject(out, "fhir", number, str(error), entry)
                report["rejected"] += 1
    except (ValueError, KeyError, TypeError) as error:
        reject(out, "fhir", 0, str(error), (data / "fhir_bundle.json").read_bytes())
        report["rejected"] += 1
    temporary = out / "canonical.jsonl.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, allow_nan=False) + "\n")
    temporary.replace(out / "canonical.jsonl")
    report["accepted"] = len(events)
    save_json(out / "ingest_report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=ROOT / "out")
    args = parser.parse_args()
    print(run(args.data, args.out))
