# CSV Import Assistant — Technical Feasibility and Risk Assessment

## Feasibility summary
The CSV import workflow is feasible within scope using a client-facing parse/validate/preview/confirm flow with no production database write. The implementation can be kept simple by using a single validation pipeline that runs after parsing and is reused for both preview and confirmation, ensuring consistent results.

## Proposed implementation approach
### 1) CSV upload and parsing
- Accept a CSV file from the administrator and parse it into row objects.
- Enforce the stated file constraints as guardrails: up to 5 MB or 10,000 rows.
- Prefer a streaming or chunked parser if the UI must remain responsive for larger files; otherwise a straightforward parser is acceptable for smaller files.
- Normalize headers once at parse time so downstream validation uses a stable schema.

### 2) Preview generation
- Render **all parsed rows**, including invalid rows, so the admin can inspect issues before confirming.
- Show row number, parsed field values, validation status, and inline error messages.
- Keep preview data in memory for the session; no persistence is required.

### 3) Validation flow
Run validation after parsing and again before confirmation using the same rules:
- Required fields must be present.
- Every contact must have a valid email address; missing or invalid email causes rejection.
- Each invalid row should carry row-specific errors, not just a file-level error.
- Validation output should distinguish between:
  - parse errors,
  - required-field errors,
  - invalid email errors,
  - duplicate-row errors.

### 4) Duplicate detection within the uploaded file
Implement deterministic normalization:
- Email comparison is case-insensitive and trimmed of surrounding whitespace.
- If a row has no email, compare normalized phone number instead.
- Keep the first occurrence and flag subsequent matches as duplicates.
- Duplicate detection should run on the in-memory uploaded file only; no cross-file or database lookup is needed.

### 5) Confirmation and import summary
- On confirmation, include only valid, non-duplicate rows in the staged result.
- Because production database integration is out of scope, the “import” should be a simulated/staged outcome in memory.
- Display a summary with counts for total parsed, valid, rejected, duplicates, and imported rows.
- Preserve rejected-row details for review in the summary view.

## Key technical decisions
- **Single-source validation engine:** Use one validation module for preview and confirmation to avoid inconsistent behavior.
- **In-memory staged import:** Suitable for the scope and avoids database concerns.
- **Deterministic normalization:** Essential for predictable duplicate handling and testability.
- **All-rows preview:** Aligns with requirements and makes validation transparent.

## Assumptions
- Import is a simulated/staged in-memory result, not a persistent write.
- The preview includes all parsed rows, including invalid ones.
- Phone normalization is limited to a sensible normalization step suitable for duplicate matching; exact formatting rules can be minimal as long as they are deterministic.
- Authentication, external integrations, deployment, and CRM features are not part of this work.

## Risks and constraints
| Risk / constraint | Impact | Mitigation |
|---|---|---|
| Large files near limits cause UI slowness | Reduced responsiveness | Use streaming/chunked parsing and batch rendering; show processing state |
| Inconsistent validation between preview and confirm | Incorrect import decisions | Share one validation pipeline and test it with the same fixtures |
| Ambiguous phone normalization | Duplicate mismatch or false positives | Keep phone normalization simple and documented; add targeted tests |
| CSV formatting edge cases (quotes, commas, blank rows) | Parse errors or unexpected preview results | Use a mature CSV parser and include parse-error reporting |
| Simulated import misunderstood as persistence | Product confusion | Label the result clearly as staged/simulated and avoid database language |
| Very large row counts in memory | Memory pressure | Cap file size/rows as specified and process incrementally where possible |

## Delivery recommendation
This feature is low-to-moderate complexity and should be deliverable in one implementation cycle if the team reuses a single parsing/validation pipeline and keeps the staged import model strictly in memory. The main engineering effort is in robust CSV parsing, consistent row-level validation, and predictable duplicate detection.
