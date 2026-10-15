"""A few end-to-end checks for the things that can change clinical results."""

import copy
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ingest
import load_omop
from common import DATA, read_json


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data, self.out = self.root / "data", self.root / "out"
        shutil.copytree(DATA, self.data)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self) -> dict:
        ingest.run(self.data, self.out)
        return load_omop.run(self.out / "canonical.jsonl", self.out / "omop.sqlite", self.data / "vocab_icd10.csv")

    def query(self, sql: str) -> list:
        db = sqlite3.connect(self.out / "omop.sqlite")
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()

    def test_full_batch_and_repeat(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first["rows"], {"person": 12, "visit_occurrence": 16, "condition_occurrence": 16})
        self.assertEqual(len((self.out / "canonical.jsonl").read_text().splitlines()), 43)
        self.assertEqual(self.query("PRAGMA foreign_key_check"), [])

    def test_maria_has_one_closed_visit_and_two_diagnoses(self) -> None:
        self.build()
        self.assertEqual(self.query("SELECT COUNT(DISTINCT v.visit_occurrence_id),MAX(v.visit_end_datetime),COUNT(DISTINCT c.condition_occurrence_id) FROM person p JOIN visit_occurrence v USING(person_id) JOIN condition_occurrence c USING(person_id) WHERE p.person_source_value='100012345'"), [(1, "2026-03-15T13:30:00+01:00", 2)])

    def test_missing_birth_unknown_gender_and_unmapped_codes(self) -> None:
        result = self.build()
        self.assertEqual(result["rejected_records"], 1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM person WHERE person_source_value='100089012'"), [(0,)])
        self.assertEqual(self.query("SELECT gender_concept_id FROM person WHERE person_source_value='100345678'"), [(0,)])
        self.assertCountEqual(self.query("SELECT condition_source_value FROM condition_occurrence WHERE condition_concept_id=0"), [("C18.99",), ("C25.9",)])
        self.assertEqual(result["deferred_conditions"], 3)

    def test_separators_line_endings_and_original_z_segment(self) -> None:
        raw = (self.data / "adt_feed.hl7").read_bytes()
        for newline in (b"\n", b"\r\n", b"\r"):
            self.assertEqual(len(ingest.split_messages(raw.replace(b"\n", newline))), 20)
        messages = ingest.split_messages(raw)
        self.assertEqual(ingest.read_hl7(messages[10])["patient"]["birth_date"], "1961-12-01")
        event = ingest.read_hl7(messages[16])
        self.assertIn("\x07", event["raw"])
        self.assertTrue(any(line.startswith("ZPV") for line in event["extra"]))

    def test_source_errors_and_exact_duplicate(self) -> None:
        path = self.data / "adt_feed.hl7"
        raw = path.read_bytes()
        path.write_bytes(raw + b"\n\n" + ingest.split_messages(raw)[0])
        result = ingest.run(self.data, self.out)
        self.assertEqual(result, {"accepted": 43, "rejected": 2, "duplicates": 1})
        self.assertEqual(len(list((self.out / "dlq/hl7").glob("*.json"))), 2)

    def test_bad_fhir_reference_and_jsonl_line_are_isolated(self) -> None:
        bundle = read_json((self.data / "fhir_bundle.json").read_text())
        broken = copy.deepcopy(bundle)
        broken["entry"][3]["resource"]["encounter"]["reference"] = "Encounter/enc-011-1"
        (self.data / "fhir_bundle.json").write_text(json.dumps(broken))
        self.assertEqual(ingest.run(self.data, self.out)["rejected"], 3)
        with (self.out / "canonical.jsonl").open("a") as stream:
            stream.write("this is not JSON\n")
        report = load_omop.run(self.out / "canonical.jsonl", self.out / "omop.sqlite", self.data / "vocab_icd10.csv")
        self.assertEqual(report["rows"]["person"], 12)
        self.assertEqual(report["rejected_records"], 2)
        broken = copy.deepcopy(bundle)
        broken["entry"][3]["resource"]["verificationStatus"] = None
        (self.data / "fhir_bundle.json").write_text(json.dumps(broken))
        self.assertEqual(ingest.run(self.data, self.out)["rejected"], 3)

    def test_corrected_birth_and_reordered_input(self) -> None:
        self.build()
        path = self.data / "adt_feed.hl7"
        path.write_bytes(path.read_bytes().replace(b"GOMEZ^ROBERTO|||M", b"GOMEZ^ROBERTO||19900101|M"))
        ingest.run(self.data, self.out)
        canonical = self.out / "canonical.jsonl"
        canonical.write_text("\n".join(reversed(canonical.read_text().splitlines())) + "\n")
        report = load_omop.run(canonical, self.out / "omop.sqlite", self.data / "vocab_icd10.csv")
        self.assertEqual(report["rows"], {"person": 13, "visit_occurrence": 17, "condition_occurrence": 17})

    def test_independent_commands(self) -> None:
        folder = Path(__file__).parent
        commands = [[str(folder / "ingest.py"), "--data", str(self.data), "--out", str(self.out)],
                    [str(folder / "load_omop.py"), "--input", str(self.out / "canonical.jsonl"), "--db", str(self.out / "omop.sqlite")]]
        for command in commands:
            result = subprocess.run([sys.executable, *command], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
