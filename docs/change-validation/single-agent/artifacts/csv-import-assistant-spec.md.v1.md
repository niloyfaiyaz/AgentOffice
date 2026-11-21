# CSV Import Assistant — Final Consolidated Product Specification

## 1) Concise Product Requirements Document

### Purpose
Define an admin-only CSV import workflow for customer contacts that prevents invalid records from being imported and clearly explains validation results before import.

### Scope
In scope: CSV upload, parsing, preview, validation, duplicate detection within the uploaded file, row-level error display, confirmation of valid records, and import summary.

Out of scope: production database integration, real customer information, authentication, external SaaS integrations, deployment, and broader CRM functionality. Source: R-016.

### Actors
- **Administrator**: uploads a CSV, reviews validation results, confirms import of valid records.

### Required CSV columns
- `first_name` — required
- `last_name` — required
- `email` — required, valid email format required
- `phone` — optional
- `company` — optional

Required-field decision based on R-018.

### End-to-end workflow
1. **Upload CSV**
   - Admin selects a CSV file and submits it for processing.
   - System rejects non-CSV files or unreadable CSV content.
2. **Parse and normalize**
   - System reads header row and data rows.
   - System maps rows to the five supported columns listed above.
   - System trims leading/trailing whitespace from field values before validation.
3. **Preview and validate**
   - System displays imported rows in a preview table.
   - System validates each row for:
     - missing `first_name`
     - missing `last_name`
     - missing `email`
     - invalid email format
     - duplicate contact within uploaded file
   - Validation results are shown per row with explicit error messages.
4. **Confirmation**
   - Admin can confirm import only for rows with no validation errors.
   - Invalid rows are excluded from import.
5. **Import summary**
   - System displays summary counts after confirmation:
     - total rows processed
     - valid rows imported
     - invalid rows excluded
     - duplicate rows excluded

### Validation rules
- A required field is invalid if empty after trimming whitespace.
- Email is valid only if it matches the system’s chosen email-format rule; engineering should implement one consistent validator and test against representative valid/invalid examples.
- Duplicate detection applies only **within the uploaded file**, not against any external system, per R-005 and R-016.
- Duplicate identity should be based on normalized email value because email is required for every imported contact (inference from R-009). Normalization assumption: trim whitespace and compare case-insensitively.

### Error handling requirements
- Errors must be row-specific and visible in preview.
- A row may show multiple errors at once.
- File-level errors (for example unreadable CSV) block preview and import.
- Row-level errors do not block preview; they block import for affected rows only.

### Non-functional notes
- This is a documentation-only scope; no persistence or integration behavior is specified beyond the workflow definition.
- The workflow should be deterministic so QA can reproduce validation outcomes from the same file.

## 2) Prioritized User Stories

### P1
**US-1 Upload CSV**  
As an administrator, I want to upload a CSV file of contacts so that I can start the import workflow.

**US-2 Preview records**  
As an administrator, I want to preview parsed contact rows so that I can inspect the data before import.

**US-3 Validate required fields and email**  
As an administrator, I want the system to validate required fields and email addresses so that invalid contacts are not imported.

**US-4 See row-specific errors**  
As an administrator, I want validation errors shown on the specific rows that caused them so that I can understand what is wrong.

**US-5 Detect duplicates within file**  
As an administrator, I want duplicate contacts in the uploaded file identified before import so that duplicate records are not imported from the same batch.

**US-6 Confirm import of valid rows**  
As an administrator, I want to confirm import only after review so that I retain control over what gets imported.

**US-7 View import summary**  
As an administrator, I want a summary of import results so that I know how many rows were imported versus rejected.

### P2
**US-8 Receive clear file-level failure feedback**  
As an administrator, I want a clear message when the file cannot be processed so that I know the import did not start.

## 3) Testable Acceptance Criteria

