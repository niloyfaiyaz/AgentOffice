# CSV Import Assistant — Technical Feasibility and Risk Assessment

## 1. Feasibility conclusion
The scoped feature is feasible as a self-contained application workflow without production integrations. A straightforward implementation can parse one uploaded CSV, validate rows in memory, detect in-file duplicates, present row-level results in a preview UI, and simulate/import only valid rows into a temporary in-app store or test fixture. This fits the stated scope because it does not require database, auth, or external service dependencies. [R-002 to R-009, R-016]

## 2. Recommended workflow
### Components
- **Upload UI**: accepts one CSV file and submits it for processing.
- **CSV processing service**: parses rows, normalizes values, validates fields, detects duplicates, and returns row results plus summary counts.
- **Preview/confirmation UI**: displays parsed rows, row-specific errors, totals, and a confirm action.
- **Import executor**: on confirm, imports only rows marked valid into a non-production in-memory store or stub repository, then returns an import summary.

### Data flow
1. Admin uploads CSV. [R-002]
2. Server or client-side parser reads header row and maps supported columns: `first_name`, `last_name`, `email`, `phone`, `company`. [R-018]
3. For each row, trim whitespace and build a row result object with:
   - source row number
   - parsed field values
   - normalized email and phone
   - validation errors array
   - duplicate flag
   - final status: `valid`, `invalid`, or `duplicate`
4. Validate required fields: `first_name`, `last_name`, `email`. [R-004, R-018]
5. Validate email syntax for every row. Rows without valid email remain invalid and cannot be imported. [R-009]
6. Detect in-file duplicates:
   - if email is present, compare case-insensitive normalized email
   - if email is blank, compare normalized phone number
   - keep first occurrence, flag later occurrences as duplicate [R-019]
7. Return preview data with row-level errors and counts for total, valid, invalid, and duplicate rows. [R-003, R-006, R-008]
8. On confirmation, import only rows with status `valid`. [R-007]
9. Return final summary. [R-008]

## 3. Validation and duplicate logic
### Validation rules
- `first_name`: required, non-blank after trim.
- `last_name`: required, non-blank after trim.
- `email`: required, non-blank after trim, syntactically valid.
- `company`: optional.
- `phone`: optional; used only for fallback duplicate matching when email is blank. This is based on Bea’s documented assumption aligning R-009 with R-019.

### Duplicate algorithm
Use hash maps for O(n) duplicate detection:
- `seenEmails[lowercase(trim(email))] = firstRowNumber`
- `seenPhones[normalizedPhone] = firstRowNumber` only when email is blank

If a later row matches an existing key, mark it duplicate and attach an error such as `Duplicate of row 4 by email`.

## 4. Suggested interfaces
### Processing response shape
A simple JSON contract is sufficient:
- `rows[]`: `{ row_number, first_name, last_name, email, phone, company, errors[], status }`
- `summary`: `{ total_rows, valid_rows, invalid_rows, duplicate_rows }`
- `can_import`: boolean

### Internal modules
- `parseCsv(file) -> rawRows`
- `normalizeRow(rawRow) -> normalizedRow`
- `validateRow(row) -> errors[]`
- `detectDuplicates(rows) -> rowsWithDuplicateFlags`
- `buildSummary(rows) -> summary`
- `executeImport(validRows) -> importSummary`

This decomposition is simple, testable, and supports unit testing without real integrations.

## 5. Technology approach
Feasible options:
- **Server-side processing** in the app backend: simpler control over parsing and consistent validation.
- **Client-side preview plus backend confirm**: also feasible, but adds duplication unless validation logic is shared.

Recommended: keep parsing and validation in one backend service or shared library to avoid mismatch between preview and import decisions.

## 6. Risks and edge cases
### Key technical risks
- **CSV format variability**: quoted commas, blank lines, inconsistent headers, and encoding issues can break naive parsers. Mitigation: use a proven CSV parser library rather than custom splitting.
- **Header mismatch**: missing or misspelled expected columns may produce confusing previews. Mitigation: explicitly validate required headers and return clear file-level errors.
- **Row numbering confusion**: header row and blank lines can shift displayed row numbers. Mitigation: define row numbering based on original CSV line numbers after header.
- **Validation inconsistency**: different logic between preview and import could import rows previously shown invalid. Mitigation: reuse the same validation result for confirmation/import.
- **Phone normalization ambiguity**: fallback duplicate detection on phone is only relevant when email is blank; different normalization rules could over- or under-match. Mitigation: document a minimal normalization rule and keep it narrow.

### Edge cases to handle
- Empty file
- File with header only and no data rows
- Rows with multiple errors
- Duplicate rows that are also missing required fields
- Mixed-case emails
- Extra unsupported columns
- Leading/trailing whitespace in fields
- Repeated blank-email rows with same phone

## 7. Assumptions and constraints
- No production database integration; import may target an in-memory store, mock repository, or test-only persistence layer. [R-016]
- No external email verification or contact enrichment. Email validation is format-only. [R-016]
- Duplicate detection is only within the uploaded file, not against existing contacts. [R-005, R-016]
- Scope does not require async background processing, large-file optimization, or bulk performance tuning; if desired later, those should be separately scoped.

## 8. Implementation recommendation
Build a single validation pipeline that produces deterministic row results used by both preview and import confirmation. Prioritize correctness of parsing, explicit error reporting, and traceable summary counts over advanced UX or integrations. This is sufficient for the scoped MVP and should be low risk if implemented with a tested CSV parser and clear row result contracts.