# CSV Import Assistant — PRD, User Stories, Acceptance Criteria

## 1) Concise PRD

### Goal
Enable administrators to upload a CSV of customer contacts, preview and validate the rows, reject invalid records, and confirm only valid records for import.

### In Scope
- CSV upload for administrators
- Preview of imported records before import
- Validation of required fields: first_name, last_name, and contact method
- Contact method validation rules:
  - email is optional if phone is present and valid
  - a row is valid when it has either a valid email or a valid phone number
  - reject a row only when both contact methods are absent or invalid
- Duplicate detection within the uploaded file:
  - Primary duplicate key: email, case-insensitive
  - If a row has no email, duplicate matching uses normalized phone number
  - Keep the first occurrence; flag subsequent duplicates
- Row-specific validation errors
- Confirmation of valid records before import
- Import summary showing counts/results

### Out of Scope
Per R-017: production database integration, real customer information, authentication, external SaaS integrations, deployment, complete CRM. Also keep the solution concise and limited to the CSV import workflow.

### Workflow Summary
1. Administrator uploads a CSV file.
2. System parses and previews the rows.
3. System validates required fields, contact method rules, and duplicates.
4. System shows row-specific errors and highlights valid vs invalid rows.
5. Administrator confirms import for valid rows.
6. System shows an import summary.

### Business Rules
- first_name and last_name are required.
- Each row must have at least one valid contact method: email or phone.
- Rows are rejected only if both contact methods are absent or invalid.
- Duplicate rows are not imported; the first matching row is kept.
- Duplicates are determined by case-insensitive email match, or by normalized phone number when email is missing.

## 2) Prioritized User Stories

### P1 — CSV upload
**As an administrator, I want to upload a CSV file so that I can begin the contact import workflow.**

### P1 — Preview uploaded records
**As an administrator, I want to preview parsed CSV rows so that I can review the data before importing.**

### P1 — Validate required fields and contact method
**As an administrator, I want the system to validate required fields and either email or phone so that only contacts with at least one valid contact method are accepted.**

### P1 — Detect duplicates in file
**As an administrator, I want duplicate rows identified within the uploaded CSV so that I do not import the same contact twice.**

### P1 — See row-specific errors
**As an administrator, I want validation errors shown by row so that I can quickly correct the exact records that failed.**

### P1 — Confirm valid records
**As an administrator, I want to confirm only valid rows for import so that rejected rows are excluded.**

### P2 — Review import summary
**As an administrator, I want an import summary so that I can confirm how many rows were accepted, rejected, and imported.**

## 3) Testable Acceptance Criteria

### AC1 — CSV upload
- Given an administrator selects a file with a .csv extension, when the upload is submitted, then the system accepts the file for parsing.
- Given a non-CSV file is submitted, then the system rejects it and shows an upload error.

### AC2 — Preview imported records
- Given a valid CSV file, when parsing succeeds, then the system displays a preview of the imported rows before import.
- The preview must include row numbers and the contact fields present in the CSV.

### AC3 — Validate required fields
- Given a row missing first_name or last_name, when validation runs, then the row is marked invalid.
- Given a row with first_name and last_name present, when validation runs, then the row may be marked valid if the contact method rule and any other rule pass.

### AC4 — Validate contact method rule
- Given a row with a missing or invalid email and a valid phone number, when validation runs, then the row is accepted unless another rule fails.
- Given a row with a valid email and no phone number, when validation runs, then the row is accepted unless another rule fails.
- Given a row with no email and an invalid or missing phone number, when validation runs, then the row is rejected.
- Given a row with an invalid email and an invalid or missing phone number, when validation runs, then the row is rejected.
- Given a row has no valid contact method, then the system rejects the row because both contact methods are absent or invalid.

### AC5 — Detect duplicates
- Given two or more rows with the same email ignoring case, when validation runs, then the first row is kept and later matching rows are flagged as duplicates.
- Given rows without email but with the same normalized phone number, when validation runs, then the first row is kept and later matching rows are flagged as duplicates.
- Duplicate rows are not eligible for import.

### AC6 — Row-specific validation errors
- Given one or more invalid rows, when validation completes, then the system shows an error message for each affected row.
- Error messages must identify the specific row and the specific failing rule(s).

### AC7 — Confirm valid records before import
- Given the preview contains valid and invalid rows, when the administrator confirms import, then only valid non-duplicate rows are imported.
- Invalid and duplicate rows remain excluded from import.

### AC8 — Import summary
- Given an import has completed, when the result is displayed, then the system shows counts for accepted rows, rejected rows, and duplicates.
- The summary must reflect the final import outcome for the uploaded file.

## 4) QA Test Coverage
- Test that a row with first_name and last_name but no email is accepted when phone is valid.
- Test that a row with a valid email and missing phone is accepted.
- Test that a row with missing email and invalid phone is rejected.
- Test that a row with invalid email and valid phone is accepted.
- Test that a row with both email and phone missing is rejected.
- Test that duplicate detection still keeps the first row when email matches case-insensitively.
- Test that duplicate detection still keeps the first row when email is absent and phone matches after normalization.
- Test that row-level error messages identify the failing contact-method rule.

## 5) Assumptions
- The CSV contains columns first_name, last_name, email, phone, and company.
- company is optional.
- “Normalized phone number” means phone values are compared after removing formatting characters such as spaces, dashes, and parentheses.
- A phone number is considered valid according to the product’s existing phone validation rule; the exact format is not further specified in the client request.
- The import summary is shown after confirmation and completion of the import action.

## 6) Open Questions
- None blocking for this build-ready scope; the client change clarified the required contact method behavior.
