# presentation

## Purpose

This specification defines the formal presentation contract for the market-daily report, including role labels, section naming, and key display labels.

## Requirements

### Requirement: Stable role labels

The system MUST use a unified role-label mapping across HTML and Markdown reports.

#### Scenario: Render role label

- **WHEN** 渲染 `role_tag`
- **THEN** 必须使用 `current.json.roles` 中定义的正式中文标签

### Requirement: Stable report sections

The system MUST use formally defined section titles across HTML and Markdown reports.

#### Scenario: Render report sections

- **WHEN** 生成 Markdown 或 HTML
- **THEN** 模块标题必须与 `current.json.markdown` 和 `current.json.html.sections` 保持一致

### Requirement: Stable modal and card labels

The system MUST use consistent labels for cards and modal details in the rendered report.

#### Scenario: Render key labels

- **WHEN** 页面渲染分数、排序、入选逻辑、盯盘点和风险提示
- **THEN** 必须使用 `current.json.html.labels` 中定义的正式标签
