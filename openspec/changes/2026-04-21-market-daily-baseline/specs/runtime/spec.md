## ADDED Requirements

### Requirement: Baseline runtime source

The system MUST treat `openspec/specs/runtime/` as the formal baseline source for run sequencing and quality-gate behavior.

#### Scenario: Update pipeline execution rules

- **WHEN** an engineer changes run order or rerun rules
- **THEN** the runtime baseline MUST be updated before implementation changes land
