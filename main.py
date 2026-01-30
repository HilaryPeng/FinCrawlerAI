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
from output.json_gen import JSONGenerator
from config.settings import get_config
from utils.state import load_state, save_state
from notifier.feishu import FeishuNotifier, build_section
from analyzer.llm_analyzer import LLMAnalyzer


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
    notify_parser.add_argument("--cailian-file", default=None, help="Use specific Cailian JSON file")
    notify_parser.add_argument("--jygs-file", default=None, help="Use specific Jiuyangongshe JSON file")
    notify_parser.add_argument("--title", default=None, help="Custom message title")

    # 分析（读取最新输出，不抓取）
    analyze_parser = subparsers.add_parser("analyze", help="Analyze latest outputs with LLM")
    analyze_parser.add_argument("--notify", action="store_true", help="Send analysis to Feishu")
    analyze_parser.add_argument("--cailian-file", default=None, help="Use specific Cailian JSON file")
    analyze_parser.add_argument("--jygs-file", default=None, help="Use specific Jiuyangongshe JSON file")
    analyze_parser.add_argument("--title", default=None, help="Custom analysis title")
    analyze_parser.add_argument("--full-list", action="store_true", help="Append full list to analysis")

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
    json_gen = JSONGenerator(config)
    
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
                out_path = config.PROCESSED_DATA_DIR / f"jiuyangongshe_follow_users_{ts_label}.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "metadata": {
                                "generated_at": datetime.now().isoformat(),
                                "source": "韭研公社",
                                "type": "follow_users",
                                "count": len(follow_users),
                            },
                            "data": follow_users,
                        },
                        f,
                        ensure_ascii=False,
                        indent=config.JSON_INDENT,
                    )
                print(f"✅ 关注的人列表已保存: {out_path}")

            # 异动解析（用于生成 Markdown/JSON）
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
                    markdown_gen.generate(aggregated)
                    json_gen.generate(aggregated)

                    if args.command == "all" and args.notify:
                        items_sorted = sorted(
                            aggregated.get("raw_news", []),
                            key=lambda item: item.get("publish_ts", 0) or 0,
                            reverse=True,
                        )
                        source_sections.append(
                            build_section("财联社", aggregated.get("summary", {}), items_sorted)
                        )

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
                    markdown_gen.generate(
                        aggregated,
                        filename_prefix=prefix,
                        report_title=report_title,
                    )
                    json_gen.generate(
                        aggregated,
                        filename_prefix=prefix,
                        source_name="韭研公社",
                    )

                    if args.command == "all" and args.notify:
                        items_sorted = sorted(
                            aggregated.get("raw_news", []),
                            key=lambda item: item.get("publish_ts", 0) or 0,
                            reverse=True,
                        )
                        source_sections.append(
                            build_section("韭研公社", aggregated.get("summary", {}), items_sorted)
                        )
            except Exception as exc:
                errors.append(f"韭研公社抓取失败: {exc}")

            if args.command == "all" and args.notify and source_sections:
                notifier = FeishuNotifier(config)
                title = f"2小时汇总 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                notifier.send_sections(title=title, sections=source_sections)

            if errors:
                print("⚠️ 部分任务失败:")
                for err in errors:
                    print(f"- {err}")

            print("🎉 任务完成！")
            return

        elif args.command == "notify":
            def load_latest(prefix: str):
                files = sorted(
                    config.PROCESSED_DATA_DIR.glob(f"{prefix}_*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not files:
                    return None
                with files[0].open("r", encoding="utf-8") as f:
                    return json.load(f)

            def load_json(path_value, prefix: str):
                if path_value:
                    path = Path(path_value)
                    if not path.is_absolute():
                        path = config.PROCESSED_DATA_DIR / path_value
                    if path.exists():
                        with path.open("r", encoding="utf-8") as f:
                            return json.load(f)
                    raise FileNotFoundError(f"File not found: {path}")
                return load_latest(prefix)

            sections = []
            errors = []

            cailian_json = load_json(args.cailian_file, "cailian_news")
            if cailian_json and isinstance(cailian_json, dict):
                data = cailian_json.get("data", {})
                items_sorted = sorted(
                    data.get("raw_news", []),
                    key=lambda item: item.get("publish_ts", 0) or 0,
                    reverse=True,
                )
                sections.append(build_section("财联社", data.get("summary", {}), items_sorted))
            else:
                errors.append("未找到财联社输出文件")

            jygs_json = load_json(args.jygs_file, "jiuyangongshe_action")
            if jygs_json and isinstance(jygs_json, dict):
                data = jygs_json.get("data", {})
                items_sorted = sorted(
                    data.get("raw_news", []),
                    key=lambda item: item.get("publish_ts", 0) or 0,
                    reverse=True,
                )
                sections.append(build_section("韭研公社", data.get("summary", {}), items_sorted))
            else:
                errors.append("未找到韭研公社输出文件")

            if sections:
                notifier = FeishuNotifier(config)
                title = args.title or f"2小时汇总 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                notifier.send_sections(title=title, sections=sections)
                print("✅ 已推送飞书消息")

            if errors:
                print("⚠️ 推送时有部分问题:")
                for err in errors:
                    print(f"- {err}")

            return

        elif args.command == "analyze":
            def load_latest(prefix: str):
                files = sorted(
                    config.PROCESSED_DATA_DIR.glob(f"{prefix}_*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not files:
                    return None
                with files[0].open("r", encoding="utf-8") as f:
                    return json.load(f)

            def load_json(path_value, prefix: str):
                if path_value:
                    path = Path(path_value)
                    if not path.is_absolute():
                        path = config.PROCESSED_DATA_DIR / path_value
                    if path.exists():
                        with path.open("r", encoding="utf-8") as f:
                            return json.load(f)
                    raise FileNotFoundError(f"File not found: {path}")
                return load_latest(prefix)

            sources = []
            errors = []

            cailian_json = load_json(args.cailian_file, "cailian_news")
            if cailian_json and isinstance(cailian_json, dict):
                sources.append(("财联社", cailian_json.get("data", {})))
            else:
                errors.append("未找到财联社输出文件")

            jygs_json = load_json(args.jygs_file, "jiuyangongshe_action")
            if jygs_json and isinstance(jygs_json, dict):
                sources.append(("韭研公社", jygs_json.get("data", {})))
            else:
                errors.append("未找到韭研公社输出文件")

            if not sources:
                print("❌ 未找到可分析的数据")
                return

            analyzer = LLMAnalyzer(config)
            result = analyzer.analyze(sources)
            notes_block = ""
            if result.truncated_notes:
                notes_block = "\n\n## 说明\n" + "\n".join([f"- {n}" for n in result.truncated_notes])

            final_markdown = result.markdown + notes_block
            if args.full_list:
                full_list_md = analyzer.build_full_list_markdown(sources)
                final_markdown = final_markdown + "\n\n" + full_list_md

            ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
            md_path = config.PROCESSED_DATA_DIR / f"analysis_{ts_label}.md"
            json_path = config.PROCESSED_DATA_DIR / f"analysis_{ts_label}.json"

            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(final_markdown, encoding="utf-8")
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "metadata": {
                            "generated_at": datetime.now().isoformat(),
                            "title": result.title,
                            "sources": [name for name, _ in sources],
                        },
                        "content": final_markdown,
                    },
                    f,
                    ensure_ascii=False,
                    indent=config.JSON_INDENT,
                )

            print(f"✅ 分析报告已生成: {md_path}")

            if args.notify:
                notifier = FeishuNotifier(config)
                title = args.title or result.title
                notifier.send_markdown(title=title, markdown=final_markdown)
                print("✅ 已推送分析到飞书")

            if errors:
                print("⚠️ 分析时有部分问题:")
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
            json_file = json_gen.generate(
                aggregated_data,
                filename_prefix=prefix,
                source_name="韭研公社",
            )
        else:
            markdown_file = markdown_gen.generate(aggregated_data)
            json_file = json_gen.generate(aggregated_data)

        print(f"✅ Markdown文件已生成: {markdown_file}")
        print(f"✅ JSON文件已生成: {json_file}")
        
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
