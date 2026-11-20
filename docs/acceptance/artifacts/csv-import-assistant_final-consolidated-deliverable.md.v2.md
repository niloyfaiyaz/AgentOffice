# CSV Import Assistant — Final Consolidated Deliverable

## Purpose
Provide a concise, implementation-ready package for the CSV import workflow: upload, preview, validation, duplicate detection, confirmation, and import summary.

## Product requirements
- Administrators can upload a CSV file.
- The system parses the file and shows a preview of all parsed rows.
- The system validates required fields per row.
- A contact is valid if it has a valid email address or a valid phone number.
- Rows are rejected only when both contact methods are absent or invalid.
- The system detects duplicates within the uploaded file.
- The system shows row-specific validation errors.
- Administrators can confirm valid records before import.
- The system shows an import summary after confirmation.

## Workflow
1. Admin uploads CSV.
2. System parses and previews all rows.
3. System validates required fields, contact methods, and duplicates.
4. Invalid and duplicate rows remain visible with row-specific errors.
5. Admin confirms import.
6. System imports only valid, non-duplicate rows into a staged/simulated result.
7. System displays summary counts and rejected-row details.

## Duplicate detection rules
- Compare email case-insensitively after trimming surrounding whitespace.
- If a row has no email, match on normalized phone number.
- Keep the first occurrence and flag later duplicates.
- Duplicate detection applies only within the current uploaded file.

## Prioritized user stories
### P1 — Upload and preview
As an administrator, I want to upload a CSV and see a parsed preview so that I can verify the file before import.

### P1 — Validate rows
As an administrator, I want rows with missing or invalid contact methods flagged so that invalid contacts do not enter the system.

### P1 — Detect duplicates
As an administrator, I want duplicates in the file identified so that I can avoid importing duplicate contacts.

### P1 — Confirm and review summary
As an administrator, I want to confirm valid rows and see an import summary so that I know what was imported and what was rejected.

## Testable acceptance criteria
- Valid CSV upload under supported limits is accepted and parsed.
- Preview shows all parsed rows, including invalid rows.
- Rows missing required fields are marked invalid and the missing fields are named.
- Rows with neither a valid email nor a valid phone number are rejected with a clear contact-method error.
- Rows with a valid email and no phone number are accepted.
- Rows with no email but a valid phone number are accepted.
- Duplicate emails match case-insensitively after trimming whitespace; later duplicates are flagged.
- Rows without email are compared by normalized phone number; later duplicates are flagged.
- Each invalid row shows its own error state and messages.
- On confirmation, only valid non-duplicate rows are included in the staged import result.
- The summary shows total parsed, valid, rejected, duplicates, and imported counts.
- The flow does not require production database integration, external integrations, or real customer data.

## Assumptions
- Import result is staged/simulated in-memory, not persisted.
- Files up to 5 MB or 10,000 rows are supported.
- The preview shows all parsed rows, not only valid ones.

## Risks
- Large files may require streaming or chunked parsing.
- Validation and duplicate logic must be centralized to avoid mismatches between preview and confirmation.
- Summary copy must clearly indicate the result is staged/simulated, not persisted.

## QA status
Approved with no blocking issues.
