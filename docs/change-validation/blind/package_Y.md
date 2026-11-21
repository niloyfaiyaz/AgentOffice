

=== Document 1 ===

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
- `email` — optional unless needed to satisfy contact-method validation; if present, must be valid
- `phone` — optional unless needed to satisfy contact-method validation; if present, must be valid
- `company` — optional

Required-field decision based on R-018. Contact-method rule updated per R-019 and R-020.

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
     - missing both `email` and `phone`
     - invalid email format when `email` is provided
     - invalid phone format when `phone` is provided
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
- A contact is valid for import only if `first_name` and `last_name` are present and at least one contact method is valid: either a valid `email` or a valid `phone`.
- If `email` is populated, it must match the system’s chosen email-format rule; engineering should implement one consistent validator and test against representative valid/invalid examples.
- If `phone` is populated, it must match the system’s chosen phone-format rule; engineering should implement one consistent validator and test against representative valid/invalid examples.
- Duplicate detection applies only **within the uploaded file**, not against any external system, per R-005 and R-016.
- Duplicate identity is not explicitly defined in the requirements once either email or phone can qualify a contact. For this documentation scope, use this assumption: flag rows as duplicates when they share the same normalized valid email, or when email is absent and they share the same normalized valid phone. Normalization assumption: trim whitespace; compare emails case-insensitively; apply one consistent phone normalization strategy.

### Error handling requirements
- Errors must be row-specific and visible in preview.
- A row may show multiple errors at once.
- File-level errors (for example unreadable CSV) block preview and import.
- Row-level errors do not block preview; they block import for affected rows only.
- Rows missing both contact methods must show an explicit row-level error indicating that either a valid email or a valid phone number is required.

### Non-functional notes
- This is a documentation-only scope; no persistence or integration behavior is specified beyond the workflow definition.
- The workflow should be deterministic so [redacted] can reproduce validation outcomes from the same file.

## 2) Prioritized User Stories

### P1
**US-1 Upload CSV**  
As an administrator, I want to upload a CSV file of contacts so that I can start the import workflow.

**US-2 Preview records**  
As an administrator, I want to preview parsed contact rows so that I can inspect the data before import.

**US-3 Validate required fields and contact methods**  
As an administrator, I want the system to validate required fields plus email and phone contact information so that contacts with insufficient or invalid contact data are not imported.

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
- Given a successfully parsed CSV, when preview is shown, then each uploaded data row appears in the preview with its parsed column values and any row-level validation status.

### AC-3 Required field and contact-method validation
- Given a row with blank `first_name` or `last_name`, when validation runs, then that row is marked invalid and the missing field error is shown on that row.
- Given a row with both `email` and `phone` blank, when validation runs, then that row is marked invalid and an error indicates that either a valid email or a valid phone number is required.
- Given whitespace-only values in required fields or contact-method fields, when validation runs, then the fields are treated as blank.

### AC-4 Email and phone validation
- Given a row with a populated but invalid email format and no valid phone, when validation runs, then the row is marked invalid and the relevant contact-method error is shown on that row.
- Given a row with a populated but invalid phone format and no valid email, when validation runs, then the row is marked invalid and the relevant contact-method error is shown on that row.
- Given a row with a valid email and blank phone, when all other validations pass, then the row is valid.
- Given a row with a valid phone and blank email, when all other validations pass, then the row is valid.
- Given a row with both email and phone populated, when one is invalid but the other is valid, then the row remains valid but the invalid populated field is still shown as an error only if engineering chooses strict field-level validation for provided optional data; for this spec, assume populated contact fields must be valid.

### AC-5 Duplicate detection
- Given two or more rows with the same normalized valid email in one uploaded file, when validation runs, then the duplicate rows are flagged with a duplicate error.
- Given rows without valid email but with the same normalized valid phone in one uploaded file, when validation runs, then the duplicate rows are flagged with a duplicate error.

### AC-6 Row-specific error handling
- Given a row that violates multiple validation rules, when preview is shown, then all applicable errors are displayed on that row.

### AC-7 Confirmation and import behavior
- Given preview contains at least one valid row, when the admin confirms import, then only rows without validation errors are imported.
- Given all rows are invalid, when preview is shown, then import confirmation is unavailable or results in zero imported rows; engineering may choose either behavior if applied consistently.
- Given preview contains a mix of valid and invalid rows, when confirmation is shown, then the UI clearly indicates how many valid records will be imported.

### AC-8 Import summary
- Given an import confirmation has completed, when summary is displayed, then it includes counts for total processed rows, imported valid rows, invalid rows excluded, and duplicate rows excluded.
- Given some rows were excluded for missing or invalid contact methods, when summary is displayed, then those rows are included in the invalid rows excluded count.

## 4) Technical Feasibility and Risk Assessment

### Feasibility
This scoped feature is straightforward as a documentation-defined workflow because it requires only file parsing, deterministic validation, preview rendering, and summary reporting. No external dependencies are required within the approved scope. Source: R-016.

### Key assumptions
- Supported columns are exactly: `first_name`, `last_name`, `email`, `phone`, `company`.
- Valid rows can be imported even if other rows in the same file are invalid.
- Because R-019 changed the required contact rule, duplicate detection in this spec uses normalized email when available, otherwise normalized phone, as a practical documentation assumption.
- Populated contact-method fields are validated individually; a row is importable when at least one of them is valid and all other required validations pass.

### Risks and mitigations
- **Ambiguous CSV structure**: Missing or unexpected headers could cause inconsistent parsing.  
  **Mitigation**: require the documented column names and fail fast with a file-level error when parsing/header requirements are not met.
- **Email/phone validation inconsistency**: Overly strict or loose validation can create [redacted] churn.  
  **Mitigation**: choose one documented validator strategy for each field and test with explicit fixtures.
- **Duplicate-rule ambiguity**: Different duplicate keys would change results, especially when one row has email and another has phone only.  
  **Mitigation**: document the assumed duplicate-key rule for this scope and keep it deterministic.
- **User confusion on partial import**: Users may not realize invalid rows are excluded.  
  **Mitigation**: clearly label valid/invalid rows in preview, state that either valid email or valid phone is sufficient, and repeat counts in the summary.

## 5) [redacted]

### Coverage check against requirements
- R-002 upload: covered in workflow, US-1, AC-1.
- R-003 preview: covered in workflow, US-2, AC-2.
- R-004 required fields: covered in validation rules, US-3, AC-3.
- R-005 duplicates within file: covered in validation rules, US-5, AC-5.
- R-006 row-specific errors: covered in error handling, US-4, AC-6.
- R-007 confirm valid records: covered in workflow, US-6, AC-7.
- R-008 import summary: covered in workflow, US-7, AC-8.
- R-018 required fields clarified: reflected in required columns section.
- R-019 / R-020 either email or phone allowed: covered in required columns, validation rules, workflow, US-3, AC-3, and AC-4.

### Gaps / decisions made
- Duplicate logic key is not explicitly stated in requirements once contacts may qualify by either email or phone; this spec uses normalized valid email, otherwise normalized valid phone, as an implementation assumption.
- Header handling is inferred as necessary for implementation readiness; exact UI wording is intentionally unspecified.
- Import confirmation behavior when zero valid rows exist is left flexible, but outcome must prevent invalid imports.

### [redacted] verdict
Within the stated scope, the documentation is sufficiently specific for engineering and [redacted] to implement and test the workflow without further clarification, provided the stated assumptions are accepted.