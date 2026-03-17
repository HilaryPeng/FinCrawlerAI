"""
数据聚合器
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Dict, Tuple, Any
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

        events = self._build_events(news_list)
        stats = self._generate_statistics(news_list)
        stats["event_count"] = len(events)
        
        aggregated_data = {
            'summary': self._generate_summary(news_list),
            'statistics': stats,
            'news_by_time': self._group_by_time(news_list),
            'news_by_tags': self._group_by_tags(news_list),
            'top_keywords': self._extract_top_keywords(news_list),
            'events': events,
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
                'event_count': 0,
                'tag_distribution': {},
                'time_distribution': {}
            },
            'news_by_time': {},
            'news_by_tags': {},
            'top_keywords': [],
            'events': [],
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
            # 事件数在 aggregate 里生成 events 后再补；这里保持字段存在，便于下游展示
            'event_count': 0,
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

    # -----------------------------
    # Event clustering / importance
    # -----------------------------
    def _build_events(self, news_list: List[Dict]) -> List[Dict]:
        """将多条新闻归并为“事件”并打分（可解释）"""
        items = [n for n in news_list if isinstance(n, dict)]

        # 先按 URL 去重（跨源也可能复用同链接）
        unique: List[Dict] = []
        seen_urls = set()
        for n in items:
            url = (n.get("url") or "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            unique.append(n)

        # 时间倒序，有利于“最新代表事件标题”
        unique.sort(key=lambda x: x.get("publish_ts", 0) or 0, reverse=True)

        clusters: List[Dict[str, Any]] = []
        window_seconds = 30 * 60
        max_hamming = 3

        for n in unique:
            ts = int(n.get("publish_ts", 0) or 0)
            fp = self._simhash64(self._event_text(n))

            matched = None
            for c in clusters:
                # 时间窗过滤（先粗筛）
                rep_ts = int(c.get("rep_ts", 0) or 0)
                if ts and rep_ts and abs(ts - rep_ts) > window_seconds:
                    continue
                if self._hamming64(fp, int(c["rep_fp"])) <= max_hamming:
                    matched = c
                    break

            if not matched:
                clusters.append(
                    {
                        "rep_fp": fp,
                        "rep_ts": ts,
                        "items": [n],
                    }
                )
            else:
                matched["items"].append(n)
                # 用最新的条目作为代表（标题更像“事件标题”）
                if ts >= int(matched.get("rep_ts", 0) or 0):
                    matched["rep_ts"] = ts
                    matched["rep_fp"] = fp

        events: List[Dict] = []
        for idx, c in enumerate(clusters, start=1):
            items2: List[Dict] = c["items"]
            items2.sort(key=lambda x: x.get("publish_ts", 0) or 0, reverse=True)

            # 代表标题：最新条目标题
            rep = items2[0] if items2 else {}
            title = rep.get("title", "") or ""
            event_id = self._event_id(items2)

            score, reasons = self._event_importance(items2)
            sources = sorted({(it.get("source") or "").strip() for it in items2 if it.get("source")})

            ts_list = [int(it.get("publish_ts", 0) or 0) for it in items2 if int(it.get("publish_ts", 0) or 0) > 0]
            start_ts = min(ts_list) if ts_list else 0
            end_ts = max(ts_list) if ts_list else 0

            events.append(
                {
                    "event_id": event_id,
                    "title": title,
                    "score": score,
                    "reasons": reasons,
                    "sources": sources,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "count": len(items2),
                    "items": items2,
                }
            )

        # 排序：先按分数，再按被提及次数，再按最新时间
        events.sort(key=lambda e: (e.get("score", 0), e.get("count", 0), e.get("end_ts", 0)), reverse=True)

        # 回填统计字段
        #（保持在同一个 Dict 内，避免在 main/output 额外计算）
        try:
            # 这里不改 summary 结构，单独放 statistics.event_count
            pass
        except Exception:
            pass

        return events

    def _event_text(self, news: Dict) -> str:
        title = str(news.get("title", "") or "")
        content = str(news.get("content", "") or "")
        tags = news.get("tags", [])
        tag_text = " ".join([str(t) for t in tags]) if isinstance(tags, list) else ""
        return f"{title} {content} {tag_text}".strip()

    def _normalize_event_text(self, text: str) -> str:
        # 去掉数字、空白、部分噪声符号；保留中英文与常见金融字符
        text = text.lower()
        text = re.sub(r"\d+", "", text)
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
        return text

    def _simhash64(self, text: str) -> int:
        """无依赖 simhash(64bit)，对中文用字符 2-gram 做 token"""
        text = self._normalize_event_text(text)
        if not text:
            return 0

        # 2-gram tokens（兼容中文/英文）
        grams = [text[i : i + 2] for i in range(max(len(text) - 1, 1))]
        freq = Counter(grams)

        v = [0] * 64
        for tok, w in freq.items():
            h = hashlib.md5(tok.encode("utf-8")).digest()
            x = int.from_bytes(h[:8], "big", signed=False)
            for i in range(64):
                bit = 1 if (x >> i) & 1 else -1
                v[i] += bit * int(w)

        out = 0
        for i in range(64):
            if v[i] >= 0:
                out |= 1 << i
        return out

    def _hamming64(self, a: int, b: int) -> int:
        x = (a ^ b) & ((1 << 64) - 1)
        # Python 3.8+: int.bit_count
        return x.bit_count()

    def _event_id(self, items: List[Dict]) -> str:
        # 使用“归一化文本 + 时间窗”生成稳定 id（不含隐私字段）
        base = ""
        if items:
            base = self._normalize_event_text(self._event_text(items[0]))[:256]
        ts = str(int(items[0].get("publish_ts", 0) or 0)) if items else "0"
        raw = f"{ts}|{base}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _event_importance(self, items: List[Dict]) -> Tuple[int, List[str]]:
        """对“事件”打分，并返回原因列表（可解释）"""
        reasons: List[str] = []
        score = 0

        # 覆盖度：同事件多条/多源
        count = len(items)
        if count >= 2:
            add = min(6, 2 + count)  # 最多加 6
            score += add
            reasons.append(f"多条提及（{count}条）+{add}")

        sources = {str(it.get("source") or "").strip() for it in items if it.get("source")}
        if len(sources) >= 2:
            score += 4
            reasons.append(f"跨源覆盖（{len(sources)}源）+4")

        # 文本关键词/标签：从“代表条目 + 合并文本”里取
        text = " ".join([self._event_text(it) for it in items[:3]])  # 控制长度

        # 重大宏观/监管/突发
        macro = [
            "央行", "美联储", "政策", "监管", "利率", "降准", "加息", "降息",
            "通胀", "就业", "PMI", "GDP", "财政", "国债", "外汇", "美元",
            "关税", "制裁", "地缘", "突发", "紧急", "回应",
        ]
        hit_macro = [k for k in macro if k in text]
        if hit_macro:
            add = min(10, 2 * len(set(hit_macro)))
            score += add
            reasons.append(f"宏观/监管/突发关键词({','.join(sorted(set(hit_macro))[:6])})+{add}")

        # 公司/资本市场强信号
        corp = ["IPO", "并购", "重组", "减持", "回购", "业绩", "预增", "预减", "暴雷", "停产", "事故", "处罚", "问询", "停牌"]
        hit_corp = [k for k in corp if k in text]
        if hit_corp:
            add = min(8, 2 * len(set(hit_corp)))
            score += add
            reasons.append(f"公司/资本市场信号({','.join(sorted(set(hit_corp))[:6])})+{add}")

        # 价格/情绪线索（韭研公社更常见）
        if any(k in text for k in ["涨停", "跌停", "连板", "封板", "高度"]):
            score += 4
            reasons.append("价格/情绪线索（涨停/连板等）+4")

        # 标签数量（避免过拟合，轻微加分）
        tags_all: List[str] = []
        for it in items:
            t = it.get("tags", [])
            if isinstance(t, list):
                tags_all.extend([str(x) for x in t if x])
        if tags_all:
            add = min(4, len(set(tags_all)))
            score += add
            reasons.append(f"标签覆盖（{len(set(tags_all))}）+{add}")

        return score, reasons