# strategy

## Purpose

This specification defines the formal strategy rules for the market-daily pipeline, including board scoring, stock role assignment, risk penalties, and observation-pool selection behavior.

## Requirements

### Requirement: Board feature scoring

The system MUST calculate `board_score` using fixed weights and MUST apply negative-return penalties for weak board conditions.

#### Scenario: Build board score

- **WHEN** 计算板块特征
- **THEN** 必须使用 `current.json` 中声明的权重与负收益惩罚

### Requirement: Stock role scoring

The system MUST calculate dragon, center, and follow role scores separately and MUST assign `role_tag` using explicit role rules.

#### Scenario: Assign stock role

- **WHEN** 计算个股特征
- **THEN** 必须按 `current.json` 中的角色门槛、风险规则和最终分公式输出结果

### Requirement: Observation pool selection

The system MUST build the observation pool using role quotas, per-board caps, and backup-pool limits.

#### Scenario: Build observation pool

- **WHEN** 生成 `daily_observation_pool`
- **THEN** Top20 与 Backup 的数量和板块约束必须符合 `current.json`
