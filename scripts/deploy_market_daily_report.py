#!/usr/bin/env python3
"""
Generate and deploy the HTML daily market report to a remote nginx host.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_command(cmd: list[str]) -> None:
    print(f"$ {' '.join(shlex.quote(part) for part in cmd)}", flush=True)
    subprocess.run(cmd, check=True)


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


def generate_report(trade_date: str) -> Path:
    from config.settings import get_config
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.report import DailyReportGenerator

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    result = DailyReportGenerator(db).generate(trade_date)
    html_path = Path(result["html_path"]).resolve()
    if not html_path.exists():
        raise FileNotFoundError(f"Generated HTML not found: {html_path}")

    print(f"Generated HTML: {html_path}", flush=True)
    return html_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and deploy the HTML daily market report to a remote nginx host"
    )
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument("--host", required=True, help="Remote server host or IP")
    parser.add_argument("--user", default="root", help="SSH user, default: root")
    parser.add_argument("--port", type=int, default=22, help="SSH port, default: 22")
    parser.add_argument(
        "--remote-staging-dir",
        default="/root/market_daily",
        help="Remote staging directory for uploaded files",
    )
    parser.add_argument(
        "--remote-web-root",
        default="/var/www/html",
        help="Remote web root served by nginx",
    )
    parser.add_argument(
        "--publish-index",
        action="store_true",
        help="Also publish the report as index.html",
    )
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Skip HTML generation and deploy an existing file",
    )
    parser.add_argument(
        "--html-path",
        help="Existing HTML file to deploy when using --skip-generate",
    )
    args = parser.parse_args()

    if args.skip_generate:
        if not args.html_path:
            parser.error("--html-path is required when --skip-generate is set")
        html_path = Path(args.html_path).expanduser().resolve()
        if not html_path.exists():
            parser.error(f"HTML file does not exist: {html_path}")
    else:
        html_path = generate_report(args.date)

    remote_staging_dir = args.remote_staging_dir.rstrip("/")
    remote_web_root = args.remote_web_root.rstrip("/")
    remote_stage_path = f"{remote_staging_dir}/{html_path.name}"
    remote_publish_path = f"{remote_web_root}/{html_path.name}"

    print("Preparing remote directories...", flush=True)
    run_command(
        ssh_command(
            args.host,
            args.user,
            args.port,
            f"mkdir -p {shlex.quote(remote_staging_dir)} {shlex.quote(remote_web_root)}",
        )
    )

    print("Uploading HTML report...", flush=True)
    run_command(scp_command(html_path, args.host, args.user, args.port, remote_stage_path))

    remote_install_cmd = (
        f"install -m 644 {shlex.quote(remote_stage_path)} {shlex.quote(remote_publish_path)}"
    )
    if args.publish_index:
        remote_install_cmd += (
            f" && install -m 644 {shlex.quote(remote_stage_path)}"
            f" {shlex.quote(remote_web_root + '/index.html')}"
        )
    remote_install_cmd += " && systemctl reload nginx"

    print("Publishing to nginx web root...", flush=True)
    run_command(ssh_command(args.host, args.user, args.port, remote_install_cmd))

    url_base = f"http://{args.host}"
    report_url = f"{url_base}/{html_path.name}"
    print("", flush=True)
    print("Deploy complete.", flush=True)
    print(f"report_url={report_url}", flush=True)
    if args.publish_index:
        print(f"index_url={url_base}/", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
