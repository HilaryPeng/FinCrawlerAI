# Proposal: market-daily-baseline

## Why

当前项目的策略、数据口径、运行链路和页面展示已经形成稳定实现，但缺少单一正式规则源。后续隔一段时间再改代码时，容易出现：

- 文档和代码脱节
- 规则修改没有连续记录
- 数据回补、运行和展示口径逐步漂移

## What

## What Changes

- 建立 `openspec/` 作为正式规则源
- 冻结当前实现为第一版基线 spec
- 将当前市场日报能力拆分为 strategy / data / runtime / presentation 四类正式 spec

## Notes

- `openspec/specs/*/current.json` 保留为机器可读基线
- `openspec/specs/*/spec.md` 提供 OpenSpec CLI 可读的正式约束说明

## Expected impact

- 后续所有影响日报结果的改动都必须先改 spec
- 项目具备可追溯的策略基线
- 代码与规则源逐步收敛为单一来源
