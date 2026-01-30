"""
Markdown输出生成器
"""

from datetime import datetime
from typing import Dict


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
