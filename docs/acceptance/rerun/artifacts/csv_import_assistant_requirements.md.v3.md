# CSV Import Assistant — Core Functional Specification (Revised)

## 1) Product requirements

### Scope
Administrators can upload a CSV of customer contacts, preview and validate rows, see row-level errors, confirm valid records, and receive an import summary.

### In scope
- CSV upload
- Preview of parsed rows
- Validation of required fields
- Duplicate detection within the uploaded file
- Row-specific validation errors
- Confirmation of valid records before import
- Import summary

### Out of scope
- Production database integration details
- Real customer data
- Authentication
- External SaaS integrations
- Deployment
- Full CRM functionality

### Data assumptions from client
- Columns: `first_name`, `last_name`, `email`, `phone`, `company`
- Required fields: `first_name`, `last_name`
- Contact method rule: a row is valid if it has either:
  - a valid email address, or
  - a valid phone number
- `company` is optional
- Valid phone number rule: a phone value is valid if it contains 10 to 15 digits after removing spaces, hyphens, parentheses, and a leading `+`.

### Functional requirements
1. The system shall allow an administrator to upload a `.csv` file.
2. The system shall parse the file and display a preview of imported rows before import.
3. The system shall validate each row for required fields: `first_name` and `last_name`.
4. The system shall accept a row when at least one contact method is valid: `email` or `phone`.
5. The system shall reject a row only when both contact methods are absent or invalid.
6. The system shall identify duplicate contacts within the uploaded file.
7. The system shall display validation errors at row level for each invalid row.
8. The system shall allow import only of valid rows.
9. The system shall present an import summary showing total rows, valid rows imported, invalid rows rejected, and duplicate rows detected.

## 2) Prioritized user stories

### P1 — Upload and preview CSV
As an administrator, I want to upload a CSV file and preview its contents so that I can confirm the file was read correctly before importing.

### P1 — Validate required name fields
As an administrator, I want the system to validate first and last name in each row so that incomplete contacts are not imported.

### P1 — Validate contact method
As an administrator, I want a row to pass validation when it has either a valid email or a valid phone number so that contacts without email can still be imported when phone is available.

### P1 — Reject rows with no valid contact method
As an administrator, I want rows rejected only when both email and phone are missing or invalid so that only unreachable contacts are blocked.

### P1 — Detect duplicates in file
As an administrator, I want duplicate contacts in the uploaded file identified so that I can avoid importing repeated records.

### P1 — Show row-specific errors
As an administrator, I want each invalid row to display its own errors so that I can correct the exact problem quickly.

### P2 — Confirm valid records and import
As an administrator, I want to confirm valid rows before import so that I can review the final set of records that will be imported.

### P2 — View import summary
As an administrator, I want an import summary after completion so that I can understand what was imported and what was rejected.

## 3) Acceptance criteria

### AC1 — Upload and preview
- Given an administrator selects a CSV file, when upload succeeds, then the system displays a preview of parsed rows.
- The preview shows the mapped columns `first_name`, `last_name`, `email`, `phone`, and `company`.

### AC2 — Required field validation
- Given a row is missing `first_name` or `last_name`, when validation runs, then the row is marked invalid.
- The system displays a row-level error for each missing required field.

### AC3 — Contact method validation
- Given a row has a valid email address, when validation runs, then the row is accepted even if `phone` is blank.
- Given a row has a valid phone number, when validation runs, then the row is accepted even if `email` is blank.
- Given a row has both `email` and `phone` missing or invalid, when validation runs, then the row is rejected.
- The row error message indicates that at least one valid contact method is required.

### AC4 — Email and phone format validation
- Given a row includes an email value that does not match the accepted email format, when validation runs, then email is treated as invalid.
- Given a row includes a phone value that does not match the accepted phone format, when validation runs, then phone is treated as invalid.
- A row is valid if at least one of the two contact methods passes its format validation.
- The accepted phone format is 10 to 15 digits after stripping spaces, hyphens, parentheses, and a leading `+`.

### AC5 — Duplicate detection within file
- Given two or more rows in the uploaded file represent the same contact by the system’s duplicate-matching rule, when validation runs, then the system flags those rows as duplicates.
- Duplicate rows are reported at row level and are not imported.

### AC6 — Row-specific error reporting
- Given a row has multiple validation issues, when validation runs, then all applicable errors are shown for that row.
- Validation errors for one row do not prevent other valid rows from being imported.

### AC7 — Confirm valid records before import
- Given the preview contains valid and invalid rows, when the administrator confirms import, then only valid non-duplicate rows are imported.
- Invalid and duplicate rows remain excluded from import.

### AC8 — Import summary
- Given import completes, then the system shows total rows processed, imported rows, rejected rows, and duplicate rows.
- The summary reflects the final validation results from the uploaded file.

## 4) Assumptions
- Duplicate detection is based on the system’s contact-matching rule for uploaded rows.
- Email validation uses standard email format rules.
- If the CSV contains extra columns, they are ignored unless mapped by the system.

## 5) QA test coverage notes
- Verify rows with blank email but valid phone are accepted.
- Verify rows with invalid email but valid phone are accepted.
- Verify rows with blank/invalid email and blank/invalid phone are rejected.
- Verify missing first or last name still causes rejection regardless of contact method.
- Verify row-level errors identify which contact method failed.
- Verify valid rows continue to import when adjacent rows are rejected.
- Verify summary counts reflect accepted, rejected, and duplicate rows.
- Verify phone validation accepts 10–15 digits after stripping spaces, hyphens, parentheses, and a leading `+`.

## 6) Open questions
- None.