### AC-1 Upload
- Given an admin selects a valid CSV file, when upload is submitted, then the system parses the file and proceeds to preview.
- Given a non-CSV or unreadable file, when upload is submitted, then the system shows a file-level error and does not proceed to preview.

### AC-2 Preview
- Given a successfully parsed CSV, when preview is shown, then each uploaded data row appears in the preview with its parsed column values.

### AC-3 Required field validation
- Given a row with blank `first_name`, `last_name`, or `email`, when validation runs, then that row is marked invalid and the missing field error is shown on that row.
- Given whitespace-only values in required fields, when validation runs, then the fields are treated as blank.

### AC-4 Email validation
- Given a row with an invalid email format, when validation runs, then the row is marked invalid and an email-format error is shown on that row.
- Given a row with a valid email format, when all other validations pass, then the email field does not produce an error.

### AC-5 Duplicate detection
- Given two or more rows with the same normalized email in one uploaded file, when validation runs, then each duplicate row is flagged with a duplicate error.

### AC-6 Row-specific error handling
- Given a row that violates multiple validation rules, when preview is shown, then all applicable errors are displayed on that row.

### AC-7 Confirmation and import behavior
- Given preview contains at least one valid row, when the admin confirms import, then only rows without validation errors are imported.
- Given all rows are invalid, when preview is shown, then import confirmation is unavailable or results in zero imported rows; engineering may choose either behavior if applied consistently.

### AC-8 Import summary
- Given an import confirmation has completed, when summary is displayed, then it includes counts for total processed rows, imported valid rows, invalid rows excluded, and duplicate rows excluded.

## 4) Technical Feasibility and Risk Assessment

### Feasibility
This scoped feature is straightforward as a documentation-defined workflow because it requires only file parsing, deterministic validation, preview rendering, and summary reporting. No external dependencies are required within the approved scope. Source: R-016.

### Key assumptions
- Supported columns are exactly: `first_name`, `last_name`, `email`, `phone`, `company`.
- Duplicate detection is based on normalized email within the uploaded file only.
- Valid rows can be imported even if other rows in the same file are invalid.

### Risks and mitigations
- **Ambiguous CSV structure**: Missing or unexpected headers could cause inconsistent parsing.  
  **Mitigation**: require the documented column names and fail fast with a file-level error when parsing/header requirements are not met.
- **Email validation inconsistency**: Overly strict or loose validation can create QA churn.  
  **Mitigation**: choose one documented validator strategy and test with explicit fixtures.
- **Duplicate-rule ambiguity**: Different duplicate keys would change results.  
  **Mitigation**: document email as the duplicate key for this scope.
- **User confusion on partial import**: Users may not realize invalid rows are excluded.  
  **Mitigation**: clearly label valid/invalid rows in preview and repeat counts in the summary.

## 5) QA Review Report

### Coverage check against requirements
- R-002 upload: covered in workflow, US-1, AC-1.
- R-003 preview: covered in workflow, US-2, AC-2.
- R-004 required fields: covered in validation rules, US-3, AC-3.
- R-005 duplicates within file: covered in validation rules, US-5, AC-5.
- R-006 row-specific errors: covered in error handling, US-4, AC-6.
- R-007 confirm valid records: covered in workflow, US-6, AC-7.
- R-008 import summary: covered in workflow, US-7, AC-8.
- R-009 valid email required: covered in validation rules, US-3, AC-4.
- R-018 required fields clarified: reflected in required columns section.

### Gaps / decisions made
- Duplicate logic key is not explicitly stated in requirements; this spec uses normalized email as an implementation assumption because email is mandatory for all imported contacts.
- Header handling is inferred as necessary for implementation readiness; exact UI wording is intentionally unspecified.
- Import confirmation behavior when zero valid rows exist is left flexible, but outcome must prevent invalid imports.

### QA verdict
Within the stated scope, the documentation is sufficiently specific for engineering and QA to implement and test the workflow without further clarification, provided the stated assumptions are accepted.