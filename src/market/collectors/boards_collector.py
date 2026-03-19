"""
Board data collector using AkShare.
"""

from typing import List, Dict, Any
import pandas as pd
import akshare as ak

from src.db import DatabaseConnection, DailyBoardQuotesRepository, StockBoardMembershipRepository
from src.utils.symbols import normalize_symbol


class BoardsCollector:
    """Collector for industry and concept board data."""

    MEMBER_PROGRESS_EVERY = 20
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.board_repo = DailyBoardQuotesRepository(db)
        self.membership_repo = StockBoardMembershipRepository(db)
    
    def collect(self, trade_date: str, include_members: bool = False) -> int:
        """
        Collect and store board data for a given date.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            include_members: Whether to also collect board membership
            
        Returns:
            Number of board records collected
        """
        print(f"Collecting board data for {trade_date}...", flush=True)
        
        total_count = 0
        
        industry_records = self._collect_industry_boards(trade_date)
        industry_count = len(industry_records)
        total_count += industry_count
        print(f"Collected {industry_count} industry boards", flush=True)
        
        concept_records = self._collect_concept_boards(trade_date)
        concept_count = len(concept_records)
        total_count += concept_count
        print(f"Collected {concept_count} concept boards", flush=True)

        if include_members:
            member_count = self._collect_all_board_members(
                trade_date,
                industry_records + concept_records,
            )
            print(f"Collected {member_count} board membership records", flush=True)
        
        print(f"Total: {total_count} board records for {trade_date}", flush=True)
        return total_count
    
    def _collect_industry_boards(self, trade_date: str) -> List[Dict[str, Any]]:
        """Collect industry board data."""
        try:
            print("Fetching industry boards via THS summary...", flush=True)
            records = self._fetch_industry_boards_ths(trade_date)
            if not records:
                print("THS industry boards empty, falling back to EM...", flush=True)
                records = self._fetch_industry_boards_em(trade_date)
        except Exception as e:
            print(f"Failed to fetch industry boards: {e}", flush=True)
            return []

        if records:
            unique_keys = self.board_repo.get_unique_keys()
            self.board_repo.upsert_many(records, unique_keys)
            sample = records[0]
            print(
                f"Industry board sample: {sample['board_name']} pct_chg={sample['pct_chg']} up={sample['up_count']} down={sample['down_count']}",
                flush=True,
            )
        return records
    
    def _collect_concept_boards(self, trade_date: str) -> List[Dict[str, Any]]:
        """Collect concept board data."""
        try:
            print("Fetching concept boards via THS list...", flush=True)
            records = self._fetch_concept_boards_ths(trade_date)
            if not records:
                print("THS concept boards empty, falling back to EM...", flush=True)
                records = self._fetch_concept_boards_em(trade_date)
        except Exception as e:
            print(f"Failed to fetch concept boards: {e}", flush=True)
            return []

        if records:
            unique_keys = self.board_repo.get_unique_keys()
            self.board_repo.upsert_many(records, unique_keys)
            sample = records[0]
            print(
                f"Concept board sample: {sample['board_name']} pct_chg={sample['pct_chg']}",
                flush=True,
            )
        return records

    def _fetch_industry_boards_ths(self, trade_date: str) -> List[Dict[str, Any]]:
        """Fetch industry board snapshot from THS summary."""
        df = ak.stock_board_industry_summary_ths()
        if df is None or df.empty:
            return []
        print(f"THS industry summary rows={len(df)}", flush=True)

        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "trade_date": trade_date,
                    "board_name": row.get("板块", ""),
                    "board_type": "industry",
                    "pct_chg": self._to_float(row.get("涨跌幅")),
                    "up_count": self._to_int(row.get("上涨家数")),
                    "down_count": self._to_int(row.get("下跌家数")),
                    "leader_symbol": None,
                    "leader_name": row.get("领涨股", ""),
                    "leader_pct_chg": self._to_float(row.get("领涨股-涨跌幅")),
                    "source": "akshare_ths",
                }
            )
        return records

    def _fetch_concept_boards_ths(self, trade_date: str) -> List[Dict[str, Any]]:
        """Fetch concept board list from THS as a minimal fallback dataset."""
        df = ak.stock_board_concept_name_ths()
        if df is None or df.empty:
            return []
        print(f"THS concept list rows={len(df)}", flush=True)

        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "trade_date": trade_date,
                    "board_name": row.get("name", ""),
                    "board_type": "concept",
                    "pct_chg": None,
                    "up_count": None,
                    "down_count": None,
                    "leader_symbol": None,
                    "leader_name": None,
                    "leader_pct_chg": None,
                    "source": "akshare_ths",
                }
            )
        return records

    def _fetch_industry_boards_em(self, trade_date: str) -> List[Dict[str, Any]]:
        """Fetch industry board data from EM as fallback."""
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return []
        print(f"EM industry board rows={len(df)}", flush=True)
        return [self._normalize_board(row, trade_date, "industry") for _, row in df.iterrows()]

    def _fetch_concept_boards_em(self, trade_date: str) -> List[Dict[str, Any]]:
        """Fetch concept board data from EM as fallback."""
        df = ak.stock_board_concept_name_em()
        if df is None or df.empty:
            return []
        print(f"EM concept board rows={len(df)}", flush=True)
        return [self._normalize_board(row, trade_date, "concept") for _, row in df.iterrows()]
    
    def _normalize_board(self, row: pd.Series, trade_date: str, board_type: str) -> Dict[str, Any]:
        """Normalize a board row to database format."""
        leader = row.get('领涨股', '')
        leader_name = str(leader).split('-')[0] if leader else ''
        leader_pct_str = str(leader).split('-')[-1] if leader else '0'
        try:
            leader_pct = float(leader_pct_str.replace('%', ''))
        except:
            leader_pct = 0.0
        
        return {
            "trade_date": trade_date,
            "board_name": row.get('板块名称', ''),
            "board_type": board_type,
            "pct_chg": float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else None,
            "up_count": int(row.get('上涨家数', 0)) if pd.notna(row.get('上涨家数')) else None,
            "down_count": int(row.get('下跌家数', 0)) if pd.notna(row.get('下跌家数')) else None,
            "leader_symbol": None,
            "leader_name": leader_name,
            "leader_pct_chg": leader_pct,
            "source": "akshare",
        }

    def _to_float(self, value: Any) -> float | None:
        """Convert common numeric strings into float."""
        if value is None or value == "":
            return None
        text = str(value).replace("%", "").replace(",", "").strip()
        try:
            return float(text)
        except Exception:
            return None

    def _to_int(self, value: Any) -> int | None:
        """Convert value into int."""
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except Exception:
            return None
    
    def collect_board_members(self, trade_date: str, board_name: str, board_type: str) -> int:
        """
        Collect stock membership for a specific board.
        
        Args:
            trade_date: Trade date
            board_name: Board name
            board_type: Board type (industry/concept)
            
        Returns:
            Number of member stocks collected
        """
        try:
            df = ak.stock_board_industry_cons_em(symbol=board_name)
        except Exception:
            try:
                df = ak.stock_board_concept_cons_em(symbol=board_name)
            except Exception:
                return 0
        
        if df is None or df.empty:
            return 0
        
        records = []
        for idx, row in df.iterrows():
            raw_symbol = row.get('代码', '')
            record = {
                "trade_date": trade_date,
                "symbol": normalize_symbol(raw_symbol),
                "board_name": board_name,
                "board_type": board_type,
                "is_primary": 1 if idx == 0 else 0,
                "source": "akshare",
            }
            records.append(record)
        
        if records:
            unique_keys = self.membership_repo.get_unique_keys()
            count = self.membership_repo.upsert_many(records, unique_keys)
            print(
                f"Board members stored: {board_type}:{board_name} count={count}",
                flush=True,
            )
            return count
        return 0

    def _collect_all_board_members(self, trade_date: str, board_records: List[Dict[str, Any]]) -> int:
        """Collect membership for all fetched boards."""
        total = 0
        total_boards = len(board_records)
        for index, board in enumerate(board_records, start=1):
            board_name = board.get("board_name", "")
            board_type = board.get("board_type", "")
            if not board_name or not board_type:
                continue
            total += self.collect_board_members(trade_date, board_name, board_type)
            if index % self.MEMBER_PROGRESS_EVERY == 0 or index == total_boards:
                print(
                    f"[membership progress] processed={index}/{total_boards} stored={total}",
                    flush=True,
                )
        return total
