

=== Document 1 ===

# CSV Import Assistant — PRD, Prioritized User Stories, and Acceptance Criteria

## 1. Purpose
Define a CSV import workflow that lets administrators upload customer contacts, preview parsed records, understand validation results, confirm import of valid records, and receive an import summary. This document covers only the workflow requirements needed for build and [redacted].

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
- None at this stage. The phone-validation rule needed for implementation and [redacted] is defined in this document.

=== Document 2 ===

# CSV Import Assistant — Technical Feasibility and Risk Assessment

## 1. Feasibility conclusion
The revised feature remains feasible as a self-contained workflow without production integrations. An implementation can parse one uploaded CSV, validate rows in memory, detect in-file duplicates, present row-level results in a preview UI, and import only rows that are valid and not duplicates into a temporary in-app store or stub repository. This still fits scope because it avoids production database, authentication, deployment, and external service dependencies. [R-002 to R-008, R-016, R-020]

## 2. Recommended workflow
### Components
- **Upload UI**: accepts one CSV file and submits it for processing.
- **CSV processing service**: parses rows, normalizes values, validates fields and contact methods, detects duplicates, and returns row results plus summary counts.
- **Preview/confirmation UI**: displays parsed rows, row-specific errors, totals, and a confirm action.
- **Import executor**: on confirm, imports only rows marked valid into a non-production in-memory store or stub repository, then returns an import summary.

### Data flow
1. Admin uploads CSV. [R-002]
2. Parser reads the header row and maps supported columns: `first_name`, `last_name`, `email`, `phone`, `company`. [R-018]
3. For each row, trim whitespace and build a row result object with source row number, parsed field values, normalized email, normalized phone, errors array, duplicate flag, and final status.
4. Validate required fields: `first_name` and `last_name` must be non-blank after trim. [R-004, R-018]
5. Validate contact methods:
   - if `email` is provided, check email syntax
   - if `phone` is provided, check phone syntax and normalize it
   - if neither a valid email nor a valid phone is present, mark the row invalid [R-004, R-020]
6. Detect in-file duplicates after normalization:
   - if email is present, compare case-insensitive normalized email
   - if email is blank, compare normalized phone number
   - keep first occurrence and flag later matching rows as duplicates [R-019]
7. Return preview data with row-level errors and counts for total, valid, invalid, and duplicate rows. [R-003, R-006, R-008]
8. On confirmation, import only rows with final status `valid`. [R-007]
9. Return final summary. [R-008]

## 3. Validation and duplicate logic
### Validation rules
- `first_name`: required, non-blank after trim.
- `last_name`: required, non-blank after trim.
- `company`: optional.
- `email`: optional as a field, but if provided it should be syntactically valid to count as a valid contact method.
- `phone`: optional as a field, but if provided it should satisfy the explicit phone rule below to count as a valid contact method.
- **Import eligibility rule**: a row is importable only if it has `first_name`, `last_name`, and at least one valid contact method: valid email or valid phone. [R-018, R-020]

### Explicit phone validation and normalization rule
Use one deterministic phone rule for both implementation and [redacted]:
- Trim leading and trailing whitespace.
- Allow only these characters in the raw phone input: digits `0-9`, spaces, hyphens `-`, parentheses `(` `)`, and an optional leading `+`.
- Reject the value if `+` appears anywhere except the first character.
- Normalize by removing spaces, hyphens, parentheses, and a leading `+`.
- After normalization, the phone must contain digits only and be **10 to 15 digits inclusive**.
- Any phone that fails the allowed-character check or digit-length check is invalid.

Examples:
- `+1 (415) 555-2671` → normalized `14155552671` → valid
- `415-555-2671` → normalized `4155552671` → valid
- `555 1212` → normalized `5551212` → invalid (too short)
- `12-34` → normalized `1234` → invalid (too short)
- `415.555.2671` → invalid (periods not allowed)
- `ext 123` or `415-555-2671 x12` → invalid (extensions not supported in scope)

This rule is intentionally minimal and format-only. It does not verify country codes, carrier validity, or real-world reachability. [R-016]

### Duplicate algorithm
Use hash maps for O(n) duplicate detection:
- `seenEmails[lowercase(trim(email))] = firstRowNumber`
- `seenPhones[normalizedPhone] = firstRowNumber` only when email is blank

If a later row matches an existing key, mark it duplicate and attach an error such as `Duplicate of row 4 by email`.

### Important implementation note
Per R-019, duplicate matching uses email whenever email is present, even if phone is also present. Phone-based matching applies only when email is absent. This means the validation pipeline should separate:
- **contact-method eligibility**: email or phone may qualify the row for import
- **duplicate key selection**: email has priority; phone is only the fallback when email is blank

This rule is feasible, but it should be implemented explicitly to avoid accidental duplicate checks across both keys for the same row.

