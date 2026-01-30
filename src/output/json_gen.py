"""
JSON输出生成器
"""

import json
from datetime import datetime
from typing import Dict
from pathlib import Path


class JSONGenerator:
    """JSON输出生成器"""
    
    def __init__(self, config):
        self.config = config
        self.output_dir = config.PROCESSED_DATA_DIR
    
    def generate(self, aggregated_data: Dict, filename_prefix: str = "cailian_news", source_name: str = "财联社") -> str:
        """生成JSON文件"""
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{filename_prefix}_{timestamp}.json"
        filepath = self.output_dir / filename
        
        # 添加元数据
        output_data = {
            'metadata': self._generate_metadata(aggregated_data, source_name=source_name),
            'data': aggregated_data
        }
        
        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=self.config.JSON_INDENT)
        
        return str(filepath)
    
    def _generate_metadata(self, aggregated_data: Dict, source_name: str) -> Dict:
        """生成元数据"""
        summary = aggregated_data.get('summary', {}) if isinstance(aggregated_data, dict) else {}
        return {
            'generated_at': datetime.now().isoformat(),
            'generator': '财联社新闻收集工具',
            'version': '1.0.0',
            'source': source_name,
            'format': 'json',
            'time_range': summary.get('time_range', '无数据'),
            'total_news': summary.get('total_news', 0),
            'description': '财联社新闻聚合数据，包含统计信息和分类汇总'
        }
