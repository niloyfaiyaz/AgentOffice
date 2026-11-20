# CSV Import Assistant — Technical Feasibility and Risk Assessment

## Scope and basis
This assessment covers the CSV import workflow only, based on the approved requirements and clarified business rules in the project artifacts. It assumes the workflow is limited to upload, preview, validation, duplicate detection, confirmation, and summary for contact rows in a CSV file.

## Feasibility assessment
The workflow is technically straightforward and feasible without production database integration or external services.

A practical implementation can use a staged pipeline:
1. **Upload** — accept a CSV file and pass it to a parser.
2. **Parse** — read rows into a structured in-memory model, preserving row numbers.
3. **Preview** — render parsed rows before import, including field values and validation status.
4. **Validate** — apply row-level checks:
   - required fields: `first_name`, `last_name`
   - contact method rule: a row is valid if it has a valid email **or** a valid phone number
   - a row is rejected only when both contact methods are missing or invalid
5. **Detect duplicates** — identify duplicates within the uploaded file using the approved rule:
   - compare email case-insensitively when email exists
   - if a row has no email, compare normalized phone number
   - keep the first occurrence and flag later matches
6. **Confirm** — allow import only for rows that are valid and non-duplicate.
7. **Summary** — return counts for accepted, rejected, and duplicate rows, plus a concise status outcome.

This flow aligns well with a synchronous or semi-synchronous UI experience for small-to-moderate files. If file size or parsing latency becomes material, the same workflow can be moved to background processing without changing the business rules.

## Implementation considerations

### Data model
A row-level processing model is the safest approach. Each row should carry:
- source row number
- raw field values
- normalized values used for validation/duplicate checks
- status (`valid`, `invalid`, `duplicate`, `accepted`, `rejected`)
- error list with rule identifiers or human-readable messages

This makes preview, validation, and summary generation deterministic and easy to test.

### Validation sequence
Validation should happen in a predictable order so error messages are stable:
1. CSV structure and required columns
2. required field presence
3. contact method validation (`email` or `phone`)
4. duplicate detection

The order matters because duplicate detection should not mask basic validation failures. A row can accumulate multiple errors, but the final result should be unambiguous for import eligibility.

### Contact-method validation
The revised rule is implementable with standard application logic:
- normalize email to compare format and case-insensitive identity
- normalize phone by stripping formatting characters before validation/comparison
- treat a row as valid if either contact method passes its validation rule
- reject only if both contact methods are absent or invalid

This reduces hard failure rates compared with the earlier email-only rule, but it requires clear messaging so users understand why a row is still rejected.

### Duplicate handling
The duplicate rule needs explicit normalization:
- email comparison should be case-insensitive
- phone normalization should strip formatting characters before comparison
- the first matching row is retained, later matches are flagged

One implementation detail to settle internally is whether a row with both email and phone should be checked against both keys or only the primary key. The requirements imply email is the primary rule when present; the phone rule applies when email is missing. Keeping that precedence explicit will avoid inconsistent duplicate classification.

### Error reporting
Row-specific errors should be displayed alongside the preview, not in a separate generic banner only. This reduces ambiguity and supports quick correction. Errors should include the row number and a concise reason, such as missing first name, invalid email, invalid phone, or duplicate row.

### Confirmation behavior
Confirmation should operate only on the validated preview state, not on a newly re-parsed file, to avoid drift between preview and import. The UI should clearly indicate how many rows will be imported and how many are excluded.

### Summary behavior
The summary should report at least:
- total parsed rows
- valid rows
- invalid rows
- duplicate rows
- imported/accepted rows

This is enough to explain the outcome without expanding into audit logging or downstream persistence details, which are out of scope.

## Major technical risks and mitigations

### 1) CSV parsing edge cases
**Risk:** malformed CSV, inconsistent delimiters, quoted commas, blank rows, or unexpected column order can cause parse failures or incorrect row mapping.

**Mitigation:** use a parser that supports standard CSV escaping and quoted fields; validate headers explicitly; reject files that do not contain the required columns; surface parse errors with row or header context.

### 2) Ambiguous or inconsistent input data
**Risk:** blank emails, malformed phone values, extra whitespace, or mixed-case emails can lead to inconsistent validation or duplicate results.

**Mitigation:** normalize values before rule checks; trim whitespace; validate phone numbers with a clearly defined rule set; allow either valid email or valid phone; display normalization-related assumptions in implementation notes.

### 3) Duplicate detection complexity
**Risk:** the rule changes meaning depending on whether email is present, and rows may partially overlap on email and phone.

**Mitigation:** codify precedence in one validator module; track seen keys separately for email and phone; keep first occurrence deterministically; add targeted test cases for mixed datasets.

### 4) Large file performance
**Risk:** very large CSV files can slow the UI or exhaust memory if fully loaded into the browser or request thread.

**Mitigation:** set an explicit file-size or row-count threshold for the initial version; process sequentially where possible; if needed, move parsing/validation to asynchronous backend processing with progress updates. This is an implementation choice, not a scope expansion.

### 5) Error clarity and user trust
**Risk:** if the system only shows aggregate counts, administrators may not understand why rows failed.

**Mitigation:** preserve row-level error detail and make the preview the primary place where issues are visible; use consistent error wording and include row identifiers.

### 6) Reprocessing mismatch between preview and import
**Risk:** if preview and confirmation re-run validation independently, the accepted set could change unexpectedly due to code drift or file changes.

**Mitigation:** store the parsed/validated import session state until confirmation, or snapshot the validated rows; confirm against the same dataset used for preview.

## Assumptions
- The CSV contains the expected contact columns, including `first_name`, `last_name`, `email`, `phone`, and `company`.
- `company` is optional.
- A row is acceptable when either `email` or `phone` is valid; both are not required.
- Duplicate detection follows the clarified rule captured in the requirements: email match case-insensitively, otherwise normalized phone number.
- The implementation does not need production persistence, authentication, or external integrations.
- The solution is intended for a small B2B SaaS context and not for high-volume batch ingestion.

## Constraints and out of scope
Per the project constraints, this assessment excludes:
- production database integration
- real customer data handling beyond the import workflow
- authentication
- external SaaS integrations
- deployment concerns
- building a complete CRM

## Conclusion
The CSV import workflow remains feasible with standard application-layer parsing, validation, and preview logic. The main implementation risks are input quality, duplicate-rule ambiguity, and file-size handling. These are manageable with explicit normalization rules, row-level state tracking, and clear validation messaging. No blocking technical dependency is apparent within the stated scope.
