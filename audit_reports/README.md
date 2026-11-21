# ATES audit reports

Audit-only assessment dated21 November 2026 (Asia/Karachi). Start with [SRS compliance](SRS_COMPLIANCE_REPORT.md); detailed reports: [functional tests](FUNCTIONAL_TEST_REPORT.md), [algorithms](ALGORITHM_AUDIT.md), [security/database](SECURITY_AND_DATABASE_AUDIT.md), [bugs](BUG_REPORT.md), [roadmap](IMPLEMENTATION_ROADMAP.md).

228 traceability items;38 fully implemented,110 partial,22 missing,44 incorrect,14 not verified. Strict verified-assessment compliance17.76%; primary FR19.51%.107 distinct final pytest cases:80 passed,27 failed. Three compile/build checks passed.4 Critical and14 High grouped issues. Project not production/SRS acceptance ready.

Authoritative evidence: direct_tests.xml/log (79 supplied tests), final_audit_probes.xml/log (28 final probes), frontend_checks.log, runtime_inventory.json, test_results.json, summary.json, requirements.json, bugs.json and source_manifest.json. Audit test sources are test_audit_probes.py/test_extra_probes.py. Partial and initial probe files are superseded diagnostic attempts; do not add their counts to final totals.

Available source SRS was docs/SRS.pdf (62 pages); requested exact filename was absent. SRS_EXTRACTED.txt and srs_page_*.png are source-reading aids. frontend_build is redirected bundle output. No dependency installation or application fixes occurred; original-file integrity verification is in integrity_verification.json. Browser/production/PostgreSQL/load/restore evidence is not claimed.
