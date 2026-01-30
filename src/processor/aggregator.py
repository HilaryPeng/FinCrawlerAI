"""
数据聚合器
"""

from typing import List, Dict
from collections import Counter, defaultdict
from datetime import datetime


class DataAggregator:
    """数据聚合器"""
    
    def __init__(self, config):
        self.config = config
    
    def aggregate(self, news_list: List[Dict]) -> Dict:
        """聚合新闻数据"""
        if not news_list:
            return self._empty_aggregation()
        
        aggregated_data = {
            'summary': self._generate_summary(news_list),
            'statistics': self._generate_statistics(news_list),
            'news_by_time': self._group_by_time(news_list),
            'news_by_tags': self._group_by_tags(news_list),
            'top_keywords': self._extract_top_keywords(news_list),
            'raw_news': news_list
        }
        
        return aggregated_data
    
    def _empty_aggregation(self) -> Dict:
        """空数据聚合"""
        return {
            'summary': {
                'total_news': 0,
                'time_range': '无数据',
                'main_topics': []
            },
            'statistics': {
                'news_count': 0,
                'tag_distribution': {},
                'time_distribution': {}
            },
            'news_by_time': {},
            'news_by_tags': {},
            'top_keywords': [],
            'raw_news': []
        }
    
    def _generate_summary(self, news_list: List[Dict]) -> Dict:
        """生成摘要"""
        total_news = len(news_list)
        
        # 时间范围
        times = [news.get('publish_time', '') for news in news_list if news.get('publish_time')]
        time_range = f"{min(times)} - {max(times)}" if times else "未知"
        
        # 主要话题
        all_tags = []
        for news in news_list:
            tags = news.get('tags', [])
            if isinstance(tags, list):
                all_tags.extend(tags)
        
        tag_counter = Counter(all_tags)
        main_topics = [tag for tag, count in tag_counter.most_common(5)]
        
        return {
            'total_news': total_news,
            'time_range': time_range,
            'main_topics': main_topics
        }
    
    def _generate_statistics(self, news_list: List[Dict]) -> Dict:
        """生成统计信息"""
        # 标签分布
        all_tags = []
        for news in news_list:
            all_tags.extend(news.get('tags', []))
        
        tag_distribution = dict(Counter(all_tags))
        
        # 时间分布
        time_distribution = defaultdict(int)
        for news in news_list:
            publish_time = news.get('publish_time', '')
            if publish_time:
                # 提取小时
                hour = publish_time.split(' ')[1].split(':')[0] if ' ' in publish_time else '00'
                time_distribution[f"{hour}:00"] += 1
        
        return {
            'news_count': len(news_list),
            'tag_distribution': tag_distribution,
            'time_distribution': dict(time_distribution)
        }
    
    def _group_by_time(self, news_list: List[Dict]) -> Dict:
        """按时间分组"""
        grouped = defaultdict(list)
        
        for news in news_list:
            publish_time = news.get('publish_time', '')
            if publish_time:
                # 按日期分组
                date = publish_time.split(' ')[0] if ' ' in publish_time else publish_time
                grouped[date].append(news)
        
        return dict(grouped)
    
    def _group_by_tags(self, news_list: List[Dict]) -> Dict:
        """按标签分组"""
        grouped = defaultdict(list)
        
        for news in news_list:
            tags = news.get('tags', [])
            for tag in tags:
                grouped[tag].append(news)
        
        return dict(grouped)
    
    def _extract_top_keywords(self, news_list: List[Dict]) -> List[Dict]:
        """提取热门关键词"""
        # 简单的关键词提取
        all_text = []
        for news in news_list:
            title = news.get('title', '')
            content = news.get('content', '')
            all_text.append(title)
            all_text.append(content)
        
        combined_text = ' '.join(all_text)
        
        # 这里可以使用更复杂的NLP技术，目前使用简单的词频统计
        keywords = self._simple_keyword_extraction(combined_text)
        
        return keywords
    
    def _simple_keyword_extraction(self, text: str) -> List[Dict]:
        """简单的关键词提取"""
        # 金融相关关键词
        financial_keywords = [
            'A股', '港股', '美股', '股市', '股票', '上证', '深证', '创业板',
            '基金', '债券', '期货', '外汇', '黄金', '石油', '经济', '金融',
            '银行', '保险', '证券', '投资', '融资', '并购', '重组', '业绩'
        ]
        
        keyword_counts = []
        for keyword in financial_keywords:
            count = text.count(keyword)
            if count > 0:
                keyword_counts.append({'keyword': keyword, 'count': count})
        
        # 按出现次数排序
        keyword_counts.sort(key=lambda x: x['count'], reverse=True)
        
        return keyword_counts[:10]  # 返回前10个关键词