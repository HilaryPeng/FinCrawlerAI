#!/usr/bin/env python3
"""
Run the full daily market pipeline on the local workstation, then deploy to server.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_command(cmd: list[str]) -> None:
    print(f"$ {' '.join(shlex.quote(part) for part in cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def try_run_command(cmd: list[str], label: str) -> bool:
    try:
        run_command(cmd)
        return True
    except Exception as exc:
        print(f"[warn] {label} failed: {exc}", flush=True)
        return False


def clear_proxy_env() -> None:
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]:
        os.environ.pop(key, None)


def is_a_share_trade_date(trade_date: str) -> bool:
    import akshare as ak

    calendar = ak.tool_trade_date_hist_sina()
    if "trade_date" not in calendar.columns:
        raise RuntimeError("A-share calendar response missing trade_date column")
    trade_dates = {str(value)[:10] for value in calendar["trade_date"].astype(str).tolist()}
    return trade_date in trade_dates


def ssh_command(host: str, user: str, port: int, remote_cmd: str) -> list[str]:
    return [
        "ssh",
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        remote_cmd,
    ]


def scp_command(local_path: Path, host: str, user: str, port: int, remote_path: str) -> list[str]:
    return [
        "scp",
        "-P",
        str(port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        str(local_path),
        f"{user}@{host}:{remote_path}",
    ]


def create_snapshot_archive(source_dir: Path, snapshot_name: str) -> Path:
    import tarfile
    import tempfile

    with tempfile.TemporaryDirectory(prefix="market_data_snapshot_") as temp_dir:
        archive_path = Path(temp_dir) / f"{snapshot_name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(source_dir, arcname="data")
        final_path = Path(tempfile.gettempdir()) / f"{snapshot_name}.tar.gz"
        if final_path.exists():
            final_path.unlink()
        shutil.move(str(archive_path), str(final_path))
    return final_path


def publish_reports_to_server(
    html_path: Path,
    index_path: Path,
    host: str,
    user: str,
    port: int,
    remote_staging_dir: str,
    remote_web_root: str,
) -> None:
    remote_staging_dir = remote_staging_dir.rstrip("/")
    remote_web_root = remote_web_root.rstrip("/")
    remote_report_stage = f"{remote_staging_dir}/{html_path.name}"
    remote_index_stage = f"{remote_staging_dir}/{index_path.name}"

    run_command(
        ssh_command(
            host,
            user,
            port,
            f"mkdir -p {shlex.quote(remote_staging_dir)} {shlex.quote(remote_web_root)}",
        )
    )
    run_command(scp_command(html_path, host, user, port, remote_report_stage))
    run_command(scp_command(index_path, host, user, port, remote_index_stage))

    remote_install_cmd = (
        f"install -m 644 {shlex.quote(remote_report_stage)} {shlex.quote(remote_web_root + '/' + html_path.name)}"
        f" && install -m 644 {shlex.quote(remote_index_stage)} {shlex.quote(remote_web_root + '/market_daily_index.html')}"
        f" && install -m 644 {shlex.quote(remote_index_stage)} {shlex.quote(remote_web_root + '/index.html')}"
        f" && systemctl reload nginx"
    )
    run_command(ssh_command(host, user, port, remote_install_cmd))


def sync_data_snapshot_to_server(
    source_dir: Path,
    host: str,
    user: str,
    port: int,
    remote_base_dir: str,
    remote_archive_dir: str,
) -> str:
    snapshot_name = f"market_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    archive_path = create_snapshot_archive(source_dir, snapshot_name)
    remote_archive_dir = remote_archive_dir.rstrip("/")
    remote_base_dir = remote_base_dir.rstrip("/")
    remote_archive_path = f"{remote_archive_dir}/{archive_path.name}"
    remote_unpack_dir = f"{remote_base_dir}/{snapshot_name}"
    remote_latest_link = f"{remote_base_dir}/latest"

    run_command(
        ssh_command(
            host,
            user,
            port,
            f"mkdir -p {shlex.quote(remote_archive_dir)} {shlex.quote(remote_base_dir)}",
        )
    )
    run_command(scp_command(archive_path, host, user, port, remote_archive_path))
    remote_unpack_cmd = (
        f"mkdir -p {shlex.quote(remote_unpack_dir)}"
        f" && tar -xzf {shlex.quote(remote_archive_path)} -C {shlex.quote(remote_unpack_dir)}"
        f" && ln -sfn {shlex.quote(remote_unpack_dir)} {shlex.quote(remote_latest_link)}"
    )
    run_command(ssh_command(host, user, port, remote_unpack_cmd))
    return remote_latest_link


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local market daily pipeline and publish to server")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Trade date in YYYY-MM-DD format")
    parser.add_argument("--check-trade-date", action="store_true", help="Skip if the date is not an A-share trading day")
    parser.add_argument("--with-news", action="store_true", help="Also collect market news")
    parser.add_argument("--news-sources", default="cailian,jygs", help="Comma-separated news sources")
    parser.add_argument("--with-attention", action="store_true", help="Also collect attention/screener data")
    parser.add_argument("--clear-proxy-env", action="store_true", help="Clear proxy env vars before running")
    parser.add_argument("--host", required=True, help="Remote server host or SSH config alias")
    parser.add_argument("--user", default="root", help="SSH user")
    parser.add_argument("--port", type=int, default=22, help="SSH port")
    parser.add_argument("--remote-staging-dir", default="/root/market_daily", help="Remote staging directory")
    parser.add_argument("--remote-web-root", default="/var/www/html", help="Remote nginx web root")
    parser.add_argument("--sync-data", action="store_true", help="Sync local data snapshot to server after run")
    parser.add_argument("--remote-data-base-dir", default="/root/market_daily_data", help="Remote data snapshot base dir")
    parser.add_argument("--remote-archive-dir", default="/root/market_daily_archives", help="Remote archive dir")
    parser.add_argument("--notify-via-server", action="store_true", help="Send Feishu notification by executing on the server")
    parser.add_argument("--server-project-dir", default="/opt/FinCrawlerAI", help="Server project directory for remote notification")
    parser.add_argument("--base-url", required=True, help="Public base URL, e.g. http://167.179.78.250")
    args = parser.parse_args()

    if args.clear_proxy_env:
        clear_proxy_env()

    trade_date = args.date
    datetime.strptime(trade_date, "%Y-%m-%d")
    if args.check_trade_date and not is_a_share_trade_date(trade_date):
        print(f"skip_non_trading_date={trade_date}", flush=True)
        return 0

    from config.settings import get_config
    from scripts.collect_market_data import collect_market_data
    from scripts.generate_market_daily_index import generate_index_page
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.collectors.boards_collector import BoardsCollector
    from src.market.features import BoardFeatureBuilder, StockFeatureBuilder
    from src.market.quality import DataQualityChecker
    from src.market.ranker import ObservationPoolSelector
    from src.market.report import DailyReportGenerator

    config = get_config()
    config.ensure_directories()
    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    news_sources = {item.strip() for item in args.news_sources.split(",") if item.strip()}

    print(f"=== Local daily job start: {trade_date} ===", flush=True)
    collect_result = collect_market_data(
        trade_date=trade_date,
        db_path=config.MARKET_DAILY_DB,
        with_news=args.with_news,
        news_sources=news_sources,
        with_attention=args.with_attention,
    )
    print(f"collect_result={collect_result}", flush=True)

    membership_count = BoardsCollector(db).collect_industry_memberships_baostock(trade_date)
    print(f"membership_inserted={membership_count}", flush=True)

    unified_count = BoardsCollector(db).build_csrc_industry_board_quotes(trade_date)
    print(f"unified_board_quotes_inserted={unified_count}", flush=True)

    board_feature_count = BoardFeatureBuilder(db).build(trade_date)
    stock_feature_count = StockFeatureBuilder(db).build(trade_date)
    print(f"board_features={board_feature_count}", flush=True)
    print(f"stock_features={stock_feature_count}", flush=True)

    observation_count = ObservationPoolSelector(db).build(trade_date)
    print(f"observation_pool_inserted={observation_count}", flush=True)

    report_result = DailyReportGenerator(db).generate(trade_date)
    index_path = Path(generate_index_page()).resolve()
    print(f"report_result={report_result}", flush=True)
    print(f"index_path={index_path}", flush=True)

    html_path = Path(report_result["html_path"]).resolve()
    json_path = Path(report_result["json_path"]).resolve()

    publish_ok = True
    try:
        publish_reports_to_server(
            html_path=html_path,
            index_path=index_path,
            host=args.host,
            user=args.user,
            port=args.port,
            remote_staging_dir=args.remote_staging_dir,
            remote_web_root=args.remote_web_root,
        )
    except Exception as exc:
        publish_ok = False
        print(f"[warn] publish_reports_to_server failed: {exc}", flush=True)

    remote_latest_link = ""
    sync_ok = True
    if args.sync_data:
        try:
            remote_latest_link = sync_data_snapshot_to_server(
                source_dir=(project_root / "data").resolve(),
                host=args.host,
                user=args.user,
                port=args.port,
                remote_base_dir=args.remote_data_base_dir,
                remote_archive_dir=args.remote_archive_dir,
            )
            print(f"remote_latest_link={remote_latest_link}", flush=True)
        except Exception as exc:
            sync_ok = False
            print(f"[warn] sync_data_snapshot_to_server failed: {exc}", flush=True)

    quality = DataQualityChecker(db).check(trade_date)
    report_url = f"{args.base_url.rstrip('/')}/{html_path.name}"
    print(f"quality={quality}", flush=True)
    print(f"report_url={report_url}", flush=True)

    if args.notify_via_server:
        if publish_ok and sync_ok:
            if not remote_latest_link:
                remote_latest_link = f"{args.remote_data_base_dir.rstrip('/')}/latest"
            remote_json_path = f"{remote_latest_link}/data/processed/market_daily/{json_path.name}"
            remote_cmd = (
                f"cd {shlex.quote(args.server_project_dir)}"
                f" && . .venv/bin/activate"
                f" && PYTHONPATH={shlex.quote(args.server_project_dir)}"
                f" python scripts/send_market_daily_notification.py"
                f" --json-path {shlex.quote(remote_json_path)}"
                f" --report-url {shlex.quote(report_url)}"
                f" --quality-status {shlex.quote(quality.get('status', 'unknown'))}"
            )
            try_run_command(
                ssh_command(args.host, args.user, args.port, remote_cmd),
                "remote Feishu notification",
            )
        else:
            print("[warn] skip remote Feishu notification because publish/sync did not complete", flush=True)

    print(f"=== Local daily job done: {trade_date} ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
