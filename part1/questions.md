# Questions before kickoff, in priority order

1. **What question must the first cohort answer, and which patients, dates and fields are essential?** This determines what we can leave for later.
2. **Who approves this research use, the cloud location, user access and retention? What is still unsigned?** Without approval, use synthetic samples only.
3. **What outbound/private transfer route is allowed, who can approve it, and when is the next change window?** This can change the critical path immediately.
4. **Which patient and visit identifiers are shared between HIS, oncology and openEHR? How are merges/corrections represented?** Missing links limit safe joins.
5. **Can we obtain the actual HL7 profile and examples of its vendor-specific fields, timestamps and repeated control IDs?** These decide which recovery rules are legitimate.
6. **What FHIR access is available: resource searches, pagination, updates/deletions and read-only credentials?** This decides the daily import and backfill approach.
7. **Can we get the deployed cardiology/diabetes OPT templates, versions and compositions, plus the `ehr_id` crosswalk?** Without these, openEHR mappings cannot be implemented reliably.
8. **How much history and daily volume are needed, how long can sources retain data, and what freshness is acceptable?** These determine batch size and outage buffering.
9. **Which patient examples and mapping gaps will Ruiz use to accept or reject the cohort?** Agreeing this avoids a late disagreement about quality.
10. **How much time can Marta, Ruiz and Diego reserve, and who backs Diego up?** Staffing changes the scope and handover date.
