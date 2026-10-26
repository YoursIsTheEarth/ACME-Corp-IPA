## MODIFIED Requirements

### Requirement: AI VP rationale for every decision (F15)
Every final `Decision` SHALL include a rationale written by the configured LLM, the rules applied, and a confidence. For floor REJECT the rationale SHALL explain the fired rules and findings. For auto-approval it SHALL be one line. For NEEDS_REVIEW it SHALL include a recommended outcome, which the Elevated Review page shows.

#### Scenario: Rejection explained
- **WHEN** INV-1016 is rejected for `UNKNOWN_ITEM`
- **THEN** the decision rationale names WidgetC and the fired rule

#### Scenario: Review recommendation
- **WHEN** INV-1010 is held for review
- **THEN** the decision includes the AI's recommended outcome and a one-line reason
