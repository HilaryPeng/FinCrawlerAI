# Strong Stock Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the role-quota observation pool with the first version of the unified strong stock pool.

**Architecture:** Keep the existing SQLite schema. Store new scoring details in `daily_stock_features.feature_json`, write the unified score to `daily_stock_features.final_score`, and keep `daily_observation_pool` as the report-facing output table. The selector stops allocating by `dragon / center / follow` quotas and instead selects stocks that hit the trend or emotion channel.

**Tech Stack:** Python, SQLite, unittest, existing OpenSpec JSON loader.

---

## Scope Notes

- Do not add a database migration in this implementation.
- Keep `pool_group = 'top20'` for the main pool so existing report queries continue to work, even though the display label changes to strong stock pool.
- Keep legacy `dragon_score`, `center_score`, and `follow_score` columns populated for compatibility, but stop using them as the primary pool selector.
- Expect implementation to need historical quote rows for `5日 / 10日 / 20日` returns.

## File Map

- Modify `openspec/specs/strategy/current.json`: add `strong_stock_pool` scoring config while keeping old keys for compatibility.
- Modify `openspec/specs/presentation/current.json`: add strong labels and rename visible pool sections.
- Modify `src/specs/market_daily.py`: validate the new config keys.
- Modify `src/market/features/stock_feature_builder.py`: compute trend, emotion, capacity, labels, and `strong_score`.
- Modify `src/market/ranker/stock_ranker.py`: expose amount and `feature_json` so selector/report logic can use strong metadata.
- Modify `src/market/ranker/selector.py`: select by strong channel hits and `strong_score`.
- Modify `src/market/report/daily_report_generator.py`: read strong labels and add board concentration summary.
- Modify `tests/test_market_daily_spec.py`: assert new spec shape.
- Create `tests/test_strong_stock_pool.py`: cover scoring and selection behavior.

## Task 1: OpenSpec Config

**Files:**
- Modify: `openspec/specs/strategy/current.json`
- Modify: `openspec/specs/presentation/current.json`
- Modify: `src/specs/market_daily.py`
- Modify: `tests/test_market_daily_spec.py`

- [ ] **Step 1: Write failing spec tests**

Add assertions that:

```python
strong = spec.strategy["strong_stock_pool"]
self.assertEqual(strong["trend_channel"]["min_amount"], 1_500_000_000.0)
self.assertEqual(strong["emotion_channel"]["min_amount"], 1_000_000_000.0)
self.assertEqual(strong["selection"]["main_pool_limit"], 30)
self.assertEqual(spec.presentation["roles"]["trend_strong"], "趋势强")
self.assertEqual(spec.presentation["roles"]["emotion_strong"], "情绪强")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_daily_spec.py -q`

Expected: failure because `strong_stock_pool` and new role labels do not exist.

- [ ] **Step 3: Add config and validation**

Add a `strong_stock_pool` object with trend thresholds, emotion thresholds, capacity bonuses, and selection size. Add presentation role labels for `trend_strong` and `emotion_strong`, and keep old labels for compatibility.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_market_daily_spec.py -q`

Expected: all tests pass.

## Task 2: Strong Stock Metrics

**Files:**
- Modify: `src/market/features/stock_feature_builder.py`
- Create: `tests/test_strong_stock_pool.py`

- [ ] **Step 1: Write failing tests for strong metrics**

Create tests that call pure helper methods on `StockFeatureBuilder` using `__new__` and injected `spec`:

```python
builder = StockFeatureBuilder.__new__(StockFeatureBuilder)
builder.spec = load_market_daily_spec().strategy["stock_feature"]
builder.strong_spec = load_market_daily_spec().strategy["strong_stock_pool"]
metrics = builder._compute_strong_stock_metrics(
    amount=2_100_000_000,
    pct_chg_5d=11.0,
    pct_chg_10d=16.0,
    pct_chg_20d=30.0,
    limit_up=0,
    limit_up_streak=0,
)
self.assertTrue(metrics["trend_channel_hit"])
self.assertEqual(metrics["labels"], ["trend_strong", "capacity_strong"])
self.assertGreaterEqual(metrics["strong_score"], 70)
```

Add a second test for a 2-board emotion stock with `amount=1_100_000_000`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strong_stock_pool.py -q`

Expected: failure because `_compute_strong_stock_metrics` is missing.

- [ ] **Step 3: Implement helper methods**

Add helpers for:

```python
_score_trend_window(window: str, pct_chg: float | None) -> float
_compute_emotion_score(limit_up: int, limit_up_streak: int) -> float
_compute_capacity_bonus(amount: float) -> float
_compute_strong_stock_metrics(...) -> dict
```

- [ ] **Step 4: Store metrics in feature rows**

Compute `pct_chg_10d` and `pct_chg_20d`, save all new metrics in `feature_json`, set `final_score` to `strong_score`, and set `role_tag` to `trend_strong`, `emotion_strong`, or `watchlist`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_strong_stock_pool.py -q`

Expected: all tests pass.

## Task 3: Strong Pool Selection

**Files:**
- Modify: `src/market/ranker/stock_ranker.py`
- Modify: `src/market/ranker/selector.py`
- Modify: `tests/test_strong_stock_pool.py`

- [ ] **Step 1: Write failing selector test**

Use an in-memory temp SQLite database initialized with schema, insert `daily_stock_features` rows with `feature_json` strong metadata, then assert:

```python
count = ObservationPoolSelector(db).build("2026-04-24")
self.assertEqual(count, 2)
rows = db.fetchall("SELECT symbol, role_tag, pool_group FROM daily_observation_pool ORDER BY stock_rank")
self.assertEqual([row["symbol"] for row in rows], ["sz.000001", "sh.600001"])
self.assertEqual(rows[0]["pool_group"], "top20")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strong_stock_pool.py -q`

Expected: failure because selector still uses role quotas.

- [ ] **Step 3: Implement strong selection**

Rank by `final_score DESC, amount DESC, symbol ASC`, select rows whose `feature_json` has `trend_channel_hit` or `emotion_channel_hit`, keep the first `main_pool_limit`, and write remaining qualifying rows as backup up to `backup_size`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_strong_stock_pool.py -q`

Expected: all tests pass.

## Task 4: Report Output

**Files:**
- Modify: `src/market/report/daily_report_generator.py`
- Modify: `tests/test_strong_stock_pool.py`

- [ ] **Step 1: Write failing report test**

Assert `_build_report_data()` includes `strong_board_summary`, and the first summary row includes count, total amount, average score, and top strong stock.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strong_stock_pool.py -q`

Expected: failure because `strong_board_summary` is missing.

- [ ] **Step 3: Implement report summary**

Join `daily_observation_pool` with `daily_stock_features`, parse `feature_json`, expose strong labels, and add a Markdown/HTML section for board concentration.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_strong_stock_pool.py -q`

Expected: all tests pass.

## Task 5: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_market_daily_spec.py tests/test_strong_stock_pool.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run existing suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run spec validator**

Run: `python scripts/validate_market_daily_spec.py`

Expected: command exits 0 and prints strategy, data, runtime, and presentation keys.

- [ ] **Step 4: Review diff**

Run: `git diff --stat`

Expected: changes are limited to config, feature scoring, selection, report output, tests, and this plan.
