# CSV Import Assistant — Technical Feasibility & Risk Assessment

## Feasibility summary
The CSV import workflow is technically feasible within the stated scope. A browser-to-server-style import flow can be implemented as: upload → parse → preview/validate → confirm → staged import summary. Because production database integration is out of scope, the “import” step can be modeled as an in-memory or transient staged result, which keeps implementation simpler and avoids persistence concerns.

## Proposed implementation approach

### 1) Upload and parsing
- Accept `.csv` uploads with server-side file size and row-count limits.
- Parse using a streaming or chunked parser to handle files up to the assumed limit (5 MB / 10,000 rows) without loading the full file into memory.
- Normalize header names during parsing to support predictable field mapping.
- Return parsed rows plus parsing errors if the file is malformed.

**Why feasible:** CSV parsing is a standard backend capability; streaming parsing avoids memory spikes and improves responsiveness.

### 2) Preview and validation
- Display all parsed rows in the preview, including invalid rows, with inline row-level status.
- Validate per row before confirmation:
  - required fields present,
  - email present and syntactically valid,
  - duplicate detection within the uploaded file.
- Keep validation results attached to each row so the UI can show exact error messages next to the affected row/field.

**Implementation note:** Validation should be deterministic and separated from UI rendering so the same rules can be reused at confirmation time.

### 3) Duplicate detection rules
- Normalize email by trimming surrounding whitespace and comparing case-insensitively.
- If a row has no email, use normalized phone number as the duplicate key.
- Keep the first occurrence and flag later rows as duplicates.

**Important constraint:** Rows with missing or invalid email must still be rejected per requirements. Phone-based duplicate matching is only for identifying duplicates among rows without email; it does not override the email-required validation rule.

### 4) Confirm and staged import summary
- Confirmation should operate only on rows that are valid and not flagged as duplicates.
- Import result should be staged/simulated in-memory, then summarized with counts such as:
  - total parsed,
  - valid,
  - rejected,
  - duplicates,
  - imported.
- Summary should clearly state that no persistent database write occurred.

## Technical constraints
- **Out of scope boundary:** No production database integration, real customer data, authentication, external SaaS integrations, deployment, or CRM functionality.
- **Performance:** Large files near the limit should be handled with streaming parse and bounded in-memory result objects.
- **UX consistency:** Validation and duplicate logic must run with the same rules during preview and confirmation to avoid mismatched results.
- **Error handling:** Malformed CSV structure, missing headers, and encoding issues must be reported clearly rather than failing silently.

## Key risks and mitigations

1) **Risk: inconsistent duplicate behavior**
- If normalization differs between preview and confirm, users may see different results after confirmation.
- **Mitigation:** Centralize normalization and validation in a single shared rules module; add tests for trimming, case-insensitive email matching, and phone fallback.

2) **Risk: ambiguity between email-required validation and phone-based duplicate fallback**
- The rule set can be misread as allowing rows without email.
- **Mitigation:** Treat missing/invalid email as a hard rejection while still using normalized phone only to detect duplicates among otherwise parsed rows. Document this explicitly in code and tests.

3) **Risk: large-file memory/performance issues**
- Naive parsing can block the UI or exceed memory on large CSVs.
- **Mitigation:** Stream parse, limit file size/row count, and avoid storing unnecessary intermediate copies of rows.

4) **Risk: poor error explainability**
- If errors are aggregated only at file level, admins cannot correct rows efficiently.
- **Mitigation:** Attach field- and row-specific errors to preview data; keep messages concise and actionable.

5) **Risk: staged import misunderstood as real persistence**
- Stakeholders may assume imported contacts were stored permanently.
- **Mitigation:** Label the result as simulated/staged and keep summary language explicit about the out-of-scope persistence boundary.

## Recommended engineering stance
Implement the workflow as a thin import pipeline with shared validation rules, deterministic normalization, and a staged result model. This keeps the feature testable within scope, supports the required preview-and-confirm flow, and avoids introducing database or integration complexity before those capabilities are in scope.
