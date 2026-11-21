# Statement of Work — CSV Import Assistant

Revise the existing CSV Import Assistant documentation to apply the approved requirement change that a contact is importable with either a valid email address or a valid phone number, while keeping the scope limited to the affected specification content.

## Scope
Update the existing PRD/specification package so validation, user stories, acceptance criteria, preview/confirmation behavior, import summary expectations, and feasibility/risk notes consistently reflect that contacts may be imported when they have either a valid email address or a valid phone number. Revise existing deliverables rather than creating a new scope of work.

### Out of scope
- Production database integration
- Use of real customer information
- Authentication
- External SaaS integrations
- Deployment
- A complete CRM
- Any feature expansion beyond the documented CSV import workflow revision

## Deliverables
- Revised concise product requirements/specification document reflecting R-019/R-020
- Revised prioritized user stories and testable acceptance criteria aligned to the new contact-validity rule
- Revised technical feasibility and risk assessment notes where affected by the validation-rule change
- Revised statement of work for this revision

## Work plan
| Key | Task | Assigned to | Depends on | Implements | Output |
|---|---|---|---|---|---|
| revise-spec | Revise CSV import documentation for email-or-phone validation rule | Pat | — | R-002, R-003, R-004, R-005, R-006, R-007, R-008, R-010, R-011, R-012, R-013, R-016, R-017, R-018, R-019, R-020 | markdown |

## Acceptance criteria
- The statement of work clearly limits work to the requirement-change revision.
- Task-to-requirement traceability precisely covers only the requirements affected by the revised rule and the required deliverables.
- The plan is minimal and sufficient for updating the existing documentation package so engineering can build and test the workflow without further clarification.

## Assumptions
- The revision applies only to the documented CSV import workflow and does not introduce new fields or integrations.
- Existing deliverables are available for targeted revision.
- Phone validation should be documented at a practical format/validity level suitable for implementation guidance, without requiring external validation services.

## Tool requirements
- (none)

## Risks
- (none)

## Budget notes
Minimal revision effort: one targeted documentation update task only, because the client requested a narrow requirement change and existing deliverables should be revised rather than recreated.

## Quality assurance
No independent QA review planned

## Questions for the client
- (none)
