#!/usr/bin/env python3
"""
财联社新闻收集工具 - 主程序入口
"""

import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
import json

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from scraper.cailian_scraper import CailianScraper
from scraper.jiuyangongshe_scraper import JiuyangongsheScraper
from processor.cleaner import DataCleaner
from processor.aggregator import DataAggregator
from output.markdown_gen import MarkdownGenerator
from config.settings import get_config
from utils.state import load_state, save_state
from notifier.feishu import FeishuNotifier


def write_run_report(config, report: dict, filename_prefix: str = "run_report") -> dict:
    """写入运行健康报告（json + markdown），便于长期稳定运行监控。"""
    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.PROCESSED_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{filename_prefix}_{ts_label}.json"
    md_path = out_dir / f"{filename_prefix}_{ts_label}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 运行健康报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- **命令**: {report.get('command', '')}",
        f"- **状态**: {report.get('status', '')}",
        f"- **总耗时(秒)**: {report.get('elapsed_seconds', 0)}",
        "",
        "## 来源明细",
        "",
    ]
    for s in report.get("sources", []):
        lines.append(f"### {s.get('name', 'unknown')}")
        lines.append(f"- **状态**: {s.get('status', '')}")
        lines.append(f"- **耗时(秒)**: {s.get('elapsed_seconds', 0)}")
        lines.append(f"- **抓取条数**: {s.get('fetched', 0)}")
        lines.append(f"- **清洗后条数**: {s.get('cleaned', 0)}")
        lines.append(f"- **事件数**: {s.get('events', 0)}")
        tr = s.get("time_range")
        if tr:
            lines.append(f"- **时间范围**: {tr}")
        err = s.get("error")
        if err:
            lines.append(f"- **错误**: {err}")
        out = s.get("outputs", {})
        if out:
            lines.append("- **输出**:")
            for k, v in out.items():
                lines.append(f"  - {k}: {v}")
        lines.append("")

    if report.get("errors"):
        lines.append("## 错误汇总")
        lines.append("")
        for e in report.get("errors", []):
            lines.append(f"- {e}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="News crawler")
    subparsers = parser.add_subparsers(dest="command")

    # 财联社
    subparsers.add_parser("cailian", help="Run Cailian (财联社) crawler")

    # 韭研公社
    jygs = subparsers.add_parser("jygs", help="Run Jiuyangongshe (韭研公社) crawler")
    jygs.add_argument(
        "--action-date",
        default=None,
        help="Scrape /action/YYYY-MM-DD (e.g. 2026-01-26)",
    )
    jygs.add_argument(
        "--focus",
        action="store_true",
        help="Fetch followed users list (requires env JYGS_PHONE/JYGS_PASSWORD)",
    )

    # 全量
    all_parser = subparsers.add_parser("all", help="Run all crawlers and optionally notify")
    all_parser.add_argument(
        "--notify",
        action="store_true",
        help="Send Feishu notifications after run",
    )
    all_parser.add_argument(
        "--jygs-action-date",
        default=None,
        help="Use specified date for Jiuyangongshe action (YYYY-MM-DD)",
    )

    # 只收集
    collect_parser = subparsers.add_parser("collect", help="Run all crawlers without notify")
    collect_parser.add_argument(
        "--jygs-action-date",
        default=None,
        help="Use specified date for Jiuyangongshe action (YYYY-MM-DD)",
    )

    # 通知（只推送，不抓取）
    notify_parser = subparsers.add_parser("notify", help="Send Feishu notifications from latest outputs")
    notify_parser.add_argument("--cailian-file", default=None, help="Use specific Cailian Markdown file")
    notify_parser.add_argument("--jygs-file", default=None, help="Use specific Jiuyangongshe Markdown file")
    notify_parser.add_argument("--title", default=None, help="Custom message title")

    args = parser.parse_args(argv)
    # Backward-compatible default
    if not args.command:
        args.command = "cailian"
    return args


def main():
    """主程序"""
    print("🚀 启动财联社新闻收集工具...")

    args = parse_args()
    
    # 加载配置
    config = get_config()
    config.ensure_directories()
    
    # 初始化组件（按需使用）
    cleaner = DataCleaner(config)
    aggregator = DataAggregator(config)
    markdown_gen = MarkdownGenerator(config)
    
    try:
        run_started = time.perf_counter()
        raw_news = []
        now_ts = int(time.time())

        if args.command == "cailian":
            s_started = time.perf_counter()
            source_report = {"name": "财联社", "status": "ok", "fetched": 0, "cleaned": 0, "events": 0, "outputs": {}}
            scraper = CailianScraper(config)
            print("📡 正在抓取财联社新闻...")
            state = load_state(config.STATE_FILE)
            last_run_ts = state.get("last_run_ts")
            since_ts = int(last_run_ts) if isinstance(last_run_ts, int) else now_ts - config.CRAWL_LOOKBACK_SECONDS
            raw_news = scraper.scrape_news(since_ts=since_ts, until_ts=now_ts)
            source_report["fetched"] = len(raw_news)
            print(f"✅ 成功抓取 {len(raw_news)} 条财联社新闻")

        elif args.command == "jygs":
            s_started = time.perf_counter()
            source_report = {"name": "韭研公社", "status": "ok", "fetched": 0, "cleaned": 0, "events": 0, "outputs": {}}
            jygs_scraper = JiuyangongsheScraper(config)

            # 关注的人（单独落盘）
            if args.focus:
                print("👥 正在抓取韭研公社关注的人...")
                jygs_scraper.login_auto()
                follow_users = jygs_scraper.scrape_follow_users(limit=500, start=1)

                ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = config.PROCESSED_DATA_DIR / f"jiuyangongshe_follow_users_{ts_label}.md"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                lines = [
                    "# 韭研公社关注的人列表",
                    "",
                    f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"总数: {len(follow_users)}",
                    "",
                ]
                for idx, user in enumerate(follow_users, start=1):
                    if not isinstance(user, dict):
                        lines.append(f"- {idx}. {user}")
                        continue
                    name = user.get("nickname") or user.get("name") or ""
                    uid = user.get("user_id") or user.get("id") or ""
                    line = f"- {idx}. {name} ({uid})".strip()
                    lines.append(line)
                out_path.write_text("\n".join(lines), encoding="utf-8")
                print(f"✅ 关注的人列表已保存: {out_path}")

            # 异动解析（用于生成 Markdown）
            if args.action_date:
                print(f"📡 正在抓取韭研公社异动解析: {args.action_date}...")
                raw_news = jygs_scraper.scrape_action_as_news(args.action_date)
                source_report["fetched"] = len(raw_news)
                print(f"✅ 成功抓取 {len(raw_news)} 条韭研公社异动解析")
            else:
                # 仅抓关注的人时，不走聚合输出
                raw_news = []

        elif args.command in ("all", "collect"):
            source_sections = []
            errors = []
            per_sources = []
            run_cmd = args.command

            # 财联社
            try:
                s_started = time.perf_counter()
                scraper = CailianScraper(config)
                print("📡 正在抓取财联社新闻...")
                state = load_state(config.STATE_FILE)
                last_run_ts = state.get("last_run_ts")
                since_ts = int(last_run_ts) if isinstance(last_run_ts, int) else now_ts - config.CRAWL_LOOKBACK_SECONDS
                cailian_news = scraper.scrape_news(since_ts=since_ts, until_ts=now_ts)
                print(f"✅ 成功抓取 {len(cailian_news)} 条财联社新闻")
                s_rep = {"name": "财联社", "status": "ok", "fetched": len(cailian_news), "cleaned": 0, "events": 0, "outputs": {}}
                if cailian_news:
                    cleaned = cleaner.clean_news(cailian_news)
                    s_rep["cleaned"] = len(cleaned)
                    aggregated = aggregator.aggregate(cleaned)
                    s_rep["events"] = len(aggregated.get("events", []) or [])
                    s_rep["time_range"] = (aggregated.get("summary", {}) or {}).get("time_range")
                    markdown_path = markdown_gen.generate(aggregated)
                    summary_path = markdown_gen.generate_summary(
                        aggregated,
                        filename_prefix="cailian_news",
                        report_title="# 财联社快讯简报（摘要）",
                        source_type="cailian",
                    )
                    s_rep["outputs"] = {"summary": summary_path, "full": markdown_path}

                    if args.command == "all" and args.notify:
                        source_sections.append(("财联社", summary_path, markdown_path))

                    max_ts = max(
                        [item.get("publish_ts", 0) for item in cailian_news if isinstance(item.get("publish_ts"), int)]
                        or [0]
                    )
                    if max_ts:
                        save_state(
                            config.STATE_FILE,
                            {
                                "last_run_ts": max_ts,
                                "last_run_time": datetime.fromtimestamp(max_ts).strftime("%Y-%m-%d %H:%M:%S"),
                                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "fetched_count": len(cailian_news),
                            },
                        )
            except Exception as exc:
                errors.append(f"财联社抓取失败: {exc}")
                s_rep = {"name": "财联社", "status": "error", "error": str(exc), "fetched": 0, "cleaned": 0, "events": 0, "outputs": {}}
            s_rep["elapsed_seconds"] = round(time.perf_counter() - s_started, 2)
            per_sources.append(s_rep)

            # 韭研公社异动解析
            try:
                s_started = time.perf_counter()
                jygs_scraper = JiuyangongsheScraper(config)
                action_date = args.jygs_action_date or datetime.now().strftime("%Y-%m-%d")
                print(f"📡 正在抓取韭研公社异动解析: {action_date}...")
                jygs_news = jygs_scraper.scrape_action_as_news(action_date)
                print(f"✅ 成功抓取 {len(jygs_news)} 条韭研公社异动解析")
                s_rep = {"name": "韭研公社", "status": "ok", "fetched": len(jygs_news), "cleaned": 0, "events": 0, "outputs": {}}
                if jygs_news:
                    cleaned = cleaner.clean_news(jygs_news)
                    s_rep["cleaned"] = len(cleaned)
                    aggregated = aggregator.aggregate(cleaned)
                    s_rep["events"] = len(aggregated.get("events", []) or [])
                    s_rep["time_range"] = (aggregated.get("summary", {}) or {}).get("time_range")
                    date_label = (action_date or "").replace("-", "")
                    prefix = f"jiuyangongshe_action_{date_label}" if date_label else "jiuyangongshe_action"
                    report_title = f"# 韭研公社异动解析研究简报（{action_date}）"
                    markdown_path = markdown_gen.generate(
                        aggregated,
                        filename_prefix=prefix,
                        report_title=report_title,
                    )
                    summary_path = markdown_gen.generate_summary(
                        aggregated,
                        filename_prefix=prefix,
                        report_title=f"# 韭研公社异动解析简报（摘要）（{action_date}）",
                        source_type="jygs",
                    )
                    s_rep["outputs"] = {"summary": summary_path, "full": markdown_path}
                    if args.command == "all" and args.notify:
                        source_sections.append(("韭研公社", summary_path, markdown_path))
            except Exception as exc:
                errors.append(f"韭研公社抓取失败: {exc}")
                s_rep = {"name": "韭研公社", "status": "error", "error": str(exc), "fetched": 0, "cleaned": 0, "events": 0, "outputs": {}}
            s_rep["elapsed_seconds"] = round(time.perf_counter() - s_started, 2)
            per_sources.append(s_rep)

            if args.command == "all" and args.notify and source_sections:
                notifier = FeishuNotifier(config)
                title = f"2小时汇总 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                for source_name, summary_path, full_path in source_sections:
                    summary_content = Path(summary_path).read_text(encoding="utf-8")
                    notifier.send_markdown(title=f"{title} - {source_name}（摘要）", markdown=summary_content)
                    full_content = Path(full_path).read_text(encoding="utf-8")
                    notifier.send_markdown(title=f"{title} - {source_name}（全量）", markdown=full_content)

            if errors:
                print("⚠️ 部分任务失败:")
                for err in errors:
                    print(f"- {err}")

            report_paths = write_run_report(
                config,
                {
                    "command": run_cmd,
                    "status": "ok" if not errors else "partial",
                    "elapsed_seconds": round(time.perf_counter() - run_started, 2),
                    "sources": per_sources,
                    "errors": errors,
                },
                filename_prefix=f"run_report_{run_cmd}",
            )
            print(f"📋 健康报告已生成: {report_paths['markdown']}")

            print("🎉 任务完成！")
            return

        elif args.command == "notify":
            def load_latest(prefix: str, summary: bool = False):
                pattern = f"{prefix}_*.md"
                files = sorted(
                    config.PROCESSED_DATA_DIR.glob(pattern),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if summary:
                    files = [p for p in files if "_summary_" in p.name]
                else:
                    files = [p for p in files if "_summary_" not in p.name]
                if not files:
                    return None
                return files[0]

            def resolve_file(path_value, prefix: str, summary: bool = False):
                if path_value:
                    path = Path(path_value)
                    if not path.is_absolute():
                        path = config.PROCESSED_DATA_DIR / path_value
                    if path.exists():
                        is_summary = "_summary_" in path.name
                        if summary and is_summary:
                            return path
                        if (not summary) and (not is_summary):
                            return path
                    raise FileNotFoundError(f"File not found: {path}")
                return load_latest(prefix, summary=summary)

            paths = []
            errors = []

            cailian_summary = resolve_file(args.cailian_file, "cailian_news", summary=True)
            cailian_full = resolve_file(args.cailian_file, "cailian_news", summary=False)
            if cailian_summary and cailian_full:
                paths.append(("财联社", cailian_summary, cailian_full))
            else:
                errors.append("未找到财联社Markdown输出文件")

            jygs_summary = resolve_file(args.jygs_file, "jiuyangongshe_action", summary=True)
            jygs_full = resolve_file(args.jygs_file, "jiuyangongshe_action", summary=False)
            if jygs_summary and jygs_full:
                paths.append(("韭研公社", jygs_summary, jygs_full))
            else:
                errors.append("未找到韭研公社Markdown输出文件")

            if paths:
                notifier = FeishuNotifier(config)
                base_title = args.title or f"2小时汇总 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                for source_name, summary_path, full_path in paths:
                    summary_content = summary_path.read_text(encoding="utf-8")
                    notifier.send_markdown(title=f"{base_title} - {source_name}（摘要）", markdown=summary_content)
                    full_content = full_path.read_text(encoding="utf-8")
                    notifier.send_markdown(title=f"{base_title} - {source_name}（全量）", markdown=full_content)
                print("✅ 已推送飞书消息")

            if errors:
                print("⚠️ 推送时有部分问题:")
                for err in errors:
                    print(f"- {err}")

            return

        else:
            raise ValueError(f"Unknown command: {args.command}")
        
        # 没有需要聚合输出的数据（比如仅抓关注的人）
        if not raw_news:
            print("🎉 任务完成！")
            return

        # 2. 数据清洗
        print("🧹 正在清洗数据...")
        cleaned_news = cleaner.clean_news(raw_news)
        if "source_report" in locals():
            source_report["cleaned"] = len(cleaned_news)
        print(f"✅ 清洗后剩余 {len(cleaned_news)} 条内容")

        # 3. 数据聚合
        print("📊 正在聚合数据...")
        aggregated_data = aggregator.aggregate(cleaned_news)
        if "source_report" in locals():
            source_report["events"] = len(aggregated_data.get("events", []) or [])
            source_report["time_range"] = (aggregated_data.get("summary", {}) or {}).get("time_range")

        # 4. 生成输出
        print("📝 正在生成输出文件...")

        if args.command == "jygs":
            date_label = (args.action_date or "").replace("-", "")
            prefix = f"jiuyangongshe_action_{date_label}" if date_label else "jiuyangongshe_action"
            report_title = f"# 韭研公社异动解析研究简报（{args.action_date}）" if args.action_date else "# 韭研公社异动解析研究简报"

            markdown_file = markdown_gen.generate(
                aggregated_data,
                filename_prefix=prefix,
                report_title=report_title,
            )
            summary_file = markdown_gen.generate_summary(
                aggregated_data,
                filename_prefix=prefix,
                report_title=f"# 韭研公社异动解析简报（摘要）（{args.action_date}）" if args.action_date else "# 韭研公社异动解析简报（摘要）",
                source_type="jygs",
            )
        else:
            markdown_file = markdown_gen.generate(aggregated_data)
            summary_file = markdown_gen.generate_summary(
                aggregated_data,
                filename_prefix="cailian_news",
                report_title="# 财联社快讯简报（摘要）",
                source_type="cailian",
            )

        print(f"✅ Markdown文件已生成: {markdown_file}")
        print(f"✅ 摘要文件已生成: {summary_file}")
        if "source_report" in locals():
            source_report["outputs"] = {"summary": summary_file, "full": markdown_file}
        
        # 只在财联社任务里更新增量状态
        if args.command == "cailian":
            max_ts = max(
                [item.get("publish_ts", 0) for item in raw_news if isinstance(item.get("publish_ts"), int)] or [0]
            )
            if max_ts:
                save_state(
                    config.STATE_FILE,
                    {
                        "last_run_ts": max_ts,
                        "last_run_time": datetime.fromtimestamp(max_ts).strftime("%Y-%m-%d %H:%M:%S"),
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "fetched_count": len(raw_news),
                    },
                )

        # 写入健康报告
        if "source_report" in locals():
            source_report["elapsed_seconds"] = round(time.perf_counter() - s_started, 2)
            report_paths = write_run_report(
                config,
                {
                    "command": args.command,
                    "status": "ok",
                    "elapsed_seconds": round(time.perf_counter() - run_started, 2),
                    "sources": [source_report],
                    "errors": [],
                },
                filename_prefix=f"run_report_{args.command}",
            )
            print(f"📋 健康报告已生成: {report_paths['markdown']}")

        print("🎉 新闻收集完成！")
        
    except Exception as e:
        print(f"❌ 程序执行出错: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
