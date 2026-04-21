# runtime

## Purpose

This specification defines the formal runtime behavior for the market-daily pipeline, including quality gates, normal-run sequencing, and same-day rerun rules.

## Requirements

### Requirement: Quality gate

The system MUST execute a quality check after pipeline completion and MUST produce `complete`, `partial`, or `blocked` status using fixed thresholds.

#### Scenario: Check trade date quality

- **WHEN** 某个交易日跑完采集与构建链路
- **THEN** 必须按 `current.json` 中的阈值和阻断检查项输出质量状态

### Requirement: Normal run pipeline

The system MUST execute the normal daily pipeline in a fixed step order.

#### Scenario: Run daily pipeline

- **WHEN** 执行正式日跑
- **THEN** 步骤顺序必须符合 `current.json.pipeline.normal_run_steps`

### Requirement: Same-day rerun pipeline

The system MUST rebuild the full downstream chain for same-day reruns and MUST NOT regenerate only HTML.

#### Scenario: Re-run incomplete trade date

- **WHEN** 发现某日数据不完整后重新执行
- **THEN** 必须遵守 `current.json.pipeline.rerun_same_day_steps`
