#!/usr/bin/env python3
"""
Pack local data/ and upload it to a remote server as a timestamped snapshot.

This is intended for the local-workstation workflow:
- local DB stays on the laptop
- every run can optionally sync a full snapshot to the server
- remote keeps historical snapshots plus a latest symlink
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
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


def create_snapshot_archive(source_dir: Path, snapshot_name: str) -> Path:
    with tempfile.TemporaryDirectory(prefix="market_data_snapshot_") as temp_dir:
        archive_path = Path(temp_dir) / f"{snapshot_name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(source_dir, arcname="data")
        final_path = Path(tempfile.gettempdir()) / f"{snapshot_name}.tar.gz"
        if final_path.exists():
            final_path.unlink()
        archive_path.replace(final_path)
    return final_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync local market data snapshot to remote server")
    parser.add_argument("--host", required=True, help="Remote server host or IP")
    parser.add_argument("--user", default="root", help="SSH user, default: root")
    parser.add_argument("--port", type=int, default=22, help="SSH port, default: 22")
    parser.add_argument(
        "--data-dir",
        default=str(project_root / "data"),
        help="Local data directory to pack, default: project_root/data",
    )
    parser.add_argument(
        "--remote-base-dir",
        default="/root/market_daily_data",
        help="Remote base directory for unpacked data snapshots",
    )
    parser.add_argument(
        "--remote-archive-dir",
        default="/root/market_daily_archives",
        help="Remote directory for uploaded tar.gz archives",
    )
    parser.add_argument(
        "--snapshot-name",
        default=None,
        help="Optional snapshot name; default: market_data_YYYYMMDD_HHMMSS",
    )
    args = parser.parse_args()

    source_dir = Path(args.data_dir).expanduser().resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"Local data dir does not exist: {source_dir}")

    snapshot_name = args.snapshot_name or f"market_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    archive_path = create_snapshot_archive(source_dir, snapshot_name)
    archive_size_mb = archive_path.stat().st_size / 1024 / 1024
    print(f"snapshot_name={snapshot_name}", flush=True)
    print(f"archive_path={archive_path}", flush=True)
    print(f"archive_size_mb={archive_size_mb:.2f}", flush=True)

    remote_archive_dir = args.remote_archive_dir.rstrip("/")
    remote_base_dir = args.remote_base_dir.rstrip("/")
    remote_archive_path = f"{remote_archive_dir}/{archive_path.name}"
    remote_unpack_dir = f"{remote_base_dir}/{snapshot_name}"
    remote_latest_link = f"{remote_base_dir}/latest"

    run_command(
        ssh_command(
            args.host,
            args.user,
            args.port,
            f"mkdir -p {shlex.quote(remote_archive_dir)} {shlex.quote(remote_base_dir)}",
        )
    )
    run_command(scp_command(archive_path, args.host, args.user, args.port, remote_archive_path))
    remote_unpack_cmd = (
        f"mkdir -p {shlex.quote(remote_unpack_dir)}"
        f" && tar -xzf {shlex.quote(remote_archive_path)} -C {shlex.quote(remote_unpack_dir)}"
        f" && ln -sfn {shlex.quote(remote_unpack_dir)} {shlex.quote(remote_latest_link)}"
    )
    run_command(ssh_command(args.host, args.user, args.port, remote_unpack_cmd))

    print("snapshot_sync_complete=1", flush=True)
    print(f"remote_archive_path={remote_archive_path}", flush=True)
    print(f"remote_unpack_dir={remote_unpack_dir}", flush=True)
    print(f"remote_latest_link={remote_latest_link}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
