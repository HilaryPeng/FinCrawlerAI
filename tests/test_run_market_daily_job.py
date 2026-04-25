from __future__ import annotations

import unittest

from scripts import run_market_daily_job


class RunMarketDailyJobRetryTests(unittest.TestCase):
    def test_retries_collection_once_when_quote_count_below_threshold(self) -> None:
        calls: list[dict] = []
        results = [
            {"trade_date": "2026-04-22", "quotes": 3200},
            {"trade_date": "2026-04-22", "quotes": 5100},
        ]

        def fake_collect_market_data(**kwargs):
            calls.append(kwargs)
            return results[len(calls) - 1]

        result, retry_count = run_market_daily_job.run_collection_with_retry(
            collect_market_data_fn=fake_collect_market_data,
            trade_date="2026-04-22",
            db_path="fake.db",
            with_news=False,
            news_sources={"jygs"},
            with_attention=True,
            min_quote_count=4500,
            max_collect_retries=1,
        )

        self.assertEqual(retry_count, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["quotes"], 5100)

    def test_does_not_retry_when_quote_count_meets_threshold(self) -> None:
        calls: list[dict] = []

        def fake_collect_market_data(**kwargs):
            calls.append(kwargs)
            return {"trade_date": "2026-04-22", "quotes": 4600}

        result, retry_count = run_market_daily_job.run_collection_with_retry(
            collect_market_data_fn=fake_collect_market_data,
            trade_date="2026-04-22",
            db_path="fake.db",
            with_news=False,
            news_sources={"jygs"},
            with_attention=True,
            min_quote_count=4500,
            max_collect_retries=1,
        )

        self.assertEqual(retry_count, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["quotes"], 4600)

    def test_skips_trading_board_memberships_when_disabled(self) -> None:
        class FakeBoardsCollector:
            called = False

            def collect_trading_board_memberships(self, trade_date: str) -> int:
                self.called = True
                return 12

        collector = FakeBoardsCollector()

        result = run_market_daily_job.maybe_collect_trading_board_memberships(
            boards_collector=collector,
            trade_date="2026-04-24",
            enabled=False,
        )

        self.assertEqual(result, 0)
        self.assertFalse(collector.called)

    def test_collects_trading_board_memberships_when_enabled(self) -> None:
        class FakeBoardsCollector:
            trade_dates: list[str]

            def __init__(self) -> None:
                self.trade_dates = []

            def collect_trading_board_memberships(self, trade_date: str) -> int:
                self.trade_dates.append(trade_date)
                return 12

        collector = FakeBoardsCollector()

        result = run_market_daily_job.maybe_collect_trading_board_memberships(
            boards_collector=collector,
            trade_date="2026-04-24",
            enabled=True,
        )

        self.assertEqual(result, 12)
        self.assertEqual(collector.trade_dates, ["2026-04-24"])


if __name__ == "__main__":
    unittest.main()
