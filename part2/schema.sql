-- The requested OMOP tables, with the fields used in this exercise.
-- This is a small subset, not a complete CDM database for OHDSI tools.
PRAGMA foreign_keys = ON;
CREATE TABLE person (
    person_id INTEGER PRIMARY KEY,
    gender_concept_id INTEGER NOT NULL,
    year_of_birth INTEGER NOT NULL,
    month_of_birth INTEGER,
    day_of_birth INTEGER,
    race_concept_id INTEGER NOT NULL DEFAULT 0,
    ethnicity_concept_id INTEGER NOT NULL DEFAULT 0,
    person_source_value TEXT NOT NULL UNIQUE
);
CREATE TABLE visit_occurrence (
    visit_occurrence_id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(person_id),
    visit_concept_id INTEGER NOT NULL,
    visit_start_date TEXT NOT NULL,
    visit_start_datetime TEXT,
    visit_end_date TEXT NOT NULL,
    visit_end_datetime TEXT,
    visit_type_concept_id INTEGER NOT NULL,
    visit_source_value TEXT,
    CHECK (visit_end_date >= visit_start_date)
);
CREATE TABLE condition_occurrence (
    condition_occurrence_id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(person_id),
    condition_concept_id INTEGER NOT NULL,
    condition_start_date TEXT NOT NULL,
    condition_type_concept_id INTEGER NOT NULL,
    visit_occurrence_id INTEGER REFERENCES visit_occurrence(visit_occurrence_id),
    condition_source_value TEXT,
    condition_source_concept_id INTEGER DEFAULT 0
);
