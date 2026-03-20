"""
Board data collector using AkShare.
"""

from io import StringIO
from pathlib import Path
import re
from typing import List, Dict, Any
import pandas as pd
import akshare as ak
import baostock as bs
import requests
from bs4 import BeautifulSoup
import py_mini_racer
from akshare.datasets import get_ths_js

from src.db import DatabaseConnection, DailyBoardQuotesRepository, StockBoardMembershipRepository
from src.utils.symbols import normalize_symbol


class BoardsCollector:
    """Collector for industry and concept board data."""

    MEMBER_PROGRESS_EVERY = 20
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.board_repo = DailyBoardQuotesRepository(db)
        self.membership_repo = StockBoardMembershipRepository(db)
        self._ths_industry_code_map: Dict[str, str] | None = None
        self._ths_concept_code_map: Dict[str, str] | None = None
    
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
        print(f"Collecting board members for {board_type}:{board_name}...", flush=True)

        records = self._fetch_board_members_em(board_name=board_name, board_type=board_type)
        source = "akshare_em"

        if not records:
            print(
                f"EM membership fetch empty for {board_type}:{board_name}, trying THS detail pages...",
                flush=True,
            )
            records = self._fetch_board_members_ths(board_name=board_name, board_type=board_type)
            source = "ths_detail"

        if not records:
            print(f"No board members found for {board_type}:{board_name}", flush=True)
            return 0

        for record in records:
            record["trade_date"] = trade_date
            record["board_name"] = board_name
            record["board_type"] = board_type
            record["source"] = source

        unique_keys = self.membership_repo.get_unique_keys()
        count = self.membership_repo.upsert_many(records, unique_keys)
        print(
            f"Board members stored: {board_type}:{board_name} count={count} source={source}",
            flush=True,
        )
        return count

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

    def collect_memberships_for_date(
        self,
        trade_date: str,
        board_type: str | None = None,
        limit: int | None = None,
    ) -> int:
        """Backfill board membership using stored board snapshots for a date."""
        boards = self.board_repo.find_by_date(trade_date)
        if board_type:
            boards = [board for board in boards if board.get("board_type") == board_type]
        if limit and limit > 0:
            boards = boards[:limit]

        if not boards:
            print(f"No board snapshots found for {trade_date}", flush=True)
            return 0

        print(
            f"Backfilling stock_board_membership for {trade_date}: boards={len(boards)}"
            + (f" board_type={board_type}" if board_type else ""),
            flush=True,
        )
        return self._collect_all_board_members(trade_date, boards)

    def collect_industry_memberships_baostock(self, trade_date: str) -> int:
        """Collect CSRC industry membership from BaoStock."""
        print(f"Collecting BaoStock industry membership for {trade_date}...", flush=True)

        login_result = bs.login()
        error_code = getattr(login_result, "error_code", "")
        error_msg = getattr(login_result, "error_msg", "")
        if error_code not in ("0", "success"):
            print(f"BaoStock login failed: code={error_code} msg={error_msg}", flush=True)
            return 0

        try:
            rs = bs.query_stock_industry(date=trade_date)
            rows: List[list[str]] = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

            if not rows:
                print(f"BaoStock industry query returned no rows for {trade_date}", flush=True)
                return 0

            df = pd.DataFrame(rows, columns=rs.fields)
            print(f"BaoStock industry rows={len(df)} fields={rs.fields}", flush=True)

            records: List[Dict[str, Any]] = []
            seen: set[tuple[str, str, str]] = set()
            sample_printed = 0
            progress_every = 500

            for index, row in df.iterrows():
                raw_code = str(row.get("code", "")).strip()
                symbol = normalize_symbol(raw_code.replace(".", ""))
                industry_name = str(row.get("industry", "")).strip()
                if not symbol or not industry_name:
                    continue

                key = (trade_date, symbol, industry_name)
                if key in seen:
                    continue

                record = {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "board_name": industry_name,
                    "board_type": "industry_csrc",
                    "is_primary": 1,
                    "source": "baostock",
                }
                records.append(record)
                seen.add(key)

                if sample_printed < 3:
                    print(
                        f"[sample {sample_printed + 1}] {symbol} -> {industry_name}",
                        flush=True,
                    )
                    sample_printed += 1

                if (index + 1) % progress_every == 0:
                    print(
                        f"[baostock industry progress] processed={index + 1}/{len(df)} stored={len(records)}",
                        flush=True,
                    )

            if not records:
                print(f"BaoStock industry membership normalized to 0 rows for {trade_date}", flush=True)
                return 0

            unique_keys = self.membership_repo.get_unique_keys()
            count = self.membership_repo.upsert_many(records, unique_keys)
            print(
                f"Stored {count} BaoStock industry membership records for {trade_date}",
                flush=True,
            )
            return count
        finally:
            bs.logout()

    def build_csrc_industry_board_quotes(self, trade_date: str) -> int:
        """Build unified CSRC industry board quotes from membership + stock quotes."""
        print(f"Building unified CSRC industry board quotes for {trade_date}...", flush=True)

        rows = self.db.fetchall(
            """
            SELECT
                m.board_name,
                q.symbol,
                q.name,
                q.pct_chg
            FROM stock_board_membership m
            JOIN daily_stock_quotes q
              ON m.trade_date = q.trade_date
             AND m.symbol = q.symbol
            WHERE m.trade_date = ?
              AND m.board_type = 'industry_csrc'
            """,
            (trade_date,),
        )
        if not rows:
            print(
                f"No membership+quotes rows found for {trade_date}; cannot build unified CSRC board quotes",
                flush=True,
            )
            return 0

        df = pd.DataFrame([dict(row) for row in rows])
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        print(f"Unified board input rows={len(df)}", flush=True)

        records: List[Dict[str, Any]] = []
        grouped = df.groupby("board_name", dropna=True)
        for board_name, group in grouped:
            valid = group.dropna(subset=["pct_chg"]).copy()
            if valid.empty:
                pct_chg = None
                up_count = 0
                down_count = 0
                leader_symbol = None
                leader_name = None
                leader_pct_chg = None
            else:
                pct_chg = round(float(valid["pct_chg"].mean()), 2)
                up_count = int((valid["pct_chg"] > 0).sum())
                down_count = int((valid["pct_chg"] < 0).sum())
                leader = valid.sort_values("pct_chg", ascending=False).iloc[0]
                leader_symbol = leader.get("symbol")
                leader_name = leader.get("name")
                leader_pct_chg = round(float(leader.get("pct_chg")), 2)

            records.append(
                {
                    "trade_date": trade_date,
                    "board_name": board_name,
                    "board_type": "industry_csrc",
                    "pct_chg": pct_chg,
                    "up_count": up_count,
                    "down_count": down_count,
                    "leader_symbol": leader_symbol,
                    "leader_name": leader_name,
                    "leader_pct_chg": leader_pct_chg,
                    "source": "derived_baostock",
                }
            )

        unique_keys = self.board_repo.get_unique_keys()
        count = self.board_repo.upsert_many(records, unique_keys)
        if records:
            sample = records[0]
            print(
                "Unified CSRC board sample: "
                f"{sample['board_name']} pct_chg={sample['pct_chg']} "
                f"up={sample['up_count']} down={sample['down_count']}",
                flush=True,
            )
        print(f"Stored {count} unified CSRC industry board quotes for {trade_date}", flush=True)
        return count

    def _fetch_board_members_em(self, board_name: str, board_type: str) -> List[Dict[str, Any]]:
        """Fetch board members from EM constituent endpoints."""
        fetchers = []
        if board_type == "industry":
            fetchers = [ak.stock_board_industry_cons_em]
        elif board_type == "concept":
            fetchers = [ak.stock_board_concept_cons_em]
        else:
            fetchers = [ak.stock_board_industry_cons_em, ak.stock_board_concept_cons_em]

        for fetcher in fetchers:
            try:
                df = fetcher(symbol=board_name)
            except Exception as exc:
                print(f"EM board members fetch failed for {board_name}: {exc}", flush=True)
                continue
            records = self._normalize_membership_df(df, source_name=fetcher.__name__)
            if records:
                return records
        return []

    def _fetch_board_members_ths(self, board_name: str, board_type: str) -> List[Dict[str, Any]]:
        """Fetch board members from THS board detail pages."""
        board_code = self._get_board_code_ths(board_name=board_name, board_type=board_type)
        if not board_code:
            print(f"THS board code not found for {board_type}:{board_name}", flush=True)
            return []

        detail_url = self._build_ths_detail_url(board_type=board_type, board_code=board_code)
        if not detail_url:
            return []

        headers = self._build_ths_headers()
        try:
            root_html = self._http_get_text(detail_url, headers=headers)
        except Exception as exc:
            print(f"THS detail root fetch failed for {board_type}:{board_name}: {exc}", flush=True)
            return []

        page_count = self._extract_page_count(root_html)
        print(
            f"THS detail pages for {board_type}:{board_name} code={board_code}: pages={page_count}",
            flush=True,
        )

        all_records: List[Dict[str, Any]] = []
        seen_symbols: set[str] = set()

        first_page_records = self._parse_membership_html(root_html)
        for record in first_page_records:
            if record["symbol"] not in seen_symbols:
                all_records.append(record)
                seen_symbols.add(record["symbol"])

        for page in range(1, page_count + 1):
            page_url = self._build_ths_member_page_url(
                board_type=board_type,
                board_code=board_code,
                page=page,
            )
            if not page_url:
                continue
            try:
                html = self._http_get_text(page_url, headers=headers)
            except Exception as exc:
                print(
                    f"THS detail page fetch failed for {board_type}:{board_name} page={page}: {exc}",
                    flush=True,
                )
                continue

            page_records = self._parse_membership_html(html)
            if not page_records:
                continue

            added = 0
            for record in page_records:
                if record["symbol"] in seen_symbols:
                    continue
                all_records.append(record)
                seen_symbols.add(record["symbol"])
                added += 1
            print(
                f"THS members page={page}/{page_count} board={board_name} added={added}",
                flush=True,
            )

        return all_records

    def _normalize_membership_df(self, df: pd.DataFrame, source_name: str) -> List[Dict[str, Any]]:
        """Normalize board membership dataframe into storage records."""
        if df is None or df.empty:
            return []

        code_col = None
        for candidate in ["代码", "股票代码", "证券代码", "code"]:
            if candidate in df.columns:
                code_col = candidate
                break
        if code_col is None:
            return []

        records: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for idx, row in df.iterrows():
            raw_symbol = str(row.get(code_col, "")).strip()
            symbol = normalize_symbol(raw_symbol)
            if not symbol or symbol in seen:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "is_primary": 1 if idx == 0 else 0,
                    "source": source_name,
                }
            )
            seen.add(symbol)
        return records

    def _get_board_code_ths(self, board_name: str, board_type: str) -> str | None:
        """Resolve THS board code from board name."""
        code_map: Dict[str, str] | None = None
        if board_type == "industry":
            if self._ths_industry_code_map is None:
                self._ths_industry_code_map = self._load_ths_code_map("industry")
            code_map = self._ths_industry_code_map
        elif board_type == "concept":
            if self._ths_concept_code_map is None:
                self._ths_concept_code_map = self._load_ths_code_map("concept")
            code_map = self._ths_concept_code_map

        if not code_map:
            return None
        return code_map.get(board_name)

    def _load_ths_code_map(self, board_type: str) -> Dict[str, str]:
        """Load THS board name -> code map."""
        try:
            if board_type == "industry":
                df = ak.stock_board_industry_name_ths()
            else:
                df = ak.stock_board_concept_name_ths()
        except Exception as exc:
            print(f"Failed to load THS {board_type} code map: {exc}", flush=True)
            return {}

        if df is None or df.empty:
            return {}

        code_col = "code" if "code" in df.columns else df.columns[1]
        name_col = "name" if "name" in df.columns else df.columns[0]
        result = {
            str(row[name_col]).strip(): str(row[code_col]).strip()
            for _, row in df.iterrows()
            if str(row.get(name_col, "")).strip() and str(row.get(code_col, "")).strip()
        }
        print(f"Loaded THS {board_type} code map: {len(result)} entries", flush=True)
        return result

    def _build_ths_headers(self) -> Dict[str, str]:
        """Build THS request headers with current v cookie."""
        js_content = Path(get_ths_js("ths.js")).read_text(encoding="utf-8")
        js_code = py_mini_racer.MiniRacer()
        js_code.eval(js_content)
        v_code = js_code.call("v")
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/89.0.4389.90 Safari/537.36"
            ),
            "Cookie": f"v={v_code}",
            "Referer": "http://q.10jqka.com.cn",
        }

    def _build_ths_detail_url(self, board_type: str, board_code: str) -> str | None:
        """Build THS board detail root URL."""
        if board_type == "industry":
            return f"http://q.10jqka.com.cn/thshy/detail/code/{board_code}/"
        if board_type == "concept":
            return f"http://q.10jqka.com.cn/gn/detail/code/{board_code}/"
        return None

    def _build_ths_member_page_url(self, board_type: str, board_code: str, page: int) -> str | None:
        """Build THS board member ajax page URL."""
        if board_type == "industry":
            return (
                f"https://q.10jqka.com.cn/thshy/detail/field/199112/"
                f"order/desc/page/{page}/ajax/1/code/{board_code}"
            )
        if board_type == "concept":
            return (
                f"http://q.10jqka.com.cn/gn/detail/order/desc/"
                f"page/{page}/ajax/1/code/{board_code}"
            )
        return None

    def _http_get_text(self, url: str, headers: Dict[str, str]) -> str:
        """Fetch text content for a URL."""
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text

    def _extract_page_count(self, html: str) -> int:
        """Extract total pagination pages from THS detail HTML."""
        soup = BeautifulSoup(html, features="lxml")
        page_text = ""

        page_container = soup.find(id="m-page")
        if page_container:
            page_text = page_container.get_text(" ", strip=True)
        if not page_text:
            page_info = soup.find(name="span", attrs={"class": "page_info"})
            if page_info:
                page_text = page_info.get_text(" ", strip=True)

        match = re.search(r"/\s*(\d+)", page_text)
        if match:
            return max(int(match.group(1)), 1)
        return 1

    def _parse_membership_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse THS detail HTML into board membership records."""
        try:
            tables = pd.read_html(StringIO(html))
        except ValueError:
            return []

        for table in tables:
            records = self._normalize_membership_df(table, source_name="ths_detail")
            if records:
                return records
        return []
