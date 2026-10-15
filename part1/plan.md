# Delivery plan

I would start with a daily research import and one agreed patient cohort. A possible first cohort is adults with heart failure; Dr. Ruiz and the research sponsor must confirm its definition and required history. The first release covers patients, visits, diagnoses and a short list of measurements. It does not try to interpret every medication or every openEHR template.

## What I would deliver

**Week 2 - prove access and understand the data.** With Marta, test an approved outbound/private transfer from the hospital to GKE. Obtain source samples, identifier definitions, timezones and both openEHR templates. Follow five patients across the sources with Ruiz. Agree the first cohort, required measurements, retention and acceptance examples. Run a small sample through a reader and show one rejected record. No full historical load yet. If access or templates are missing, explain the effect on the schedule now.

**Week 6 - a small pilot that can be checked.** Run daily HL7 and FHIR imports for a limited historical window. Load Person, Visit_occurrence and Condition_occurrence, plus the agreed measurements after checking units. Connect one approved cardiology openEHR template. Count accepted/rejected records, repeat a batch without duplicate results, and recover a failed transfer. Ruiz reviews 20 patient examples, including missing fields and overlapping sources. Medication exposure and other templates remain outside this pilot.

**Week 12 - an accepted cohort and a maintainable service.** Add the approved diabetes template, complete the agreed history and publish the first cohort after clinical/governance approval. Every source record must have a known outcome and unexplained count differences must be resolved. Demonstrate daily freshness within 24 hours, restore/replay and restricted access. Diego runs the process and handles a failed batch using the runbook. Keep unreviewed codes out of cohort criteria; list the exclusions instead of promising complete coverage.

For a network outage, retain the last accepted research snapshot. Keep a bounded local export buffer, sized from measured daily volume, and alert before it fills. Backfill in small batches so daily imports can continue. A mapping change gets a test case and a new version; compare counts before publishing its results.

## Five risks

Probability and impact use 1 (low), 2 (medium), 3 (high). These are starting estimates to revisit after the samples.

| Risk | P x I | Owner | Mitigation and warning sign |
|---|---|---|---|
| **Technical:** repeated/non-shared visit IDs join the wrong interactions across HIS and FHIR. | 2 x 3 = 6 | Integration engineer | Confirm identifier namespaces and use a source-approved crosswalk. Keep visits separate without evidence. Any wrong-patient join in the reviewed examples blocks the affected release. |
| **Operational:** restricted networking and hospital change windows delay exports or exhaust the local buffer. | 2 x 3 = 6 | Marta | Test the route in week 2, reserve a change window and agree buffering/checkpoints. No working sample export by week 2, a growing backlog or buffer above 80% triggers a recovery/replanning call. |
| **Clinical:** a template or vocabulary change silently changes a diagnosis or measurement unit. | 2 x 3 = 6 | Dr. Ruiz | Approve mappings with source examples and pin template versions. New template versions, mismatched units or disagreement on an acceptance example pause that mapping. |
| **Compliance:** raw identifiers or quarantine files are used beyond the approved research purpose. | 2 x 3 = 6 | Hospital DPO | Confirm purpose, region, permissions and retention before real-data use; restrict raw/DLQ access and pseudonymise research outputs. Missing approval or identifiers in a research export blocks release. |
| **Organisational:** Diego becomes the only person who can run a channel without enough practice. | 3 x 2 = 6 | Marta | Protect pairing time, name a backup and keep vendor escalation. Two missed pairing sessions or a failed recovery exercise means reducing scope or extending supported handover. |

## Working with Marta, Ruiz and Diego

| Person | Week 2 | Week 6 | Week 12 |
|---|---|---|---|
| Marta | One 45-minute access/change review. I bring the actual network rules and rollback steps. | Attend a short outage recovery demonstration; vendor engineers handle cloud debugging. | Accept the support/access arrangements and a named backup. |
| Dr. Ruiz | One hour to define the cohort and explain ambiguous source examples. | A prepared 30-minute weekly review of clinical decisions, rather than a list of every bad row. | Approve cohort rules, measurements and known exclusions. |
| Diego | Two hours of pairing a week: run the example and trace a patient. | Own daily pilot runs with support; change one mapping and practise a replay. | Run a full cycle and recover a failed batch from the runbook. |

The runbook contains commands, expected counts, common failure reasons, replay/rollback steps and an escalation contact. I would ask Diego to demonstrate these tasks before transferring ownership. He should maintain the channels independently, with a backup for absence and vendor help for incidents outside his remit.

## Three decisions I would discuss with the customer

These are possible customer requests, not positions already expressed by the hospital.

1. **Customer: "All history and all data types by week 12."** I would explain that clinical review and identity checks take time. My proposal is one cohort, a defined history window, two approved templates and a small measurement list. Preserve other data for a later phase instead of guessing its meaning.
2. **Customer: "Merge visits that happen at nearly the same time."** I would show the sample where source visit classes disagree. My proposal is to merge patients by the approved MRN but keep their source visits separate until the hospital provides an encounter crosswalk. Do not release visit-count analyses before that decision.
3. **Customer: "Diego can own production as soon as the first import works."** I would propose several supported pilot runs and a recovery exercise first. The vendor owns incidents during the first pilot month; Diego takes routine operation gradually, with a named hospital backup at handover.
