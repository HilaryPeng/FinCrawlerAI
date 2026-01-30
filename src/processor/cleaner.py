"""
数据清洗器
"""

import re
from typing import List, Dict
from difflib import SequenceMatcher


class DataCleaner:
    """数据清洗器"""
    
    def __init__(self, config):
        self.config = config
    
    def clean_news(self, news_list: List[Dict]) -> List[Dict]:
        """清洗新闻数据"""
        cleaned_news = []
        
        # 1. 过滤无效新闻
        valid_news = self._filter_invalid_news(news_list)
        
        # 2. 去重
        deduplicated_news = self._remove_duplicates(valid_news)
        
        # 3. 标准化格式
        standardized_news = self._standardize_format(deduplicated_news)
        
        return standardized_news
    
    def _filter_invalid_news(self, news_list: List[Dict]) -> List[Dict]:
        """过滤无效新闻"""
        valid_news = []
        
        for news in news_list:
            # 检查内容长度
            content_length = len(news.get('content', ''))
            if content_length < self.config.MIN_CONTENT_LENGTH:
                continue
            if content_length > self.config.MAX_CONTENT_LENGTH:
                continue
            
            # 检查必要字段
            if not news.get('title') or not news.get('content'):
                continue
            
            valid_news.append(news)
        
        return valid_news
    
    def _remove_duplicates(self, news_list: List[Dict]) -> List[Dict]:
        """去重"""
        unique_news = []
        seen_contents = set()
        
        for news in news_list:
            content = news.get('content', '')
            title = news.get('title', '')
            
            # 检查内容相似度
            is_duplicate = False
            for seen_content in seen_contents:
                similarity = SequenceMatcher(None, content, seen_content).ratio()
                if similarity > self.config.DUPLICATE_THRESHOLD:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_news.append(news)
                seen_contents.add(content)
        
        return unique_news
    
    def _standardize_format(self, news_list: List[Dict]) -> List[Dict]:
        """标准化格式"""
        standardized_news = []
        
        for news in news_list:
            standardized_item = {
                'title': self._clean_text(news.get('title', '')),
                'content': self._clean_text(news.get('content', '')),
                'publish_time': news.get('publish_time', ''),
                'publish_ts': news.get('publish_ts', 0),
                'source': news.get('source', '财联社'),
                'url': news.get('url', ''),
                'tags': news.get('tags', [])
            }
            standardized_news.append(standardized_item)
        
        return standardized_news
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ''
        
        # 移除多余的空白字符
        text = re.sub(r'\s+', ' ', text)
        
        # 移除特殊字符（保留常见金融符号，如 + - / %）
        text = re.sub(r'[^\w\s\u4e00-\u9fff,.!?;:()（）。，！？；：+\-/%#]', '', text)
        
        # 去除首尾空白
        text = text.strip()
        
        return text
