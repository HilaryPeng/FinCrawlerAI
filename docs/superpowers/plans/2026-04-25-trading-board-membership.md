# Trading Board Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trading-style board memberships and use them as the primary board display for strong stock reports.

**Architecture:** Reuse `stock_board_membership` for `concept` and `industry` memberships. Add selection helpers in the report layer to resolve each stock's primary trading board from `concept -> industry -> industry_csrc`, while leaving strong stock scoring unchanged. Add a collector method for limited, keyword-augmented trading board membership backfills.

**Tech Stack:** Python, SQLite, AkShare, unittest.

---

### Task 1: Report Trading Board Selection

**Files:**
- Modify: `src/market/report/daily_report_generator.py`
- Test: `tests/test_strong_stock_pool.py`

- [ ] **Step 1: Write failing tests**

Add tests that insert one strong stock with multiple memberships and verify the report uses `concept` as the primary board, keeps related labels, and aggregates strong board summary by that trading board.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_strong_stock_pool.StrongStockReportTests -v`

Expected: fails because `trading_board_name` and trading-board aggregation do not exist.

- [ ] **Step 3: Implement minimal report changes**

Add helper methods:

```python
def _get_trading_board_map(self, trade_date: str) -> Dict[str, Dict[str, Any]]:
    ...

def _attach_trading_boards(self, trade_date: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ...
```

Update `_get_observation_pool()` and `_get_strong_board_summary()` to use `trading_board_name` with fallback to existing `board_name`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_strong_stock_pool.StrongStockReportTests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: show trading boards in strong report`

### Task 2: Trading Board Membership Collector

**Files:**
- Modify: `src/market/collectors/boards_collector.py`
- Test: `tests/test_trading_board_membership.py`

- [ ] **Step 1: Write failing tests**

Add tests for board candidate selection:

```python
selected = collector._select_trading_board_candidates("2026-04-24", concept_limit=2, industry_limit=1)
```

Expected behavior:

- concept candidates are sorted by `board_score DESC, pct_chg DESC`
- industry candidates are sorted by `board_score DESC, pct_chg DESC`
- keyword matches are included even outside the limit
- duplicate boards are removed

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_trading_board_membership -v`

Expected: fails because `_select_trading_board_candidates` does not exist.

- [ ] **Step 3: Implement selection and collection helper**

Add:

```python
TRADING_BOARD_KEYWORDS = (...)

def collect_trading_board_memberships(self, trade_date: str, concept_limit: int = 80, industry_limit: int = 40) -> int:
    ...

def _select_trading_board_candidates(self, trade_date: str, concept_limit: int, industry_limit: int) -> List[Dict[str, Any]]:
    ...
```

This method calls existing `collect_board_members()` for selected `concept` and `industry` boards.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_trading_board_membership -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: collect trading board memberships`

### Task 3: Full Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python -m unittest tests.test_strong_stock_pool tests.test_trading_board_membership -v
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 3: Run compile check**

Run:

```bash
python -m py_compile src/market/collectors/boards_collector.py src/market/report/daily_report_generator.py
```

Expected: no output and exit code 0.

