# OpenSpec Workflow

`openspec/` 是当前项目的正式规则源。

约定如下：

- 当前正式策略、数据契约、运行口径、展示口径只认 `openspec/specs/`
- 任何影响日报结果的改动，必须先在 `openspec/changes/` 建 proposal
- proposal 确认后再改代码
- 代码落地后，把变更并回 `openspec/specs/`，并归档 change

当前目录职责：

- `openspec/specs/strategy/`：策略规则与参数
- `openspec/specs/data/`：数据契约与重建依赖
- `openspec/specs/runtime/`：运行链路与质量门槛
- `openspec/specs/presentation/`：展示口径与正式文案映射
- `openspec/changes/`：后续变更提案与归档
