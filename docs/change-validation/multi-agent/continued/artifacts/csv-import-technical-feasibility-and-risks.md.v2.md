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
   - if `phone` is provided, check phone syntax
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
- `phone`: optional as a field, but if provided it should be syntactically valid to count as a valid contact method.
- **Import eligibility rule**: a row is importable only if it has `first_name`, `last_name`, and at least one valid contact method: valid email or valid phone. [R-018, R-020]

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
- **Phone validation ambiguity**: R-020 allows phone-only imports, but the exact phone validity rule is not specified in the requirements or PRD v2. Mitigation: define and document a minimal phone-validation rule before implementation and QA finalization; treat this as an explicit assumption until decided.
- **Phone normalization ambiguity**: duplicate detection on phone depends on normalization rules; over-normalization may merge distinct numbers, under-normalization may miss duplicates. Mitigation: keep normalization narrow and aligned with the agreed validation rule.
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

## 7. Assumptions and constraints
- No production database integration; import may target an in-memory store, mock repository, or test-only persistence layer. [R-016]
- No external email verification, SMS verification, or contact enrichment. Validation is format-only. [R-016]
- Duplicate detection is only within the uploaded file, not against existing contacts. [R-005, R-016]
- Scope does not require async background processing, large-file optimization, or bulk performance tuning.
- Assumption from PRD v2: phone normalization for duplicate checks removes spaces, hyphens, parentheses, and a leading `+`. This is an implementation assumption, not a client-stated requirement.
- Open constraint: the exact phone validation rule is still unspecified by the client artifacts provided.

## 8. Implementation recommendation
Build a single deterministic validation pipeline that produces row results used by both preview and import confirmation. Model contact-method validation and duplicate-key selection as separate functions so R-020 and R-019 are both enforced correctly. This approach is low complexity, testable, and sufficient for the scoped MVP, provided the team defines one explicit phone-validation rule before build and QA execution.