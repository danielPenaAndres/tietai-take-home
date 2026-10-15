"""Build a complete SQLite snapshot from canonical.jsonl. No incremental state."""

import argparse
import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from common import DATA, ROOT, calendar_date, read_json, reject, save_json, validate


def read_vocab(path: Path) -> dict:
    mappings = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["source_vocabulary_id"], row["source_code"])
            if key in mappings or int(row["target_concept_id"]) <= 0:
                raise ValueError("Invalid or repeated vocabulary mapping")
            mappings[key] = row
    return mappings


def read_events(path: Path, out: Path) -> tuple[list[tuple[int, dict]], int]:
    events, rejected = [], 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = read_json(line)
            validate(event)
            events.append((number, event))
        except (ValueError, KeyError, IndexError, TypeError) as error:
            reject(out, "load", number, str(error), line)
            rejected += 1
    return events, rejected


def run(canonical: Path = ROOT / "out/canonical.jsonl", database: Path = ROOT / "out/omop.sqlite",
        vocab: Path = DATA / "vocab_icd10.csv") -> dict:
    out = database.parent
    mappings = read_vocab(vocab)
    events, rejected = read_events(canonical, out)
    if not events:
        raise ValueError("No valid records; existing database was not replaced")
    events.sort(key=lambda pair: datetime.fromisoformat(pair[1]["time"]))
    snapshot = events[-1][1]["time"]

    # 1. Reconcile demographics by the shared hospital MRN.
    patients, conflicts = {}, set()
    for _, event in events:
        patient = dict(event["patient"])
        mrn = patient["mrn"]
        previous = patients.get(mrn)
        if previous:
            for name in ("birth_date", "gender"):
                old, new = previous[name], patient[name]
                if old not in (None, "unknown") and new not in (None, "unknown") and old != new:
                    conflicts.add(mrn)
                if new in (None, "unknown"):
                    patient[name] = old
        patients[mrn] = patient
    bad_patients = conflicts | {mrn for mrn, patient in patients.items() if not patient["birth_date"] or patient["birth_date"] > snapshot[:10]}
    usable = []
    for number, event in events:
        if event["patient"]["mrn"] in bad_patients:
            reject(out, "load", number, "Patient has no birth date or has conflicting/invalid demographics", event)
            rejected += 1
        else:
            usable.append((number, event))
    if not usable:
        raise ValueError("No eligible patients; existing database was not replaced")

    # 2. Consolidate each visit before writing it. A03 supplies the real end.
    visits, owners = {}, {}
    for _, event in usable:
        visit = event["visit"]
        if not visit:
            continue
        key, mrn = visit["key"], event["patient"]["mrn"]
        previous = visits.get(key)
        if previous and (owners[key] != mrn or previous["start"] != visit["start"]):
            raise ValueError("Visit identity conflict; existing database was not replaced")
        if previous is None or previous["end"] is None or visit["end"] is not None:
            visits[key], owners[key] = visit, mrn

    # Build in memory first: a failed build does not damage yesterday's output.
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        person_ids, visit_ids = {}, {}
        for mrn in sorted(set(patients) - bad_patients):
            patient = patients[mrn]
            year, month, day = map(int, calendar_date(patient["birth_date"]).split("-"))
            gender = {"male": 8507, "female": 8532}.get(patient["gender"], 0)
            cursor = db.execute("INSERT INTO person (gender_concept_id,year_of_birth,month_of_birth,day_of_birth,person_source_value) VALUES (?,?,?,?,?)", (gender, year, month, day, mrn))
            person_ids[mrn] = cursor.lastrowid
        provisional = 0
        for key, visit in sorted(visits.items()):
            end = visit["end"]
            if end is None:
                provisional += 1
                end = snapshot if visit["class"] == "IMP" else visit["start"]
            if datetime.fromisoformat(end) < datetime.fromisoformat(visit["start"]):
                raise ValueError("Visit starts after the snapshot")
            concept = {"IMP": 9201, "AMB": 9202, "EMER": 9203}.get(visit["class"], 0)
            cursor = db.execute("INSERT INTO visit_occurrence (person_id,visit_concept_id,visit_start_date,visit_start_datetime,visit_end_date,visit_end_datetime,visit_type_concept_id,visit_source_value) VALUES (?,?,?,?,?,?,?,?)",
                                (person_ids[owners[key]], concept, visit["start"][:10], visit["start"], end[:10], end, 32817, key))
            visit_ids[key] = cursor.lastrowid

        # 3. Map diagnoses; repeated snapshots of the same diagnosis share a row.
        seen, unmapped, deferred, observations, medications = set(), 0, 0, 0, 0
        for number, event in usable:
            mrn = event["patient"]["mrn"]
            observations += len(event["observations"])
            medications += len(event["medications"])
            invalid_link = any(c["visit_key"] and (c["visit_key"] not in visit_ids or owners[c["visit_key"]] != mrn) for c in event["conditions"])
            if invalid_link:
                reject(out, "load", number, "Diagnosis has an unresolved or cross-patient visit", event)
                rejected += 1
                continue
            for condition in event["conditions"]:
                mapping = mappings.get((condition["vocabulary"], condition["code"]))
                if mapping and mapping["domain_id"] != "Condition":
                    deferred += 1
                    continue
                key = (mrn, condition["visit_key"], condition["vocabulary"], condition["code"], condition["date"])
                if key in seen:
                    continue
                seen.add(key)
                concept = int(mapping["target_concept_id"]) if mapping else 0
                unmapped += int(mapping is None)
                db.execute("INSERT INTO condition_occurrence (person_id,condition_concept_id,condition_start_date,condition_type_concept_id,visit_occurrence_id,condition_source_value) VALUES (?,?,?,?,?,?)",
                           (person_ids[mrn], concept, condition["date"], 32817, visit_ids.get(condition["visit_key"]), condition["code"]))
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key check failed")
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                  for name in ("person", "visit_occurrence", "condition_occurrence")}
        db.commit()
        database.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(database)
        try:
            db.backup(target)
        finally:
            target.close()
    finally:
        db.close()
    report = {"rows": counts, "rejected_records": rejected, "unmapped_conditions": unmapped,
              "deferred_conditions": deferred, "observations_kept_in_jsonl": observations,
              "medications_kept_in_jsonl": medications, "provisional_visit_ends": provisional, "snapshot": snapshot}
    save_json(out / "load_report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "out/canonical.jsonl")
    parser.add_argument("--db", type=Path, default=ROOT / "out/omop.sqlite")
    parser.add_argument("--vocab", type=Path, default=DATA / "vocab_icd10.csv")
    args = parser.parse_args()
    print(run(args.input, args.db, args.vocab))
