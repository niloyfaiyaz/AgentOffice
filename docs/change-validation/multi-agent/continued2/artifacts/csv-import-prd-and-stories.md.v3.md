# CSV Import Assistant — PRD, Prioritized User Stories, and Acceptance Criteria

## 1. Purpose
Define a CSV import workflow that lets administrators upload customer contacts, preview parsed records, understand validation results, confirm import of valid records, and receive an import summary. This document covers only the workflow requirements needed for build and QA.

## 2. Facts from client requirements
- The system is a small B2B SaaS platform for administrators importing customer contacts. [R-001]
- The workflow must support CSV upload, record preview, required-field validation, duplicate detection within the uploaded file, row-specific errors, confirmation before import, and an import summary. [R-002 to R-008]
- Contact columns are: `first_name`, `last_name`, `email`, `phone`, `company`. Required fields are `first_name` and `last_name`; `company` is optional. [R-018]
- A contact may be imported if it has either a valid email address or a valid phone number. [R-020]
- Duplicate detection is within the uploaded file only. Duplicates are determined by case-insensitive email match; if a row has no email, match on normalized phone number. Keep the first occurrence and flag later occurrences. [R-005, R-019]
- Out of scope: production DB integration, real customer information, authentication, external SaaS integrations, deployment, and a full CRM. [R-016]

## 3. Assumptions
- “Valid email address” means a syntactically valid email format suitable for application-level validation; domain ownership or mailbox existence is not checked.
- “Valid phone number” means a phone value that:
  - contains only digits, spaces, hyphens (`-`), parentheses, and at most one leading `+`;
  - after normalization by removing spaces, hyphens, parentheses, and a leading `+`, contains only digits;
  - has a normalized length of 10 to 15 digits inclusive.
- “Normalized phone number” for duplicate detection means removing spaces, hyphens, parentheses, and a leading `+` before comparison.
- The workflow imports only rows that are valid and not flagged as duplicates; invalid and duplicate rows are excluded from import.
- Per R-019, duplicate matching uses email when email is present; phone-based matching is used only when email is absent.

## 4. Functional requirements
- **FR-1 Upload CSV:** The system shall allow an administrator to select and upload one CSV file. [R-002]
- **FR-2 Parse and preview:** After upload, the system shall parse the CSV and display a row-level preview using the defined columns when present. [R-003, R-018]
- **FR-3 Required-field validation:** The system shall validate that `first_name` and `last_name` are present for each row. [R-004, R-018]
- **FR-4 Contact-method validation:** The system shall mark a row invalid unless it contains at least one valid contact method: a valid email address or a valid phone number. [R-004, R-020]
- **FR-5 Field-format validation:** The system shall validate email format when an email value is provided and phone format when a phone value is provided, using the phone rule in Section 3. [R-004, R-020]
- **FR-6 Duplicate detection:** The system shall detect duplicates within the uploaded file by keeping the first occurrence and flagging subsequent rows as duplicates, using case-insensitive email match; if email is blank, use normalized phone number. [R-005, R-019]
- **FR-7 Row-specific errors:** The system shall display validation and duplicate errors for each affected row, including the row number and reason. [R-006]
- **FR-8 Confirmation before import:** Before import completes, the system shall present counts of valid and invalid rows and require administrator confirmation to import valid rows. [R-007]
- **FR-9 Import summary:** After confirmation, the system shall display an import summary with counts at minimum for total rows processed, valid rows imported, invalid rows skipped, and duplicate rows skipped. [R-008]

## 5. Prioritized user stories
### P1
1. **US-1 Upload CSV**
   - As an administrator, I want to upload a CSV file so that I can start importing contacts.
2. **US-2 Preview records**
   - As an administrator, I want to preview parsed rows so that I can verify the file was read correctly.
3. **US-3 Validate required fields and contact methods**
   - As an administrator, I want the system to validate required fields and contact details so that only importable contacts proceed.
4. **US-4 Detect duplicates in file**
   - As an administrator, I want duplicate rows identified within the uploaded file so that I do not import repeated contacts.
