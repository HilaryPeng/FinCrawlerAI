"""
Stock mention extractor from text.
"""

import re
from typing import List, Dict, Any

from src.utils.symbols import normalize_symbol


class StockMentionExtractor:
    """Extract stock symbols and names from text."""
    
    STOCK_CODE_PATTERN = re.compile(r'(?:sz|sh)?(\d{6})')
    
    COMMON_STOCK_NAMES = {
        "平安": ("000001", "平安银行"),
        "万科": ("000002", "万科A"),
        "国农科技": ("000004", "国农科技"),
        "世纪星源": ("000005", "世纪星源"),
        "深振业": ("000006", "深振业A"),
        "全新好": ("000007", "全新好"),
        "神州高铁": ("000008", "神州高铁"),
        "中国宝安": ("000009", "中国宝安"),
        "美丽生态": ("000010", "美丽生态"),
        "深物业A": ("000011", "深物业A"),
        "南玻A": ("000012", "南玻A"),
        "沙河股份": ("000014", "沙河股份"),
        "深康佳A": ("000016", "深康佳A"),
        "深中华A": ("000017", "深中华A"),
        "神州长城": ("000018", "神州长城"),
        "深深宝A": ("000019", "深深宝A"),
        "深华发A": ("000020", "深华发A"),
        "深科技": ("000021", "深科技"),
        "深赤湾A": ("000022", "深赤湾A"),
        "深天地A": ("000023", "深天地A"),
        "招商地产": ("000024", "招商地产"),
        "特力A": ("000025", "特力A"),
        "飞亚达": ("000026", "飞亚达A"),
        "深圳能源": ("000027", "深圳能源"),
        "国药一致": ("000028", "国药一致"),
        "深深房A": ("000029", "深深房A"),
        "富奥股份": ("000030", "富奥股份"),
        "中粮地产": ("000031", "中粮地产"),
        "深桑达A": ("000032", "深桑达A"),
        "新都退": ("000033", "新都退"),
        "神州数码": ("000034", "神州数码"),
        "中国天楹": ("000035", "中国天楹"),
        "华联控股": ("000036", "华联控股"),
        "深南电A": ("000037", "深南电A"),
        "深大通": ("000038", "深大通"),
        "中集集团": ("000039", "中集集团"),
        "东旭蓝天": ("000040", "东旭蓝天"),
        "贵州茅台": ("600519", "贵州茅台"),
        "中国平安": ("601318", "中国平安"),
        "招商银行": ("600036", "招商银行"),
        "兴业银行": ("601166", "兴业银行"),
        "工商银行": ("601398", "工商银行"),
        "建设银行": ("601939", "建设银行"),
        "农业银行": ("601288", "农业银行"),
        "中国银行": ("601988", "中国银行"),
        "比亚迪": ("002594", "比亚迪"),
        "宁德时代": ("300750", "宁德时代"),
        "隆基股份": ("601012", "隆基绿能"),
        "恒瑞医药": ("600276", "恒瑞医药"),
        "药明康德": ("603259", "药明康德"),
        "五粮液": ("000858", "五粮液"),
        "泸州老窖": ("000568", "泸州老窖"),
        "海康威视": ("002415", "海康威视"),
        "美的集团": ("000333", "美的集团"),
        "格力电器": ("000651", "格力电器"),
    }
    
    def extract(self, text: str) -> List[Dict[str, Any]]:
        """Extract stock mentions from text."""
        results = []
        
        for name, (code, full_name) in self.COMMON_STOCK_NAMES.items():
            if name in text:
                symbol = normalize_symbol(code)
                results.append({
                    "symbol": symbol,
                    "name": full_name,
                })
        
        codes = self.STOCK_CODE_PATTERN.findall(text)
        for code in set(codes):
            if len(code) == 6:
                symbol = normalize_symbol(code)
                if not any(r["symbol"] == symbol for r in results):
                    results.append({
                        "symbol": symbol,
                        "name": code,
                    })
        
        return results

    def normalize(self, code: str) -> str:
        """Normalize a stock code to the project's symbol format."""
        return normalize_symbol(code)
