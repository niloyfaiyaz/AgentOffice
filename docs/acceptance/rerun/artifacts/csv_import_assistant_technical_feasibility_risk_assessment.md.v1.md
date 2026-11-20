# CSV Import Assistant — Technical Feasibility & Risk Assessment

## Scope alignment
This workflow is feasible as a self-contained CSV upload and validation feature. The implementation can stay within the approved scope: file upload, preview, validation, duplicate detection within the uploaded file, confirmation of valid rows, and an import summary. No production database, authentication, external integrations, or deployment concerns are assumed.

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
3. Validate required fields for each row: `first_name`, `last_name`, `email`.
4. Validate email format and reject missing/invalid email values.
5. Detect duplicates within the uploaded file.
6. Produce a preview payload with per-row status and errors.

This sequence makes it easy to explain why a row failed and ensures invalid rows are excluded before confirmation.

### 3) Duplicate detection
- Treat duplicate detection as an in-file comparison, not a cross-database lookup.
- Use normalized email address as the primary duplicate key, since email is mandatory and uniquely identifies a contact for this workflow.
- Normalize by trimming whitespace and applying case-insensitive comparison.
- If the same normalized email appears more than once, mark all matching rows as duplicates or mark the later occurrences as duplicates, depending on product UX choice; the key point is that duplicates are clearly excluded from import and shown at row level.

### 4) Preview handling
- Display all parsed rows before import with row numbers and status badges such as valid, invalid, duplicate, or excluded.
- Show row-specific errors inline or in a dedicated error column.
- Preserve the user’s ability to inspect valid rows even when some rows are invalid.
- Do not require the administrator to edit data in this phase; preview is for review and decision-making only.

### 5) Import confirmation
- Confirmation should only apply to rows that passed validation and are not duplicates.
- The confirm action should use the validated preview state rather than re-parsing the file again, unless the file is re-uploaded.
- Final summary should include total rows processed, valid rows imported, invalid rows rejected, and duplicate rows detected.

## Assumptions
- Required fields are `first_name`, `last_name`, and `email`; `phone` and `company` are optional.
- Duplicate detection is limited to rows within the uploaded CSV file.
- Email format validation uses standard application-side format rules.
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
- **Mitigation:** Define duplicate detection by normalized email within the file and surface the rule in the UI/help text.

### Risk 3: Error message ambiguity
Row-level validation can become hard to understand if messages are vague or combined poorly.
- **Mitigation:** Emit one message per failed rule per row, with field-specific wording like “email is missing” or “email format is invalid.”

### Risk 4: Partial import confusion
Users may expect all rows to import even when some are invalid.
- **Mitigation:** Make the preview and confirmation state explicit: only valid non-duplicate rows are importable; provide counts before confirmation.

### Risk 5: Large file performance
A large CSV could slow parsing, validation, or preview rendering.
- **Mitigation:** Keep processing streaming-friendly where practical and paginate or cap preview rows if needed, while still validating the full file.

### Risk 6: Inconsistent validation rules between preview and import
If rules differ between stages, the final result may not match the preview.
- **Mitigation:** Centralize validation logic so preview and confirmation use the same rules and normalized data model.

## Feasibility conclusion
The feature is technically straightforward and low-to-moderate risk if implemented as a single validation pipeline with clear row-level outcomes. The main engineering effort is predictable: robust CSV parsing, deterministic validation ordering, duplicate detection by normalized email, and a preview UI that preserves error transparency. This is sufficient for implementation planning without requiring broader system design.