## 4. Suggested interfaces
### Processing response shape
A simple JSON contract is sufficient:
- `rows[]`: `{ row_number, first_name, last_name, email, phone, company, errors[], status }`
- `summary`: `{ total_rows, valid_rows, invalid_rows, duplicate_rows }`
- `can_import`: boolean

Useful optional fields for UI/debugging:
- `normalized_email`
- `normalized_phone`
- `duplicate_of_row`
- `duplicate_key_type` (`email` or `phone`)

### Internal modules
- `parseCsv(file) -> rawRows`
- `normalizeRow(rawRow) -> normalizedRow`
- `validateRow(row) -> errors[]`
- `selectDuplicateKey(row) -> { keyType, keyValue } | null`
- `detectDuplicates(rows) -> rowsWithDuplicateFlags`
- `buildSummary(rows) -> summary`
- `executeImport(validRows) -> importSummary`

This decomposition keeps validation rules isolated and testable.

## 5. Technology approach
Feasible options:
- **Server-side processing** in the app backend: simpler control over parsing and consistent validation.
- **Client-side preview plus backend confirm**: also feasible, but adds mismatch risk unless validation logic is shared.

Recommended: centralize parsing, normalization, validation, duplicate detection, and import eligibility in one backend service or shared library so the preview and import confirmation always use the same rules.

## 6. Risks and edge cases
### Key technical risks
- **CSV format variability**: quoted commas, blank lines, inconsistent headers, and encoding issues can break naive parsers. Mitigation: use a proven CSV parser library.
- **Header mismatch**: missing or misspelled expected columns may produce confusing previews. Mitigation: validate expected headers and return clear file-level errors.
- **Validation inconsistency**: preview and import could disagree if contact-method logic is duplicated in different layers. Mitigation: reuse one validation pipeline and persist row results through confirmation.
- **Phone rule implementation drift**: phone-only imports now depend on the specified phone rule, so inconsistent implementations could cause defects. Mitigation: reuse one normalization/validation function everywhere and cover boundary cases with unit tests.
- **Rule interaction risk**: a row can be valid for import by phone while duplicate matching still prefers email if email is present. Mitigation: implement duplicate-key selection as a separate step with unit tests for mixed email/phone cases.

### Edge cases to handle
- Empty file
- File with header only and no data rows
- Rows with multiple errors
- Rows where email is invalid but phone is valid
- Rows where phone is invalid but email is valid
- Rows where both email and phone are present but both invalid
- Duplicate rows that are otherwise valid
- Mixed-case emails
- Extra unsupported columns
- Leading/trailing whitespace in fields
- Repeated blank-email rows with same phone
- Phone inputs with unsupported punctuation or extensions
- Phone inputs at the 10-digit and 15-digit validity boundaries

## 7. Assumptions and constraints
- No production database integration; import may target an in-memory store, mock repository, or test-only persistence layer. [R-016]
- No external email verification, SMS verification, or contact enrichment. Validation is format-only. [R-016]
- Duplicate detection is only within the uploaded file, not against existing contacts. [R-005, R-016]
- Scope does not require async background processing, large-file optimization, or bulk performance tuning.
- Phone normalization for duplicate checks is the same normalization used by phone validation: remove spaces, hyphens, parentheses, and a leading `+`, then compare the resulting digit string.
- The specified phone rule is an implementation design decision in this technical deliverable to satisfy R-017 and support testable execution of R-020.

## 8. Implementation recommendation
Build a single deterministic validation pipeline that produces row results used by both preview and import confirmation. Model contact-method validation and duplicate-key selection as separate functions so R-020 and R-019 are both enforced correctly. With the explicit phone-validation and normalization rule above, this approach is low complexity, testable, and sufficient for the scoped MVP.


=== Document 3 ===

# Final Consolidated Delivery — CSV Import Assistant

## Delivered package
This project delivered the concise planning package required to enable engineering to build and test a CSV import preview-and-validation workflow for customer contacts within the approved scope.

### Deliverables completed
1. **`csv-import-prd-and-stories.md` v3**
   - Concise PRD for the CSV Import Assistant.
   - Prioritized user stories.
   - Traceable, testable acceptance criteria.
   - Defined business rules for required fields, import eligibility, duplicate handling, row-specific errors, confirmation, and summary.

2. **`csv-import-technical-feasibility-and-risks.md` v4**
   - Technical feasibility conclusion.
   - Recommended component/workflow design.
   - Explicit validation, normalization, and duplicate-detection logic.
   - Suggested interfaces, module decomposition, implementation approach, risks, and edge cases.

3. **`[redacted] (run 1)` v3**
   - [redacted] history and final verdict.
   - Recorded findings F-001, F-002, and F-003.
   - Final re-review verdict: **pass**.

