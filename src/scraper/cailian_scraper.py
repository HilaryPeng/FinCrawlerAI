"""
财联社新闻抓取器
"""

import time
import random
import hashlib
from typing import List, Dict, Optional, Any
import requests
from bs4 import BeautifulSoup
from datetime import datetime


class CailianScraper:
    """财联社新闻抓取器"""
    
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(config.REQUEST_HEADERS)
    
    def scrape_news(self, since_ts: Optional[int] = None, until_ts: Optional[int] = None) -> List[Dict]:
        """抓取新闻列表"""
        news_list = []
        
        try:
            # 首先尝试从API获取
            api_news = self._fetch_from_api(since_ts=since_ts, until_ts=until_ts)
            if api_news:
                news_list.extend(api_news)
            
            # 如果API失败，尝试网页抓取
            if not news_list:
                web_news = self._fetch_from_web()
                news_list.extend(web_news)
            
        except Exception as e:
            print(f"抓取新闻时出错: {e}")
        
        return news_list
    
    def _fetch_from_api(self, since_ts: Optional[int], until_ts: Optional[int]) -> List[Dict]:
        """从API获取新闻"""
        try:
            since_ts = since_ts or int(time.time()) - self.config.CRAWL_LOOKBACK_SECONDS
            until_ts = until_ts or int(time.time())
            return self._fetch_roll_list(since_ts=since_ts, until_ts=until_ts)
            
        except Exception as e:
            print(f"API请求失败: {e}")
            return []
    
    def _fetch_from_web(self) -> List[Dict]:
        """从网页抓取新闻"""
        try:
            url = self.config.CAILIAN_BASE_URL
            response = self.session.get(url, timeout=self.config.TIMEOUT)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            return self._parse_web_content(soup)
            
        except Exception as e:
            print(f"网页抓取失败: {e}")
            return []
    
    def _fetch_roll_list(self, since_ts: int, until_ts: int) -> List[Dict]:
        """滚动抓取快讯列表"""
        news_list: List[Dict] = []
        last_time = int(until_ts)
        stop = False

        for _ in range(self.config.MAX_PAGES):
            params = {
                "refresh_type": 1,
                "rn": self.config.PAGE_SIZE,
                "last_time": last_time,
                "category": ""
            }
            data = self._request_roll_list(params)
            roll_data = data.get("data", {}).get("roll_data", []) if isinstance(data, dict) else []

            if not roll_data:
                break

            for item in roll_data:
                ctime = item.get("ctime") or item.get("sort_score")
                if not isinstance(ctime, int):
                    try:
                        ctime = int(ctime)
                    except Exception:
                        ctime = None

                if ctime is None:
                    continue

                if ctime <= since_ts:
                    stop = True
                    break

                news_item = self._normalize_roll_item(item, ctime)
                if news_item:
                    news_list.append(news_item)

            last_item_time = roll_data[-1].get("ctime") or roll_data[-1].get("sort_score")
            try:
                last_item_time = int(last_item_time)
            except Exception:
                last_item_time = last_time - 1

            last_time = last_item_time
            if stop or last_time <= since_ts:
                break

            self._delay_request()

        return news_list

    def _request_roll_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """请求快讯列表API"""
        api_url = f"{self.config.CAILIAN_BASE_URL}{self.config.CAILIAN_TELEGRAPH_API_PATH}"
        signed_params = self._sign_params(params)
        response = self.session.get(api_url, params=signed_params, timeout=self.config.TIMEOUT)
        response.raise_for_status()
        return response.json()

    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """生成签名参数"""
        merged = dict(params or {})
        merged["os"] = "web"
        merged["sv"] = "8.4.6"
        merged["app"] = "CailianpressWeb"

        serialized = self._serialize_params(merged)
        sha1_hash = hashlib.sha1(serialized.encode("utf-8")).hexdigest()
        sign = hashlib.md5(sha1_hash.encode("utf-8")).hexdigest()

        merged_sorted = dict(sorted(merged.items(), key=lambda item: str(item[0]).upper()))
        merged_sorted["sign"] = sign
        return merged_sorted

    def _serialize_params(self, params: Dict[str, Any]) -> str:
        """序列化参数用于签名"""
        def normalize_value(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        def serialize_key(key: str, value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (str, int, float, bool)):
                return [f"{key}={normalize_value(value)}"]
            if isinstance(value, list):
                if not value:
                    return [f"{key}[]"]
                items: List[str] = []
                for idx, item in enumerate(value):
                    items.extend(serialize_key(f"{key}[{idx}]", item))
                return items
            if isinstance(value, dict):
                items: List[str] = []
                for sub_key in sorted(value.keys()):
                    items.extend(serialize_key(f"{key}[{sub_key}]", value[sub_key]))
                return items
            return [f"{key}={normalize_value(value)}"]

        parts: List[str] = []
        for key in sorted(params.keys()):
            parts.extend(serialize_key(key, params[key]))

        parts = [item for item in parts if item]
        return "&".join(parts)

    def _normalize_roll_item(self, item: Dict[str, Any], ctime: int) -> Optional[Dict]:
        """规范化快讯条目"""
        title = item.get("title") or ""
        content = item.get("content") or item.get("brief") or title
        content = self._clean_html(content)
        title = self._clean_html(title) if title else content[:50]

        article_id = item.get("id")
        url = item.get("shareurl") or (f"{self.config.CAILIAN_BASE_URL}/detail/{article_id}" if article_id else "")

        return {
            "title": title,
            "content": content,
            "publish_time": self._format_timestamp(ctime),
            "publish_ts": ctime,
            "source": "财联社",
            "url": url,
            "tags": self._extract_tags(f"{title} {content}")
        }
    
    def _parse_telegraph_page(self, soup: BeautifulSoup) -> List[Dict]:
        """解析财联社快讯页面"""
        news_list = []
        
        try:
            # 查找快讯列表
            telegraph_items = soup.find_all('div', class_='telegraph-item')
            if not telegraph_items:
                # 尝试其他可能的选择器
                additional_items = []
                for div in soup.find_all('div'):
                    classes = div.get('class')
                    if classes and any('telegraph' in str(cls).lower() for cls in classes):
                        additional_items.append(div)
                telegraph_items = additional_items
            
            if not telegraph_items:
                # 查找包含时间的内容项
                telegraph_items = soup.find_all(['div', 'li'], {'data-time': True})
            
            if not telegraph_items:
                # 最后尝试：查找包含时间文本的元素
                additional_items = []
                for elem in soup.find_all(['div', 'li', 'article']):
                    text = elem.get_text(strip=True)
                    if any(keyword in text for keyword in [':', '】', '】', '时', '分']):
                        if len(text) > 10 and len(text) < 500:
                            additional_items.append(elem)
                telegraph_items = additional_items
            
            for item in telegraph_items[:50]:  # 限制最多50条
                try:
                    title_elem = item.find('h3') or item.find('h4') or item.find('a') or item.find('span', class_='title')
                    content_elem = item.find('p') or item.find('div', class_='content') or item
                    time_elem = item.find('time') or item.find('span', class_='time') or item.find('div', class_='time')
                    
                    # 如果没有找到标题元素，使用整个项的文本
                    title_text = ''
                    content_text = ''
                    
                    if title_elem:
                        title_text = title_elem.get_text(strip=True)
                    
                    if content_elem:
                        content_text = content_elem.get_text(strip=True)
                    else:
                        content_text = item.get_text(strip=True)
                    
                    # 如果标题为空，使用内容的前50个字符作为标题
                    if not title_text and content_text:
                        title_text = content_text[:50] + '...' if len(content_text) > 50 else content_text
                    elif not title_text:
                        continue
                    
                    # 获取时间
                    time_text = ''
                    if time_elem:
                        time_text = time_elem.get_text(strip=True)
                    else:
                        # 尝试从文本中提取时间
                        import re
                        time_pattern = r'(\d{1,2}:\d{2})'
                        time_match = re.search(time_pattern, item.get_text())
                        if time_match:
                            time_text = time_match.group(1)
                    
                    news_item = {
                        'title': title_text,
                        'content': content_text,
                        'publish_time': self._parse_time(time_text),
                        'publish_ts': self._parse_time_to_ts(time_text),
                        'source': '财联社',
                        'url': f"https://www.cls.cn/telegraph#{hash(title_text)}",
                        'tags': self._extract_tags(title_text + ' ' + content_text)
                    }
                    news_list.append(news_item)
                    
                except Exception as e:
                    print(f"解析单个新闻项时出错: {e}")
                    continue
                    
        except Exception as e:
            print(f"解析财联社快讯页面时出错: {e}")
        
        return news_list

    def _parse_web_content(self, soup: BeautifulSoup) -> List[Dict]:
        """解析网页内容"""
        return self._parse_telegraph_page(soup)
    
    def _parse_time(self, time_str: str) -> str:
        """解析时间字符串"""
        try:
            if not time_str:
                return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if isinstance(time_str, (int, float)):
                return self._format_timestamp(int(time_str))

            time_str = str(time_str).strip()
            if time_str.isdigit():
                return self._format_timestamp(int(time_str))

            if ":" in time_str and len(time_str) <= 5:
                today = datetime.now().strftime('%Y-%m-%d')
                return f"{today} {time_str}:00"

            return time_str
        except Exception:
            return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _parse_time_to_ts(self, time_str: str) -> int:
        """解析时间字符串为时间戳"""
        try:
            if not time_str:
                return 0

            if isinstance(time_str, (int, float)):
                return int(time_str)

            time_str = str(time_str).strip()
            if time_str.isdigit():
                return int(time_str)

            if ":" in time_str and len(time_str) <= 5:
                today = datetime.now().strftime('%Y-%m-%d')
                dt = datetime.strptime(f"{today} {time_str}", "%Y-%m-%d %H:%M")
                return int(dt.timestamp())

            dt = datetime.fromisoformat(time_str)
            return int(dt.timestamp())
        except Exception:
            return 0

    def _format_timestamp(self, ts: int) -> str:
        """时间戳格式化"""
        try:
            return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _clean_html(self, text: str) -> str:
        """清理HTML内容"""
        if not text:
            return ""
        try:
            soup = BeautifulSoup(text, "lxml")
            return soup.get_text(" ", strip=True)
        except Exception:
            return str(text).strip()
    
    def _extract_tags(self, text: str) -> List[str]:
        """从文本中提取标签"""
        tags = []
        
        # 简单的关键词匹配
        keywords = ['A股', '港股', '美股', '股市', '股票', '基金', '债券', '期货', '外汇', '经济', '金融']
        
        for keyword in keywords:
            if keyword in text:
                tags.append(keyword)
        
        return tags
    
    def _delay_request(self):
        """请求延迟"""
        delay = self.config.REQUEST_DELAY + random.uniform(0, 1)
        time.sleep(delay)
