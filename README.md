# San Andres data integration

This is a small batch solution using Python 3.11+ and SQLite. It uses the standard library only. Run the commands from this folder.

## Run it

```console
python part2/run.py
```

The two components also run separately:

```console
python part2/ingest.py
python part2/load_omop.py
```

Results are written to `out/`: `canonical.jsonl`, `omop.sqlite`, two short reports and rejected records under `dlq/`. The reader prints a reason for each reject. Missing input files or database/configuration failures stop the command.

Reports describe the current run; the DLQ may retain earlier rejects. Use `python part2/run.py --out out/demo2` for a fresh output folder.

**The writer rebuilds the whole output database from the JSONL.** It builds in memory and copies the completed result into the dedicated output database. Running it again gives the same snapshot without duplicate rows. Use this database only for the exercise; it replaces previous output and does not preserve unrelated tables or incremental history.

Run the checks:

```console
python -m unittest discover -s part2 -p test_pipeline.py -v
```

The supplied batch produces **43 canonical records**, **12 patients**, **16 visits** and **16 diagnoses**. Ingestion rejects the malformed HL7 message and the control-ID collision. The writer rejects one canonical record for the patient without a birth date, withholding that patient's visit and diagnosis too. There are 8 tests covering counts, repeat runs, linking, source errors, a corrected birth date and independent commands.

## Part 1

Read the [architecture](part1/architecture.md), [delivery plan](part1/plan.md) and [kickoff questions](part1/questions.md). The diagram uses Mermaid. It proposes responsibilities for Hydra Connect and Hydra Platform on GKE; no live Hydra APIs or cloud deployment are implemented here.

## Why this implementation

I chose Python because this is file parsing and transformation, and SQLite keeps the example easy to run. There are two main scripts, a small shared helper file and the SQL schema.

The JSONL is the boundary: the reader handles HL7/FHIR details, while the writer handles patients, visits and diagnosis mappings. It can be inspected or loaded again independently. No event hashing, audit database or incremental loading framework is needed for this complete, small batch.

### Common record format

Each line represents **one source message/resource**. Both formats use these fields:

| Field | Meaning |
|---|---|
| `source`, `source_id`, `time` | Source type, original identity and source timestamp. |
| `patient` | Hospital MRN, birth date or null, administrative gender. |
| `visit` | Visit key, start, end or null, class; null when absent. |
| `conditions` | List of code, vocabulary, date and optional visit key. |
| `observations`, `medications` | Facts retained for a later domain writer. |
| `warnings`, `extra`, `raw` | Recovery notes, unhandled segments including Z-segments, original message/resource. |

Full dates use `YYYY-MM-DD`; timestamps include an offset. A reader can emit one record containing a patient, visit and several diagnoses. The writer reconciles these entities before inserting rows. Runtime checks validate the fields it consumes; this is not a complete HL7/FHIR validator.

### Data decisions

- Match patients by the approved fixture MRN namespace, never by name. Contradictory demographics are quarantined. A missing birth date excludes a new patient; missing gender maps to concept 0. Confirm the administrative sex/gender interpretation before production.
- Combine HL7 admission/update/discharge by visit identifier or admission time. Keep FHIR visits separate: timestamps alone do not prove that visits from two systems are identical.
- Deduplicate the same diagnosis by patient, visit, vocabulary, code and date. Keep distinct visits/diagnosis dates separate.
- Use the supplied CSV as the vocabulary stub. Unknown codes C18.99/C25.9 keep their source value and concept 0. Targets outside the Condition domain are deferred: the stub has `Symptom` for R07.9 and `Observation` for O80. Those labels require dictionary review, not automatic conversion to diagnoses.
- An open inpatient visit uses the source snapshot time as a provisional end; other visits without an end use their start. The original end remains null in JSONL, so an imputed end can be traced. No birth time or clinical onset time is invented.

### Problems found in the sample

The reader gets separators from MSH. This hospital sample also needs a few explicit repairs, each recorded in `warnings`: admission time is at PV1-48 rather than PV1-44; PV1-19 repeats `VIP`; the custom-separator message still uses `^` in MSH-9; DG1 says `I10` while the supplied CSV says ICD10CM. These are sample-specific assumptions, not general rules for other hospitals. HL7 times without offsets use `+01:00` for this March batch; production needs a timezone/DST policy.

The BEL control byte is cleaned only for parsing; the original and Z-segments remain available. Exact HL7 duplicates are skipped within the batch; a reused sender/day/control ID with different content is quarantined. Three numeric OBX segments lack the expected OBX-11 finality field, so their status remains unknown.

The FHIR collection lacks `fullUrl`. The reader resolves unique relative references inside this file, including forward references. Missing/ambiguous/cross-patient links are rejected. It does not fetch external resources. Patient 013 lacks gender. The observations include suspect HbA1c/weight values and a date in 2099; the future date is flagged and values remain unchanged. RxNorm code 40048 has conflicting drug displays. Observations and medication statements stay in JSONL, not clinical output tables, until their units, codes and meanings are reviewed.

## Limits and the next step towards production

The code loads a complete batch in memory. The SQL is a subset of the three requested OMOP tables, not a full CDM for OHDSI tools. Measurement is part of the hospital plan; the code exercise asks for three tables. No DQ agent is added despite the stale Part 3 reference in the fixture README.

For openEHR I would add another reader that uses approved OPT template versions/node paths, resolves `ehr_id` to MRN, and retains composition UID/version, time and units. It would emit this same common format; unknown templates would be rejected for review. A composition export or the source's AQL API can supply input. [openEHR Query API](https://specifications.openehr.org/releases/ITS-REST/latest/query.html).

For multi-tenant Hydra, stamp an authenticated tenant ID at entry, scope identifiers/storage/permissions to that tenant and use separate tenant outputs. This local version is for one hospital. Monitor batch counts, rejected records, mapping gaps and source lag. Protect raw/JSONL/DLQ/backups with restricted access, encryption and approved retention; authorise research access separately.

For replay, fix the source or mapping, rerun the reader and rebuild the complete snapshot. There is no automatic single-record replay or persisted control-ID registry. A production incremental loader would need both, plus versioned raw batches and correction/deletion handling. The first production work is to confirm the source profile and replace the stub with reviewed mappings. [OMOP 5.4 conventions](https://ohdsi.github.io/CommonDataModel/cdm54.html), [FHIR R4 Bundle](https://hl7.org/fhir/R4/bundle.html).


## AI assistance

AI tools assisted with implementation and documentation. The commands, tests and sample results were checked locally.

## Next steps, in five lines

1. Confirm identifiers, source quirks and the first cohort with the hospital.
2. Replace the vocabulary stub and review unmapped or wrong-domain codes.
3. Add reviewed Measurement and two template-specific openEHR readers.
4. Add incremental checkpoints, versioned corrections and controlled replay.
5. Deploy tenant-specific permissions, monitoring, backup and research access.
