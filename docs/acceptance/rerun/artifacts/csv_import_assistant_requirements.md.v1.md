# CSV Import Assistant — Core Functional Specification

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
- Required fields: `first_name`, `last_name`, `email`
- Optional fields: `phone`, `company`

### Functional requirements
1. The system shall allow an administrator to upload a `.csv` file.
2. The system shall parse the file and display a preview of imported rows before import.
3. The system shall validate each row for required fields: `first_name`, `last_name`, `email`.
4. The system shall reject any row with a missing or invalid email address.
5. The system shall identify duplicate contacts within the uploaded file.
6. The system shall display validation errors at row level for each invalid row.
7. The system shall allow import only of valid rows.
8. The system shall present an import summary showing total rows, valid rows imported, invalid rows rejected, and duplicate rows detected.

## 2) Prioritized user stories

### P1 — Upload and preview CSV
As an administrator, I want to upload a CSV file and preview its contents so that I can confirm the file was read correctly before importing.

### P1 — Validate required fields
As an administrator, I want the system to validate required fields in each row so that incomplete contacts are not imported.

### P1 — Reject invalid email rows
As an administrator, I want rows with missing or invalid email addresses rejected so that only usable contact records are imported.

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
- Given a row is missing `first_name`, `last_name`, or `email`, when validation runs, then the row is marked invalid.
- The system displays a row-level error for each missing required field.

### AC3 — Email validation
- Given a row has a missing email, when validation runs, then the row is rejected.
- Given a row has an invalid email format, when validation runs, then the row is rejected.
- The row error message indicates the email is missing or invalid.

### AC4 — Duplicate detection within file
- Given two or more rows in the uploaded file represent the same contact by email, when validation runs, then the system flags those rows as duplicates.
- Duplicate rows are reported at row level and are not imported.

### AC5 — Row-specific error reporting
- Given a row has multiple validation issues, when validation runs, then all applicable errors are shown for that row.
- Validation errors for one row do not prevent other valid rows from being imported.

### AC6 — Confirm valid records before import
- Given the preview contains valid and invalid rows, when the administrator confirms import, then only valid non-duplicate rows are imported.
- Invalid and duplicate rows remain excluded from import.

### AC7 — Import summary
- Given import completes, then the system shows total rows processed, imported rows, rejected rows, and duplicate rows.
- The summary reflects the final validation results from the uploaded file.

## 4) Assumptions
- Duplicate detection is based on email address within the uploaded file.
- Email validation uses standard email format rules.
- If the CSV contains extra columns, they are ignored unless mapped by the system.

## 5) Open questions
- None blocking for this scope; required fields are confirmed as `first_name`, `last_name`, and `email`.
