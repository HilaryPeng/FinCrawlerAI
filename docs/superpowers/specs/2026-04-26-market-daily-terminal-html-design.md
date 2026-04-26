# Market Daily Terminal HTML Redesign

## Decision

Use the A3 visual direction for the market daily HTML report: a rice-paper and copper screen optimized for fast post-market scanning.

## Visual Direction

- Primary style: light trading desk layout, not a marketing poster.
- Primary palette:米纸铜, using a warm paper background, translucent white cards, copper highlights, and dark ink text.
- Avoid heavy black/dark cards and keep stock names readable on cards.
- Preserve high information density while improving hierarchy and mobile readability.

## Layout Changes

- First screen prioritizes market status, strong-stock count, and the top strong stocks.
- Large decorative gauges are removed or reduced to compact metric cards.
- Core strong stocks are shown as ranked terminal rows with stock name, symbol, role, score, primary trading board, and related tags.
- Strong board summary appears near the top as compact chips or a dense table.
- Details remain available lower on the page through cards/tables so the report is still complete.

## Data Behavior

- No scoring or data-selection changes.
- HTML uses the existing `report_data` payload.
- Trading board labels continue to prefer concept/industry board membership when present and fall back to CSRC industry names.

## Mobile Requirements

- The first screen must fit useful information on a phone viewport.
- Metric cards can wrap to two columns.
- Ranked strong-stock rows remain readable without horizontal scrolling.
- Large tables can still scroll horizontally in lower sections.

## Acceptance Checks

- Generated 2026-04-24 HTML shows the terminal-style A layout.
- Top rows show trading labels such as `AI手机`, `5G`, `共封装光学(CPO)`, or `PCB概念` when available.
- Report still generates JSON, Markdown, and HTML without changing selectors or collectors.
