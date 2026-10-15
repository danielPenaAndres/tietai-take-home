"""Convenience command: run the reader, then the SQLite writer."""

import argparse
from pathlib import Path

import ingest
import load_omop
from common import ROOT


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "out")
    out = parser.parse_args().out
    print("Ingestion:", ingest.run(out=out))
    print("SQLite:", load_omop.run(out / "canonical.jsonl", out / "omop.sqlite"))