## What the package specifies
Across the final deliverables, the package defines a workflow that:
- allows an administrator to upload one CSV file;
- parses and previews rows for `first_name`, `last_name`, `email`, `phone`, and `company`;
- validates required fields (`first_name`, `last_name`);
- allows import when a row has at least one valid contact method: valid email or valid phone;
- detects in-file duplicates by case-insensitive email, or by normalized phone when email is blank;
- keeps the first duplicate occurrence and flags later rows;
- shows row-specific validation and duplicate errors;
- requires explicit confirmation before import of valid rows; and
- returns an import summary with counts.

## Teammate contributions
### [redacted] — [redacted]
Delivered the business-facing requirements package in **`csv-import-prd-and-stories.md` v3**.
- Drafted the concise PRD.
- Wrote prioritized user stories.
- Produced testable acceptance criteria traceable to requirements.
- Reworked the document to reflect R-020, so rows are importable with either valid email or valid phone.
- Resolved [redacted] finding F-001 by defining a concrete phone validation and normalization rule and updating ACs accordingly.

### [redacted] — [redacted]
Delivered the technical package in **`csv-import-technical-feasibility-and-risks.md` v4**.
- Assessed feasibility within scope constraints.
- Defined the recommended processing flow, validation pipeline, duplicate algorithm, interfaces, and modules.
- Reworked the technical design for R-020.
- Resolved [redacted] findings F-002 and F-003 by explicitly specifying the phone rule in the technical design and aligning it with the PRD.

### [redacted] — [redacted]
Delivered [redacted] outcomes in **`[redacted] (run 1)` v3**.
- Initial review found major gaps around phone-validation ambiguity.
- Re-review confirmed F-001 resolved in the PRD.
- Subsequent re-review identified cross-document inconsistency on phone length.
- Final re-review passed after the technical deliverable aligned to the PRD.

## Assumptions in the final package
The final package includes these explicit assumptions/design decisions:
- Email validation is syntax-only; no mailbox, domain, or ownership verification is included.
- Phone validation is format-only.
- A valid phone number:
  - may contain digits, spaces, hyphens, parentheses, and at most one leading `+`;
  - is normalized by removing spaces, hyphens, parentheses, and a leading `+`;
  - must contain **10 to 15 digits inclusive** after normalization.
- Duplicate detection is only within the uploaded file, not against an existing database.
- Duplicate key priority is email first; phone is used only when email is blank.
- Import targets a non-production stub/in-memory store, not a production database.
- Out-of-scope items remain excluded: authentication, deployment, external integrations, real customer data, and a full CRM.

## Open questions
- **No open questions remain in the final package.**

## [redacted] findings still open
- **None.**
- [redacted] findings **F-001**, **F-002**, and **F-003** are recorded as **resolved** in `[redacted] (run 1)` v3, and the final verdict is **pass**.

## Verified vs unverified claims

### Verified by tools/deliverables in this task
The following claims are verified by artifacts read in this conversation:
- **The PRD/stories deliverable exists as `csv-import-prd-and-stories.md` v3.** Verified by reading that artifact.
- **The technical feasibility deliverable exists as `csv-import-technical-feasibility-and-risks.md` v4.** Verified by reading that artifact.
- **The [redacted] report exists as `[redacted] (run 1)` v3 and records a final verdict of pass.** Verified by reading that artifact.
- **The final PRD defines the phone rule as 10–15 digits after normalization.** Verified in `csv-import-prd-and-stories.md` v3.
- **The final technical deliverable defines the same phone rule as 10–15 digits after normalization.** Verified in `csv-import-technical-feasibility-and-risks.md` v4.
- **The [redacted] report records findings F-001, F-002, and F-003 as resolved.** Verified in `[redacted] (run 1)` v3.
- **The final package contains no open questions in the PRD.** Verified in Section 7 of `csv-import-prd-and-stories.md` v3.

### Unverified or not tool-tested
The following claims are not verified by implementation tests in this conversation:
- **That the workflow has been implemented.** No build artifact or running system was reviewed.
- **That the validation logic works in software exactly as specified.** No executable tests were run here.
- **That an engineering team can build the feature without any further clarification in practice.** This is supported by document content and [redacted] opinion, but not independently proven by implementation.
- **That the recommended architecture or algorithms are optimal.** They are design recommendations, not benchmarked results.
- **That all edge cases are fully covered by future implementation tests.** The documents list edge cases, but no test execution evidence exists here.

## Consolidated status
The approved scope deliverables for the CSV Import Assistant are complete at the document level:
- business requirements package delivered;
- technical feasibility/risk package delivered;
- [redacted] delivered with final pass;
- earlier ambiguities and cross-document conflicts around phone validation were resolved.

This final package is ready for engineering handoff as a concise planning set, subject to the usual limitation that no software implementation or runtime testing was performed in this task.