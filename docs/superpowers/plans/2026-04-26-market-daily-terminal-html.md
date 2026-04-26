# Market Daily Terminal HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current brown poster-style HTML report with the approved A-style trading terminal layout.

**Architecture:** Keep `DailyReportGenerator` as the single HTML renderer for now, because the existing project embeds report HTML there. Add small renderer helpers for terminal metric cards and strong-stock rows, then replace the CSS/markup in `_write_html_report` without changing report data, selectors, or collectors.

**Tech Stack:** Python `unittest`, generated static HTML/CSS, SQLite-backed report data.

---

### Task 1: Add HTML Contract Test

**Files:**
- Modify: `tests/test_strong_stock_pool.py`

- [ ] **Step 1: Write the failing test**

Add this test to `StrongStockReportTests`:

```python
def test_html_report_uses_terminal_layout(self) -> None:
    with self._db_context() as db:
        trade_date = "2026-04-24"
        self._insert_quote(db, trade_date, "sh600001", "东山精密", pct_chg=6.0, amount=2_000_000_000)
        self._insert_stock_feature(db, trade_date, "sh600001", "东山精密", final_score=90)
        self._insert_board_feature(db, trade_date, "AI手机", "concept", board_score=70, pct_chg=4.0)
        self._insert_membership(db, trade_date, "sh600001", "AI手机", "concept")
        ObservationPoolSelector(db).build(trade_date)

        result = DailyReportGenerator(db).generate(trade_date)
        html = Path(result["html_path"]).read_text(encoding="utf-8")

        self.assertIn("terminal-shell", html)
        self.assertIn("强势池 Monitor", html)
        self.assertIn("CORE TARGETS", html)
        self.assertIn("AI手机", html)
        self.assertNotIn("gauge-dial", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_strong_stock_pool.StrongStockReportTests.test_html_report_uses_terminal_layout -v
```

Expected: FAIL because `terminal-shell` and `强势池 Monitor` are not in the current HTML.

### Task 2: Implement Terminal HTML Shell

**Files:**
- Modify: `src/market/report/daily_report_generator.py`

- [ ] **Step 1: Replace hero shell and CSS**

In `_write_html_report`, replace the brown hero and gauge-first CSS with a terminal palette:

```css
--bg: #0f1511;
--panel: rgba(255, 255, 255, 0.055);
--panel-strong: rgba(255, 255, 255, 0.075);
--ink: #edf3e9;
--muted: #98a495;
--line: rgba(237, 243, 233, 0.11);
--accent: #d7b45c;
--accent-soft: rgba(215, 180, 92, 0.16);
--rise: #f06f61;
--fall: #40c48a;
```

Use a top-level class:

```html
<main class="terminal-shell">
```

The first viewport must contain metric cards and top strong rows, not large gauges.

- [ ] **Step 2: Keep existing lower sections**

Preserve existing board tables, observation card details, backup pool, and modal content where practical. Style them to match the terminal shell rather than deleting data.

- [ ] **Step 3: Run focused HTML test**

Run:

```bash
python -m unittest tests.test_strong_stock_pool.StrongStockReportTests.test_html_report_uses_terminal_layout -v
```

Expected: PASS.

### Task 3: Regenerate and Visually Verify

**Files:**
- Generated only: `data/processed/market_daily/market_daily_20260424.html`

- [ ] **Step 1: Regenerate 2026-04-24 report**

Run:

```bash
python - <<'PY'
from config.settings import get_config
from src.db.connection import DatabaseConnection
from src.market.report import DailyReportGenerator

db = DatabaseConnection(get_config().MARKET_DAILY_DB)
print(DailyReportGenerator(db).generate("2026-04-24"))
PY
```

Expected: JSON, Markdown, and HTML paths for `2026-04-24`.

- [ ] **Step 2: Run full tests**

Run:

```bash
python -m unittest discover -s tests -v
python -m py_compile src/market/report/daily_report_generator.py
```

Expected: all tests pass and py_compile exits 0.

- [ ] **Step 3: Commit**

Run:

```bash
git add src/market/report/daily_report_generator.py tests/test_strong_stock_pool.py
git commit -m "feat: redesign market daily terminal html"
```
