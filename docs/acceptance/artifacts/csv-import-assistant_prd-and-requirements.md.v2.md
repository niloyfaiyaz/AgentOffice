# CSV Import Assistant — Product Requirements & Delivery Package

## 1) Product requirements (concise)
**Goal:** Let administrators upload a CSV of customer contacts, review a preview with validation feedback, confirm valid rows, and receive an import summary before any persistent database write.

### In scope
- CSV upload for administrators.
- Parse and preview uploaded rows.
- Validate required fields.
- Contact validation rule:
  - A row is valid if it has a valid email address **or** a valid phone number.
  - Reject a row only when both contact methods are absent or invalid.
- Duplicate detection within the uploaded file:
  - Compare email case-insensitively after trimming surrounding whitespace.
  - If a row has no email, match on normalized phone number.
  - Keep the first occurrence; flag later duplicates.
- Row-specific error messaging.
- Confirm valid records before import.
- Import summary showing counts of total, valid, rejected, duplicates, and imported rows.

### Out of scope
- Production database integration.
- Real customer data handling.
- Authentication/authorization implementation.
- External SaaS integrations.
- Deployment concerns.
- Full CRM functionality.

### Assumptions
- Import outcome is a simulated/staged in-memory import result suitable for a small B2B SaaS product.
- The preview shows all parsed rows, including invalid rows, so admins can review issues before confirming.
- Files up to 5 MB or 10,000 rows are supported.

## 2) End-to-end admin workflow
1. Admin selects and uploads a CSV file.
2. System parses file and displays a row preview.
3. System validates each row:
   - required fields present,
   - at least one valid contact method present (email or phone),
   - duplicate detection within file,
   - row-specific errors shown inline.
4. Valid rows are eligible for confirmation; invalid rows remain visible but are excluded from import.
5. Admin confirms import.
6. System imports only confirmed valid rows into the simulated/staged result.
7. System displays an import summary with counts and error details.

## 3) Prioritized user stories
### P1 — Upload and preview
**As an administrator,** I want to upload a CSV and see a preview of parsed rows **so that** I can verify the file was read correctly before import.
- Scope: file upload, parsing, preview table.
- Boundary: no persistent write at this step.

### P1 — Validate required fields and contact methods
**As an administrator,** I want each row validated for required fields and at least one valid contact method **so that** contacts without usable contact data are rejected.
- Scope: required-field validation, email-or-phone validation.
- Boundary: no manual editing of data in this flow.

### P1 — Detect duplicates within file
**As an administrator,** I want duplicates identified in the uploaded file **so that** I can avoid importing duplicate contacts.
- Scope: email case-insensitive matching; if no email, phone-based matching; first occurrence kept.
- Boundary: duplicates are only checked within the current file.

### P1 — Confirm valid records and import summary
**As an administrator,** I want to confirm valid rows and receive an import summary **so that** I know what was imported and what was rejected.
- Scope: confirmation action, simulated/staged import result, summary counts.
- Boundary: no production database write.

## 4) Testable acceptance criteria
1. **Upload:** Given a valid CSV under the supported limits, when the admin uploads it, then the system accepts the file and parses rows for preview.
2. **Preview:** Given a parsed file, when preview loads, then all parsed rows are displayed, including rows with validation errors.
3. **Required fields:** Given a row missing any required field, when validation runs, then the row is marked invalid and the missing field is named in the error.
4. **Contact validation:** Given a row with neither a valid email nor a valid phone number, when validation runs, then the row is rejected and the error states that at least one valid contact method is required.
5. **Email-only valid:** Given a row with a valid email and no phone number, when validation runs, then the row is accepted as valid.
6. **Phone-only valid:** Given a row with no email but a valid phone number, when validation runs, then the row is accepted as valid.
7. **Duplicate detection:** Given two rows with the same email differing only by case/whitespace, when validation runs, then the first row is kept and the later row is flagged as a duplicate.
8. **Phone fallback duplicates:** Given rows with no email but matching normalized phone numbers, when validation runs, then the first row is kept and the later row is flagged as a duplicate.
9. **Row-specific errors:** Given multiple invalid rows, when validation completes, then each row shows its own error state and messages; errors are not combined into a file-level-only message.
10. **Confirm valid records:** Given valid and invalid rows in the preview, when the admin confirms import, then only valid non-duplicate rows are included in the import result.
11. **Summary:** After confirmation, the system shows counts for total parsed, valid, rejected, duplicates, and imported rows.
12. **Scope boundary:** The workflow completes without requiring production database integration, external integrations, or real customer data.

## 5) Delivery notes / risks
- CSVs near the size limit may require streaming or chunked parsing to keep the UI responsive.
- Validation and duplicate rules need deterministic normalization for email and phone to avoid inconsistent results.
- Since persistence is out of scope, the import summary should clearly indicate the result is staged/simulated.

## 6) Open questions
- None blocking for this package; normalization details for phone formatting beyond basic trimming should be defined during implementation if needed.