## ADDED Requirements

### Requirement: Baseline presentation source

The system MUST treat `openspec/specs/presentation/` as the formal baseline source for report labels and section naming.

#### Scenario: Update report wording

- **WHEN** an engineer changes formal report labels or presentation contract fields
- **THEN** the presentation baseline MUST be updated before the rendering code is changed
