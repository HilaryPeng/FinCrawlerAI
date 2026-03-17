#!/usr/bin/env python3
"""
财联社新闻收集工具 - 主程序入口
"""

import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

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
        raw_news = []
        now_ts = int(time.time())

        if args.command == "cailian":
            scraper = CailianScraper(config)
            print("📡 正在抓取财联社新闻...")
            state = load_state(config.STATE_FILE)
            last_run_ts = state.get("last_run_ts")
            since_ts = int(last_run_ts) if isinstance(last_run_ts, int) else now_ts - config.CRAWL_LOOKBACK_SECONDS
            raw_news = scraper.scrape_news(since_ts=since_ts, until_ts=now_ts)
            print(f"✅ 成功抓取 {len(raw_news)} 条财联社新闻")

        elif args.command == "jygs":
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
                print(f"✅ 成功抓取 {len(raw_news)} 条韭研公社异动解析")
            else:
                # 仅抓关注的人时，不走聚合输出
                raw_news = []

        elif args.command in ("all", "collect"):
            source_sections = []
            errors = []

            # 财联社
            try:
                scraper = CailianScraper(config)
                print("📡 正在抓取财联社新闻...")
                state = load_state(config.STATE_FILE)
                last_run_ts = state.get("last_run_ts")
                since_ts = int(last_run_ts) if isinstance(last_run_ts, int) else now_ts - config.CRAWL_LOOKBACK_SECONDS
                cailian_news = scraper.scrape_news(since_ts=since_ts, until_ts=now_ts)
                print(f"✅ 成功抓取 {len(cailian_news)} 条财联社新闻")
                if cailian_news:
                    cleaned = cleaner.clean_news(cailian_news)
                    aggregated = aggregator.aggregate(cleaned)
                    markdown_path = markdown_gen.generate(aggregated)
                    summary_path = markdown_gen.generate_summary(
                        aggregated,
                        filename_prefix="cailian_news",
                        report_title="# 财联社快讯简报（摘要）",
                        source_type="cailian",
                    )

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

            # 韭研公社异动解析
            try:
                jygs_scraper = JiuyangongsheScraper(config)
                action_date = args.jygs_action_date or datetime.now().strftime("%Y-%m-%d")
                print(f"📡 正在抓取韭研公社异动解析: {action_date}...")
                jygs_news = jygs_scraper.scrape_action_as_news(action_date)
                print(f"✅ 成功抓取 {len(jygs_news)} 条韭研公社异动解析")
                if jygs_news:
                    cleaned = cleaner.clean_news(jygs_news)
                    aggregated = aggregator.aggregate(cleaned)
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
                    if args.command == "all" and args.notify:
                        source_sections.append(("韭研公社", summary_path, markdown_path))
            except Exception as exc:
                errors.append(f"韭研公社抓取失败: {exc}")

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
        print(f"✅ 清洗后剩余 {len(cleaned_news)} 条内容")

        # 3. 数据聚合
        print("📊 正在聚合数据...")
        aggregated_data = aggregator.aggregate(cleaned_news)

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

        print("🎉 新闻收集完成！")
        
    except Exception as e:
        print(f"❌ 程序执行出错: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
