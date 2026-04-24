# data

## Purpose

This specification defines the formal data contracts for the market-daily pipeline, including idempotent ingest rules, truth sources, and downstream rebuild dependencies.

## Requirements

### Requirement: Idempotent daily quote ingest

The system MUST support idempotent daily quote backfill and MUST NOT create duplicate rows for the same trade date and symbol.

#### Scenario: Re-run same trade date

- **WHEN** 同一交易日的行情数据被重新采集
- **THEN** 结果必须更新或补齐，而不是新增重复记录

### Requirement: Derived report dependency chain

The system MUST rebuild derived tables and reports using a fixed dependency order after upstream corrections.

#### Scenario: Rebuild after upstream correction

- **WHEN** 上游表被修正
- **THEN** 必须按照 `current.json` 中的 `rebuild_dependencies` 重建下游层

### Requirement: Report truth source

The system MUST treat derived feature tables and the observation pool as the truth source for final reports.

#### Scenario: Generate report

- **WHEN** 生成市场日报
- **THEN** 不得绕过特征层直接使用原始输入表拼接最终页面
