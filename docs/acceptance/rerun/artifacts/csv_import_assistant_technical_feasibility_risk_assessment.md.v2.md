# CSV Import Assistant — Technical Feasibility & Risk Assessment

## Scope alignment
This workflow remains feasible as a self-contained CSV upload and validation feature. The implementation can stay within the approved scope: file upload, preview, validation, duplicate detection within the uploaded file, confirmation of valid rows, and an import summary. No production database, authentication, external integrations, or deployment concerns are assumed.

## Updated validation rule
A row is valid if it has either:
- a valid email address, or
- a valid phone number.

Reject a row only when both contact methods are absent or invalid. First name and last name remain required. Company remains optional.

## Implementation approach

### 1) CSV parsing
- Accept a `.csv` file from the administrator UI.
- Parse the file into an in-memory row model with normalized headers.
- Require the expected columns: `first_name`, `last_name`, `email`, `phone`, `company`.
- Ignore unexpected columns, but preserve all expected fields in the preview.
- Handle common CSV edge cases: quoted values, commas inside values, blank lines, and header casing/whitespace normalization.

### 2) Validation sequencing
Use a deterministic, row-by-row pipeline so error reporting is predictable:
1. Parse file and map columns.
2. Validate structural issues: missing headers, unreadable CSV, malformed rows.
3. Validate required fields for each row: `first_name`, `last_name`.
4. Validate contact methods: accept a valid email OR a valid phone number; reject only if both are missing/invalid.
5. Detect duplicates within the uploaded file.
6. Produce a preview payload with per-row status and errors.

This sequence makes it easy to explain why a row failed and ensures invalid rows are excluded before confirmation.

### 3) Contact validation
- Email validation: standard application-side email format rules.
- Phone validation: define and document a clear phone rule (for example, E.164-like or a constrained business format) so the app can consistently decide whether a phone number is valid.
- A row with a valid email but invalid/missing phone is still valid.
- A row with no valid email but a valid phone is still valid.
- A row with both invalid or missing is rejected.

### 4) Duplicate detection
- Treat duplicate detection as an in-file comparison, not a cross-database lookup.
- Use a normalized contact key for matching. Because contact rows may now be valid via phone-only or email-only, the safest approach is to detect duplicates by normalized email when present, and by normalized phone when email is absent. If both are present, either field may be used to identify a duplicate.
- Normalize values by trimming whitespace and applying case-insensitive comparison where applicable.
- If the same normalized contact key appears more than once, mark matching rows as duplicates and exclude them from import.

### 5) Preview handling
- Display all parsed rows before import with row numbers and status badges such as valid, invalid, duplicate, or excluded.
- Show row-specific errors inline or in a dedicated error column.
- Preserve the user’s ability to inspect valid rows even when some rows are invalid.
- Do not require the administrator to edit data in this phase; preview is for review and decision-making only.

### 6) Import confirmation
- Confirmation should only apply to rows that passed validation and are not duplicates.
- The confirm action should use the validated preview state rather than re-parsing the file again, unless the file is re-uploaded.
- Final summary should include total rows processed, valid rows imported, invalid rows rejected, and duplicate rows detected.

## Assumptions
- Required fields are `first_name` and `last_name`; at least one of `email` or `phone` must be valid.
- Duplicate detection is limited to rows within the uploaded CSV file.
- Email and phone format validation uses standard application-side rules that the engineering team will define explicitly.
- Preview and validation happen in a transient session/state for the uploaded file, not via persistent storage.

## Constraints
- No production database integration is designed here; import persistence is abstracted behind a generic “import confirmed” boundary.
- No authentication, authorization, external integration, or deployment architecture is included.
- No real customer data or CRM data model assumptions are made beyond the CSV fields.
- If the file is very large, memory usage and preview pagination may become relevant, but handling large-file scale is out of scope unless later specified.

## Key technical risks and mitigations

### Risk 1: CSV parsing inconsistencies
Different CSV files may include quoted commas, inconsistent headers, blank rows, or encoding issues.
- **Mitigation:** Use a well-tested CSV parser, normalize headers, and return explicit parse errors before validation.

### Risk 2: Ambiguous duplicate logic
If duplicate criteria are not explicit, users may be confused about which rows were flagged.
- **Mitigation:** Define duplicate detection rules for email and phone consistently and surface the rule in the UI/help text.

### Risk 3: Phone validation variability
Phone numbers vary by country and formatting, which can cause inconsistent accept/reject behavior.
- **Mitigation:** Choose one validation standard, document it, and reuse the same validator in preview and import confirmation.

### Risk 4: Error message ambiguity
Row-level validation can become hard to understand if messages are vague or combined poorly.
- **Mitigation:** Emit one message per failed rule per row, such as “email is missing or invalid and phone is missing or invalid.”

### Risk 5: Partial import confusion
Users may expect all rows to import even when some are invalid.
- **Mitigation:** Make the preview and confirmation state explicit: only valid non-duplicate rows are importable; provide counts before confirmation.

### Risk 6: Large file performance
A large CSV could slow parsing, validation, or preview rendering.
- **Mitigation:** Keep processing streaming-friendly where practical and paginate or cap preview rows if needed, while still validating the full file.

### Risk 7: Inconsistent validation rules between preview and import
If rules differ between stages, the final result may not match the preview.
- **Mitigation:** Centralize validation logic so preview and confirmation use the same rules and normalized data model.

## Feasibility conclusion
The feature remains technically straightforward and low-to-moderate risk if implemented as a single validation pipeline with clear row-level outcomes. The main engineering effort is predictable: robust CSV parsing, deterministic validation ordering, flexible contact validation, duplicate detection, and a preview UI that preserves error transparency. This is sufficient for implementation planning without requiring broader system design.