5. **US-5 See row-specific errors**
   - As an administrator, I want each invalid row to show its specific errors so that I know what must be fixed.
6. **US-6 Confirm import of valid rows**
   - As an administrator, I want to confirm import after review so that I control whether valid rows are imported.
7. **US-7 View import summary**
   - As an administrator, I want a summary after import so that I know what happened.

## 6. Testable acceptance criteria
Traceability uses requirement IDs and user story IDs.

### AC-1 Upload CSV (US-1; R-002)
- Given an administrator selects a CSV file, when upload is submitted, then the system accepts the file and begins parsing it.

### AC-2 Preview records (US-2; R-003, R-018)
- Given a successfully parsed CSV, when parsing completes, then the system displays a preview with row numbers and available values for `first_name`, `last_name`, `email`, `phone`, and `company`.

### AC-3 Required fields (US-3; R-004, R-018)
- Given a previewed row, when `first_name` is blank, then that row is marked invalid with a row-specific error stating `first_name` is required.
- Given a previewed row, when `last_name` is blank, then that row is marked invalid with a row-specific error stating `last_name` is required.

### AC-4 Contact-method presence and validity (US-3; R-004, R-020)
- Given a previewed row, when both `email` and `phone` are blank, then that row is marked invalid with a row-specific error stating that either a valid email or a valid phone number is required.
- Given a previewed row, when `email` is provided in valid format and `phone` is blank or invalid, then the row remains eligible for import unless another validation rule fails.
- Given a previewed row, when `phone` is provided and normalizes to 10 to 15 digits after removing spaces, hyphens, parentheses, and a leading `+`, and the original value contains no other characters, then the row remains eligible for import unless another validation rule fails.
- Given a previewed row, when both `email` and `phone` are provided but both are invalid, then that row is marked invalid with a row-specific error stating that either a valid email or a valid phone number is required.

### AC-5 Field-format validation (US-3; R-004, R-020)
- Given a previewed row, when `email` is provided and is not in valid email format, then the system marks the email field invalid with a row-specific error stating the email is invalid.
- Given a previewed row, when `phone` is provided and contains characters other than digits, spaces, hyphens, parentheses, or a leading `+`, then the system marks the phone field invalid with a row-specific error stating the phone number is invalid.
- Given a previewed row, when `phone` is provided and its normalized value contains fewer than 10 digits or more than 15 digits, then the system marks the phone field invalid with a row-specific error stating the phone number is invalid.
- Given a previewed row, when `phone` is provided as `+1 (415) 555-2671`, then the phone field is valid because it normalizes to `14155552671`.
- Given a previewed row, when `phone` is provided as `555-1234`, then the phone field is invalid because it normalizes to 7 digits.
- Given a previewed row, when `phone` is provided as `415-555-2671 ext 9`, then the phone field is invalid because it contains unsupported characters.

### AC-6 Duplicate detection (US-4; R-005, R-019)
- Given two or more rows with the same email differing only by letter case, when validation runs, then the first occurrence remains eligible and each later occurrence is marked as a duplicate.
- Given rows with blank email and matching normalized phone numbers, when validation runs, then the first occurrence remains eligible and each later occurrence is marked as a duplicate.
- Given a duplicate row, then the duplicate row is not imported.

### AC-7 Row-specific errors (US-5; R-006)
- Given any invalid or duplicate row, when the preview is displayed, then the system shows the row number and each applicable error on that row.

### AC-8 Confirmation before import (US-6; R-007)
- Given validation is complete and at least one valid row exists, when the administrator reviews results, then the system shows counts of valid and invalid rows and requires an explicit confirmation action before importing valid rows.
- Given the administrator does not confirm, then no rows are imported.

### AC-9 Import summary (US-7; R-008)
- Given the administrator confirms import, when import completes, then the system displays an import summary including total rows processed, valid rows imported, invalid rows skipped, and duplicate rows skipped.

## 7. Open questions
- None at this stage. The phone-validation rule needed for implementation and QA is defined in this document.