"""
Markdown输出生成器
"""

from datetime import datetime
from typing import Dict, List


class MarkdownGenerator:
    """Markdown输出生成器"""
    
    def __init__(self, config):
        self.config = config
        self.output_dir = config.PROCESSED_DATA_DIR
    
    def generate(self, aggregated_data: Dict, filename_prefix: str = "cailian_news", report_title: str = "# 财联社快讯研究简报") -> str:
        """生成Markdown文件"""
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{filename_prefix}_{timestamp}.md"
        filepath = self.output_dir / filename
        
        # 生成内容
        content = self._generate_markdown_content(aggregated_data, report_title=report_title)
        
        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return str(filepath)

    def generate_summary(
        self,
        aggregated_data: Dict,
        filename_prefix: str,
        report_title: str,
        source_type: str,
    ) -> str:
        """生成摘要Markdown文件"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{filename_prefix}_summary_{timestamp}.md"
        filepath = self.output_dir / filename

        content = self._generate_summary_content(
            aggregated_data,
            report_title=report_title,
            source_type=source_type,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return str(filepath)
    
    def _generate_markdown_content(self, data: Dict, report_title: str) -> str:
        """生成Markdown内容"""
        content = []

        content.append(report_title)
        content.append("")
        content.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("")

        summary = data.get('summary', {})
        stats = data.get('statistics', {})

        content.append("## 研究摘要")
        content.append("")
        content.append(f"- **新闻总数**: {summary.get('total_news', 0)}")
        content.append(f"- **时间范围**: {summary.get('time_range', '无数据')}")
        content.append(f"- **主要话题**: {', '.join(summary.get('main_topics', []))}")
        content.append("")

        tag_dist = stats.get('tag_distribution', {})
        if tag_dist:
            content.append("## 主题分布")
            content.append("")
            content.append("| 标签 | 数量 |")
            content.append("|------|------|")
            for tag, count in sorted(tag_dist.items(), key=lambda x: x[1], reverse=True):
                content.append(f"| {tag} | {count} |")
            content.append("")

        keywords = data.get('top_keywords', [])
        if keywords:
            content.append("## 关键词")
            content.append("")
            for keyword_data in keywords[:10]:
                keyword = keyword_data.get('keyword', '')
                count = keyword_data.get('count', 0)
                content.append(f"- **{keyword}**: {count}次")
            content.append("")

        raw_news = data.get('raw_news', [])
        if raw_news:
            content.append("## 新闻列表")
            content.append("")

            def sort_key(item):
                return item.get('publish_ts', 0) or 0

            for index, news in enumerate(sorted(raw_news, key=sort_key, reverse=True), start=1):
                title = news.get('title', '')
                news_content = news.get('content', '')
                url = news.get('url', '')
                tags = news.get('tags', [])
                publish_time = news.get('publish_time', '')
                source = news.get('source', '')

                content.append(f"### {index}. {publish_time} {title}")
                if source:
                    content.append(f"**来源**: {source}")
                if url:
                    content.append(f"**链接**: [{url}]({url})")
                if tags:
                    content.append(f"**标签**: {', '.join(tags)}")
                content.append("")
                content.append(news_content)
                content.append("")
                content.append("---")
                content.append("")

        return '\n'.join(content)

    def _generate_summary_content(self, data: Dict, report_title: str, source_type: str) -> str:
        content: List[str] = []
        content.append(report_title)
        content.append("")
        content.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("")

        raw_news = data.get('raw_news', [])
        sorted_news = self._sort_news(raw_news)

        if source_type == "jygs":
            content.append("## 连板/高度重点")
            content.append("")
            highlights = self._jygs_highlights(sorted_news, limit=15)
            if highlights:
                for item in highlights:
                    content.append(item)
            else:
                content.append("- 无明显连板/高度条目")
            content.append("")
            content.append("## 重点条目")
            content.append("")
            for item in self._format_news_list(sorted_news[:15]):
                content.append(item)
            return '\n'.join(content)

        content.append("## 关键要点")
        content.append("")
        for item in self._key_points(sorted_news, limit=6):
            content.append(item)
        content.append("")

        content.append("## 重点消息")
        content.append("")
        for item in self._format_news_list(self._important_news(sorted_news, limit=15)):
            content.append(item)

        return '\n'.join(content)

    def _sort_news(self, raw_news: List[Dict]) -> List[Dict]:
        def sort_key(item: Dict) -> int:
            return item.get('publish_ts', 0) or 0
        return sorted(raw_news, key=sort_key, reverse=True)

    def _format_news_list(self, items: List[Dict]) -> List[str]:
        lines: List[str] = []
        for news in items:
            title = news.get('title', '')
            publish_time = news.get('publish_time', '')
            source = news.get('source', '')
            url = news.get('url', '')
            if url:
                line = f"- [{publish_time}] {title}（{source}）[{url}]({url})"
            else:
                line = f"- [{publish_time}] {title}（{source}）"
            lines.append(line)
        return lines

    def _key_points(self, items: List[Dict], limit: int) -> List[str]:
        important = self._important_news(items, limit=limit)
        return self._format_news_list(important)

    def _important_news(self, items: List[Dict], limit: int) -> List[Dict]:
        scored = []
        for news in items:
            score = self._importance_score(news)
            scored.append((score, news))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [news for _, news in scored if _ > 0]
        if len(picked) < limit:
            existing_ids = {id(item) for item in picked}
            for news in items:
                if id(news) in existing_ids:
                    continue
                picked.append(news)
                if len(picked) >= limit:
                    break
        return picked[:limit]

    def _importance_score(self, news: Dict) -> int:
        title = news.get('title', '')
        content = news.get('content', '')
        tags = news.get('tags', [])
        text = f"{title} {content}"

        keywords = [
            "央行", "美联储", "政策", "监管", "利率", "降准", "加息", "降息",
            "通胀", "就业", "PMI", "GDP", "财政", "国债", "外汇", "美元",
            "原油", "黄金", "中美", "关税", "制裁", "IPO", "并购", "重组",
            "减持", "回购", "业绩", "预增", "预减", "暴雷", "停产", "事故",
            "处罚", "问询", "风险", "地缘", "突发", "紧急", "回应",
        ]

        score = 0
        for kw in keywords:
            if kw in text:
                score += 2
        if isinstance(tags, list):
            score += len(tags)
        if "涨停" in text or "跌停" in text:
            score += 2
        return score

    def _jygs_highlights(self, items: List[Dict], limit: int) -> List[str]:
        lines: List[str] = []
        for news in items:
            title = news.get('title', '')
            content = news.get('content', '')
            publish_time = news.get('publish_time', '')
            source = news.get('source', '')
            url = news.get('url', '')
            text = f"{title} {content}"
            if any(k in text for k in ["连板", "涨停", "高度", "板", "封板"]):
                prefix = "🔥 "
                if url:
                    line = f"- {prefix}[{publish_time}] {title}（{source}）[{url}]({url})"
                else:
                    line = f"- {prefix}[{publish_time}] {title}（{source}）"
                lines.append(line)
            if len(lines) >= limit:
                break
        return lines
