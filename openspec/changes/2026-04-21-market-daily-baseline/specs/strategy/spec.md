## ADDED Requirements

### Requirement: Baseline strategy source

The system MUST treat `openspec/specs/strategy/` as the formal baseline source for market-daily strategy rules.

#### Scenario: Review current strategy rules

- **WHEN** an engineer reviews or updates strategy behavior
- **THEN** the formal baseline MUST be read from the strategy spec before code is changed
